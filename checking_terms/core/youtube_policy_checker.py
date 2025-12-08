import logging
from typing import Dict, List
from transformers import AutoModelForSequenceClassification, AutoTokenizer
import torch

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class YouTubePolicyChecker:
    def __init__(
            self,
            tiny2_path: str,
            base_path: str,
            threshold: float = 0.6,
            weight_tiny2: float = 0.7,
            weight_base: float = 0.3,
            max_length: int = 512
    ):
        """
        Агент для классификации текста на соответствие политике YouTube.

        Args:
            tiny2_path: путь к модели cointegrated/rubert-tiny2
            base_path: путь к модели rubert-base-cased
            threshold: порог уверенности для класса "нарушение"
            weight_tiny2: вес модели tiny2 в ансамбле
            weight_base: вес модели base в ансамбле
            max_length: максимальная длина токенов
        """
        self.max_length = max_length
        self.threshold = threshold
        self.weight_tiny2 = weight_tiny2
        self.weight_base = weight_base

        logger.info("Загружаем модели...")
        self.model1 = AutoModelForSequenceClassification.from_pretrained(tiny2_path)
        self.tokenizer1 = AutoTokenizer.from_pretrained(tiny2_path)

        self.model2 = AutoModelForSequenceClassification.from_pretrained(base_path)
        self.tokenizer2 = AutoTokenizer.from_pretrained(base_path)

        self.model1.eval()
        self.model2.eval()
        logger.info("✅ Модели загружены")

    def predict(self, text: str) -> Dict[str, any]:
        """
        Проверяет, соответствует ли текст политике YouTube.

        Args:
            text: входной текст (транскрибированный текст из видео и т.д.)
        Returns:
            dict: {
                "label": "Соответствует" или "Не соответствует",
                "confidence": float,
                "details": {
                    "tiny2_score": float,
                    "base_score": float,
                    "final_score": float
                }
            }
        """
        try:
            with torch.no_grad():
                # —— tiny2 ——
                inputs1 = self.tokenizer1(
                    text,
                    return_tensors="pt",
                    truncation=True,
                    padding="max_length",
                    max_length=self.max_length
                )
                logits1 = self.model1(**inputs1).logits
                prob1 = torch.softmax(logits1, dim=-1).squeeze()[1].item()

                # —— base ——
                inputs2 = self.tokenizer2(
                    text,
                    return_tensors="pt",
                    truncation=True,
                    padding="max_length",
                    max_length=self.max_length
                )
                logits2 = self.model2(**inputs2).logits
                prob2 = torch.softmax(logits2, dim=-1).squeeze()[1].item()

                # —— Ансамбль моделей ——
                final_score = self.weight_tiny2 * prob1 + self.weight_base * prob2

                if final_score > self.threshold:
                    label = "Не соответствует"
                    confidence = final_score
                else:
                    label = "Соответствует"
                    confidence = 1 - final_score

                result = {
                    "label": label,
                    "confidence": round(confidence, 4),
                    "details": {
                        "tiny2_score": round(prob1, 4),
                        "base_score": round(prob2, 4),
                        "final_score": round(final_score, 4)
                    }
                }

                logger.info(f"Текст '{text[:50]}...': {label} (уверенность: {confidence:.2f})")
                return result

        except Exception as e:
            logger.error(f"Ошибка при обработке текста: {e}")
            return {
                "label": "Ошибка",
                "confidence": 0.0,
                "details": {"error": str(e)}
            }

    def predict_batch(self, texts: List[str]) -> List[Dict[str, any]]:
        """Пакетная проверка списка текстов."""
        return [self.predict(text) for text in texts]
