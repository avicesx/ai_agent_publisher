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
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        
        if not os.path.exists(output_path):
            raise Exception("Файл не был создан")
        
        video_title = info.get('title', 'Unknown') if info else 'Unknown'
        logger.info(f"Видео скачано: '{video_title}' -> {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"Ошибка скачивания видео: {e}")
        raise
