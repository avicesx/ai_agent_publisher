from pydantic import BaseModel
from typing import Literal, Optional


class CheckRequest(BaseModel):
    """
    Запрос на проверку контента
    """
    text: Optional[str] = None
    file_path: Optional[str] = None
    platform: Literal["youtube", "rutube", "vk"] = "youtube"


class CheckResponse(BaseModel):
    """
    Результат проверки контента
    """
    platform: str
    verdict: str  # ALLOW или BLOCK
    confidence: float
    details: dict
