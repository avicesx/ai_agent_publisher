import os
from pathlib import Path

# директории
WORKDIR = os.getenv("WORKDIR", "/data/workdir")
Path(WORKDIR).mkdir(parents=True, exist_ok=True)

# параметры обнаружения тишины
SILENCE_THRESHOLD = int(os.getenv("SILENCE_THRESHOLD", "-45")) # дБ
MIN_SILENCE_LENGTH = int(os.getenv("MIN_SILENCE_LENGTH", "700")) # мс

# паддинги для плавного звучания
START_PADDING = 300 # мс - смягчить начало
END_PADDING = 300 # мс - чтобы фраза не обрывалась

# FFmpeg настройки
FFMPEG_AUDIO_CODEC = "aac"
FFMPEG_VIDEO_CODEC = "libx264"
FFMPEG_PRESET = "ultrafast"
AUDIO_CHANNELS = 1
AUDIO_RATE = 16000

# таймауты
DOWNLOAD_TIMEOUT = 600 # секунд для скачивания видео

# логирование
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
