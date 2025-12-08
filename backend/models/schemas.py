from pydantic import BaseModel, Field
from typing import Optional


class ProcessingResult(BaseModel):
    """
    Результат обработки от orchestrator
    Маппинг полей Job -> ProcessingResult:
      id -> job_id
      video_path -> processed_video_path  
      text -> transcription
      generated_content -> (содержит policy_check внутри)
    """
    job_id: str = Field(alias="id")
    status: str  # "COMPLETED", "FAILED", "PROCESSING", "PENDING"
    processed_video_path: Optional[str] = Field(None, alias="video_path")
    transcription: Optional[str] = Field(None, alias="text")
    generated_content: Optional[dict] = None  # сгенерированное в text_generator
    transcript_check: Optional[dict] = None  # проверка на пользовательское соглашение
    message: Optional[str] = None  # сообщение о статусе
    error: Optional[str] = None
    
    class Config:
        populate_by_name = True
