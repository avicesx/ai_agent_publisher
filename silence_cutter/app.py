import logging
from fastapi import FastAPI
from routes import video_router
import config
import uvicorn

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Silence_cutter",
    description="Сервис для удаления пауз из видео",
    version="2.0.0"
)

app.include_router(video_router, tags=["video"])

logger.info("Silence_cutter запущен")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "silence_cutter"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
