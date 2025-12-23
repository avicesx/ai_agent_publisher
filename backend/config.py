import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in environment variables. Please set it in .env file")

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8000")

TELEGRAM_API_URL = os.getenv("TELEGRAM_API_URL", None)
TELEGRAM_API_FILES_DIR = "/var/lib/telegram-bot-api"

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/data/uploads")
WORKDIR = os.getenv("WORKDIR", "/data/workdir")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/data/outputs")

for directory in [UPLOAD_DIR, WORKDIR, OUTPUT_DIR]:
    os.makedirs(directory, exist_ok=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "300.0"))
