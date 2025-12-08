from pydantic import BaseModel
from typing import List


class GenerateRequest(BaseModel):
    transcript: str
    post_format: str = "neutral"


class YouTubeContent(BaseModel):
    title: str
    description: str
    tags: List[str]


class TelegramContent(BaseModel):
    title: str
    post: str


class GenerateResponse(BaseModel):
    youtube: YouTubeContent
    telegram: TelegramContent
