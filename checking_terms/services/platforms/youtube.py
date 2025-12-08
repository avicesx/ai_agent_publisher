import logging
from typing import Dict
from services.base_checker import BasePolicyChecker
from core.youtube_policy_checker import YouTubePolicyChecker
import config

logger = logging.getLogger(__name__)


class YouTubePolicyService(BasePolicyChecker):
    """
    Обертка над оригинальным YouTubePolicyChecker
    для интеграции в единую архитектуру
    """
    
    def __init__(self):
        """Инициализация с параметрами из config"""
        logger.info("Инициализация YouTube Policy Service...")
        self.checker = YouTubePolicyChecker(
            tiny2_path=config.TINY2_MODEL_PATH,
            base_path=config.BASE_MODEL_PATH,
            threshold=config.DECISION_THRESHOLD,
            weight_tiny2=config.WEIGHT_TINY2,
            weight_base=config.WEIGHT_BASE,
            max_length=config.MAX_LENGTH
        )
        logger.info("YouTube Policy Service готов")
    
    def check(self, text: str) -> Dict:
        """
        Проверка текста на соответствие политике YouTube
        
        Args:
            text: Текст для проверки
        Returns:
            dict с verdict, confidence, details
        """
        result = self.checker.predict(text)
        
        verdict = "BLOCK" if result["label"] == "Не соответствует" else "ALLOW"
        
        return {
            "verdict": verdict,
            "confidence": result["confidence"],
            "details": result["details"]
        }
    
    def get_platform_name(self) -> str:
        return "youtube"
