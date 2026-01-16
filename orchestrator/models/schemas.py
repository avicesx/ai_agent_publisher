from pydantic import BaseModel
from typing import Optional
from enum import Enum


class JobStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Job(BaseModel):
    id: str
    status: JobStatus
    video_path: Optional[str] = None
    text: Optional[str] = None
    transcript_check: Optional[dict] = None  # проверка транскрипта
    generated_content: Optional[dict] = None  # ютуб + тг + проверки
    message: Optional[str] = None


class ProcessRequest(BaseModel):
    video_path: str
    platforms: list[str] = ["youtube", "telegram"]
    post_format: str = "neutral"
    custom_prompt: Optional[str] = None
    pipeline_actions: list[str] = []