from fastapi import FastAPI, HTTPException
import logging
import uvicorn
import config
from models import GenerateRequest, GenerateResponse, YouTubeContent, TelegramContent
from services import (
    load_llm,
    generate_youtube_title,
    generate_youtube_description,
    generate_tags,
    generate_telegram_title,
    generate_telegram_post
)

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("text_generator")

app = FastAPI(
    title="Text Generator",
    description="Генерация контента для YouTube и Telegram",
    version="1.0.0"
)


@app.on_event("startup")
async def startup_event():
    """Загрузка LLM при старте сервиса"""
    logger.info("Запуск Text Generator...")
    load_llm()
    logger.info("Сервис готов к работе")


@app.post("/generate", response_model=GenerateResponse)
async def generate_content(request: GenerateRequest):
    """
    Генерация контента для YouTube и Telegram
    
    Args:
        request: Транскрипт и формат поста
    Returns:
        Сгенерированный контент для обеих платформ
    """
    try:
        logger.info(f"Генерация контента, формат: {request.post_format}")
        
        # генерация YouTube контента
        youtube = YouTubeContent(
            title=generate_youtube_title(request.transcript),
            description=generate_youtube_description(request.transcript),
            tags=generate_tags(request.transcript)
        )
        
        # генерация Telegram контента
        telegram = TelegramContent(
            title=generate_telegram_title(request.transcript),
            post=generate_telegram_post(request.transcript, request.post_format)
        )
        
        logger.info("Контент успешно сгенерирован")
        return GenerateResponse(youtube=youtube, telegram=telegram)
        
    except Exception as e:
        logger.error(f"Ошибка генерации: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "text_generator"}


if __name__ == "__main__":
    logger.info("Запуск Text Generator...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
