from pydantic import BaseModel


class FileRequest(BaseModel):
    """
    Модель запроса с путем к локальному файлу
    """
    file_path: str


class TranscribeResponse(BaseModel):
    """
    Модель ответа с результатом транскрибации
    """
    text: str