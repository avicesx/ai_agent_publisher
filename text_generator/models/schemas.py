from pydantic import BaseModel
from typing import List, Optional


class GenerateRequest(BaseModel):
    transcript: str
    post_format: str = "neutral"
    custom_prompt: Optional[str] = None
    platforms: List[str] = ["youtube", "telegram"]


class YouTubeContent(BaseModel):
    title: str
    description: str
    tags: List[str]


class TelegramContent(BaseModel):
    title: str
    post: str


class GenerateResponse(BaseModel):
    youtube: Optional[YouTubeContent] = None
    telegram: Optional[TelegramContent] = None
