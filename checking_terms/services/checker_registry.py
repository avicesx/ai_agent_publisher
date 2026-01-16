from typing import Dict, Type
from services.base_checker import BasePolicyChecker
from services.platforms import YouTubePolicyService


CHECKERS: Dict[str, Type[BasePolicyChecker]] = {
    "youtube": YouTubePolicyService,
    # "rutube": RutubePolicyService,
    # "vk": VKPolicyService
}


def get_checker(platform: str) -> BasePolicyChecker:
    """
    Получить checker для заданной платформы
    
    Args:
        platform: имя платформы (youtube, rutube, vk)
    Returns:
        экземпляр BasePolicyChecker
    Raises:
        ValueError: если платформа не поддерживается
    """
    if platform not in CHECKERS:
        supported = ", ".join(CHECKERS.keys())
        raise ValueError(f"Платформа '{platform}' не поддерживается. Доступные: {supported}")
    
    return CHECKERS[platform]()


def get_supported_platforms() -> list:
    """Возвращает список поддерживаемых платформ"""
    return list(CHECKERS.keys())
