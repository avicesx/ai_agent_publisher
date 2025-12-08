import os
from pathlib import Path

# пути
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
OUTPUT_DIR = DATA_DIR / "thumbnails"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# параметры генерации
N_THUMBNAILS = int(os.getenv("N_THUMBNAILS", "3"))
FRAME_STEP_SCENE = int(os.getenv("FRAME_STEP_SCENE", "10"))
FRAME_STEP_SAMPLE = int(os.getenv("FRAME_STEP_SAMPLE", "5"))
SCENE_HIST_THRESH = float(os.getenv("SCENE_HIST_THRESH", "0.45"))
PER_SCENE_MAX = int(os.getenv("PER_SCENE_MAX", "3"))

# логи
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
