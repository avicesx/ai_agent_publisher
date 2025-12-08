import os
import logging
from typing import Union
from core.youtube_policy_checker import YouTubePolicyChecker
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class YouTubeContentGuard:
    """
    Агент для анализа текстового контента на соответствие политике YouTube.
    Поддерживает обработку текста, файлов и байтов.
    """

    def __init__(
            self,
            tiny2_path: str = None,
            base_path: str = None,
            decision_threshold: float = None,
            weight_a: float = None,
            weight_b: float = None
    ):
        self.analyzer = YouTubePolicyChecker(
            tiny2_path=tiny2_path or config.TINY2_MODEL_PATH,
            base_path=base_path or config.BASE_MODEL_PATH,
            threshold=decision_threshold or config.DECISION_THRESHOLD,
            weight_tiny2=weight_a or config.WEIGHT_TINY2,
            weight_base=weight_b or config.WEIGHT_BASE
        )
        logger.info("✅ YouTubeContentGuard успешно инициализирован")

    def evaluate(self, content_source: Union[str, bytes]) -> dict:
        """
        Основной метод анализа контента.

        Args:
            content_source: текст, путь к .txt или байты

        Returns:
            dict с полями: verdict ("ALLOW"/"BLOCK"/"ERROR"), confidence, details, preview
        """
        try:
            text = self._extract_content(content_source)
            if not text.strip():
                return self._make_result("ALLOW", 1.0, "Пустой текст", "")

            raw_result = self.analyzer.predict(text)
            verdict = "BLOCK" if raw_result["label"] == "Не соответствует" else "ALLOW"

            return self._make_result(
                verdict,
                raw_result["confidence"],
                raw_result["details"],
                text[:100] + "..." if len(text) > 100 else text
            )

        except Exception as e:
            logger.error(f"Ошибка при анализе: {e}")
            return self._make_result("ERROR", 0.0, {"error": str(e)}, "")

    def _extract_content(self, source: Union[str, bytes]) -> str:
        """Извлекает текст из источника."""
        if isinstance(source, bytes):
            return source.decode("utf-8").strip()
        if isinstance(source, str):
            if os.path.isfile(source) and source.endswith(".txt"):
                with open(source, "r", encoding="utf-8") as f:
                    return f.read().strip()
            return source.strip()
        raise ValueError("Ожидался str или bytes")

    def _make_result(self, verdict: str, confidence: float, details: dict, preview: str) -> dict:
        return {
            "verdict": verdict,
            "confidence": round(confidence, 4),
            "details": details,
            "preview": preview
        }

    def is_safe(self, text: str) -> bool:
        """Возвращает True, если контент безопасен."""
        return self.evaluate(text)["verdict"] == "ALLOW"