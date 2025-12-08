import subprocess
import uuid
from pathlib import Path
from typing import List, Tuple
import logging
import config

logger = logging.getLogger(__name__)


def extract_audio(video_path: str) -> str:
    """
    Извлекает аудио из видео файла
    
    Args:
        video_path: Путь к видео файлу
    Returns:
        Путь к извлеченному аудио файлу (.wav)
    """
    audio_path = video_path + ".wav"
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-ac", str(config.AUDIO_CHANNELS), 
        "-ar", str(config.AUDIO_RATE),
        audio_path
    ]
    
    logger.info(f"Извлечение аудио: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except subprocess.CalledProcessError as e:
        logger.error("FFmpeg не смог извлечь аудио")
        raise RuntimeError(f"FFmpeg не смог извлечь аудио: {e}")
    
    if not Path(audio_path).exists():
        raise FileNotFoundError(f"FFmpeg завершился, но аудио файл не найден: {audio_path}")
    
    logger.info(f"Аудио успешно извлечено: {audio_path}")
    return audio_path


def cut_video_segments(input_video: str, segments: List[Tuple[float, float]], workdir: str) -> List[str]:
    """
    Нарезает видео на сегменты согласно временным меткам
    
    Args:
        input_video: Путь к входному видео
        segments: Список кортежей (start, end) в секундах
        workdir: Рабочая директория для временных файлов
    Returns:
        Список путей к нарезанным файлам
    """
    input_video = Path(input_video).resolve().as_posix()
    chunk_files = []
    
    logger.info(f"Нарезка видео на {len(segments)} сегментов")
    
    for i, (start, end) in enumerate(segments):
        duration = end - start
        out_file = Path(workdir, f"chunk_{i}.mp4").resolve().as_posix()
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", input_video,
            "-t", str(duration),
            "-c:v", config.FFMPEG_VIDEO_CODEC,
            "-preset", config.FFMPEG_PRESET,
            "-c:a", config.FFMPEG_AUDIO_CODEC,
            out_file
        ]
        
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        chunk_files.append(out_file)
    
    logger.info(f"Создано {len(chunk_files)} сегментов")
    return chunk_files


def concat_videos(chunk_files: List[str], workdir: str) -> str:
    """
    Склеивает несколько видео файлов в один
    
    Args:
        chunk_files: Список путей к видео файлам для склейки
        workdir: Рабочая директория
    Returns:
        Путь к финальному склеенному видео
    """
    output_final = Path(workdir, f"output_{uuid.uuid4()}.mp4").resolve().as_posix()
    temp_list = Path(workdir, f"{uuid.uuid4()}.txt").resolve().as_posix()
    
    with open(temp_list, "w", encoding="utf-8") as f:
        for fp in chunk_files:
            f.write(f"file '{fp}'\n")
    
    logger.info(f"Склейка {len(chunk_files)} файлов")
    
    cmd_concat = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", temp_list,
        "-c:v", config.FFMPEG_VIDEO_CODEC,
        "-preset", config.FFMPEG_PRESET,
        "-c:a", config.FFMPEG_AUDIO_CODEC,
        output_final
    ]
    
    subprocess.run(cmd_concat, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info(f"Видео успешно склеено: {output_final}")
    
    return output_final
