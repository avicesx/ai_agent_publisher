import logging
from fastapi import FastAPI
from routes import transcribe_router
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Transcriber",
    description="Сервис для транскрибации видео",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

app.include_router(transcribe_router, tags=["transcribe"])

logger.info("Transcriber запущен")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "transcriber"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
