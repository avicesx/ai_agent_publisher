import os
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException
from models import FileRequest, TranscribeResponse
from services.audio_extractor import extract_audio
from services.transcriber import WhisperTranscriber
from config import Config

logger = logging.getLogger(__name__)

router = APIRouter()

transcriber = WhisperTranscriber(model_size=Config.MODEL_SIZE)


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_file(request: FileRequest):
    """
    Транскрибация видеофайла по локальному пути
    Args:
        request: Запрос с путем к файлу
    Returns:
        Текст транскрипции
    """
    logger.info(f"Получен запрос на транскрибацию файла {request.file_path}")
    input_path = Path(request.file_path)

    try:
        if not input_path.exists():
            logger.error(f"Файл не найден: {input_path}")
            raise HTTPException(status_code=404, detail=f"Файл не найден: {input_path}")

        logger.info(f"Извлечение аудио из {input_path}")
        wav_path = extract_audio(str(input_path))
        
        logger.info(f"Транскрибация файла {wav_path}")
        text = transcriber.transcribe(wav_path)
        logger.info("Транскрибация завершена")

        if os.path.exists(wav_path):
            os.remove(wav_path)

        return TranscribeResponse(text=text)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка транскрибации: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
