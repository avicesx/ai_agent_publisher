import os
import logging
from fastapi import APIRouter, HTTPException
from models.schemas import VideoResponse, FileRequest
from services.silence_remover import SilenceCutter
import config

logger = logging.getLogger(__name__)

router = APIRouter()

silence_cutter = SilenceCutter(workdir=config.WORKDIR)


@router.post("/process_file", response_model=VideoResponse)
async def process_file(request: FileRequest):
    """
    Обработка видеофайла по локальному пути
    Args:
        request: Запрос с путем к файлу
    Returns:
        Путь к обработанному видео
    """
    logger.info(f"Получен запрос process_file для {request.file_path}")
    
    try:

        if not os.path.exists(request.file_path):
            logger.error(f"Файл не найден: {request.file_path}")
            raise HTTPException(status_code=404, detail=f"Файл не найден: {request.file_path}")
        
        logger.info(f"Начало обработки файла: {request.file_path}")
        output_path = await silence_cutter.process(request.file_path)
        logger.info(f"Обработка завершена, результат: {output_path}")
        
        return VideoResponse(
            output_path=output_path
        )
    
    except Exception as e:
        logger.error(f"Ошибка при обработке файла: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))