from pydantic import BaseModel


class VideoResponse(BaseModel):
    """
    Модель ответа с результатом обработки видео
    """
    output_path: str


class FileRequest(BaseModel):
    """
    Модель запроса с путем к локальному файлу
    """
    file_path: str