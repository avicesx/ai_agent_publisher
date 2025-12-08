import os
from pathlib import Path

# пути
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
UPLOAD_DIR = DATA_DIR / "uploads"
PROCESSED_DIR = DATA_DIR / "processed"

# создание директорий
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# URL микросервисов
SILENCE_CUTTER_URL = os.getenv("SILENCE_CUTTER_URL", "http://silence_cutter:8000")
TRANSCRIBER_URL = os.getenv("TRANSCRIBER_URL", "http://transcriber:8000")
CHECKING_TERMS_URL = os.getenv("CHECKING_TERMS_URL", "http://checking_terms:8000")
TEXT_GENERATOR_URL = os.getenv("TEXT_GENERATOR_URL", "http://text_generator:8000")
THUMBNAIL_GENERATOR_URL = os.getenv("THUMBNAIL_GENERATOR_URL", "http://thumbnail_generator:8000")

# таймауты
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "600.0"))

# логирование
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")