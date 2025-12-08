from abc import ABC, abstractmethod
from typing import Dict


class BasePolicyChecker(ABC):
    """
    Базовый класс для всех policy checkers.
    Используется для единообразия проверки контента на разных платформах.
    """
    
    @abstractmethod
    def check(self, text: str) -> Dict:
        """
        Проверить текст на соответствие политике платформы
        
        Args:
            text: Текст для проверки
        Returns:
            dict: {
                "verdict": ALLOW или BLOCK,
                "confidence": float,
                "details": dict
            }
        """
        pass
    
    @abstractmethod
    def get_platform_name(self) -> str:
        """Возвращает имя платформы (youtube, rutube, vk)"""
        pass
