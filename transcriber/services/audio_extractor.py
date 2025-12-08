import ffmpeg
import os
import uuid
import logging

logger = logging.getLogger(__name__)


def extract_audio(video_path: str) -> str:
    """
    Извлекает аудио из видео в .wav 16 kHz, сливая в моно
    """
    output_path = create_temp_filename(".wav")

    logger.info(f"Извлечение аудио из {video_path}")

    try:
        (
            ffmpeg
            .input(video_path)
            .output(output_path, format="wav", acodec="pcm_s16le", ac=1, ar="16000")
            .overwrite_output()
            .run(quiet=True)
        )
        logger.info(f"Аудио сохранено: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Ошибка извлечения аудио: {e}")
        raise


def create_temp_filename(extension=".wav", directory="temp"):
    """
    Создает уникальное имя файла во временной директории
    """
    os.makedirs(directory, exist_ok=True)
    unique_name = f"audio_{uuid.uuid4().hex}{extension}"
    return os.path.join(directory, unique_name)