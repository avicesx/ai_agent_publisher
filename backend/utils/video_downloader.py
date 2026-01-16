import os
import uuid
import logging
from yt_dlp import YoutubeDL
import config

logger = logging.getLogger(__name__)


async def download_video(url: str) -> str:
    """
    Скачать видео по URL и сохранить в UPLOAD_DIR
    Args:
        url: URL видео
    Returns:
        Путь к скачанному файлу
    """
    video_id = str(uuid.uuid4())
    output_filename = f"video_{video_id}.mp4"
    output_path = os.path.join(config.UPLOAD_DIR, output_filename)
    
    logger.info(f"Скачивание видео из {url}")
    
    ydl_opts = {
        'outtmpl': output_path,
        'format': 'best[ext=mp4][height<=1080]/best[height<=1080]/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'retries': 3,
        'fragment_retries': 3,
        'file_access_retries': 3,
        'ignoreerrors': False,
        'extract_flat': False,
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise Exception("Файл не был создан или пуст")
        
        video_title = info.get('title', 'Unknown') if info else 'Unknown'
        logger.info(f"Видео скачано: '{video_title}' -> {output_path}")
        return output_path
        
    except Exception as e:
        error_msg = str(e)
        if "empty" in error_msg.lower():
            logger.error(f"Ошибка скачивания видео: файл пуст")
            raise Exception("Не удалось скачать видео: файл оказался пустым. Попробуйте другой URL или загрузите видео файлом.")
        else:
        logger.error(f"Ошибка скачивания видео: {e}")
            raise Exception(f"Ошибка скачивания видео: {error_msg}")
