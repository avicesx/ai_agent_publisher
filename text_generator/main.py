from fastapi import FastAPI, HTTPException
import logging
import uvicorn
import config
from models import GenerateRequest, GenerateResponse, YouTubeContent, TelegramContent
from services import (
    load_llm,
    bulk_generate_content
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
    logger.info("Text Generator готов к работе")


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
        logger.info(f"Генерация контента, формат: {request.post_format}, платформы: {request.platforms}")
        
        generated_data = bulk_generate_content(
            request.transcript, 
            request.platforms, 
            request.post_format, 
            request.custom_prompt
        )
        
        youtube = None
        telegram = None

        if "youtube" in request.platforms and generated_data.get("youtube"):
            yt = generated_data["youtube"]
            youtube = YouTubeContent(
                title=yt.get("title", ""),
                description=yt.get("description", ""),
                tags=yt.get("tags", [])
            )
        
        if "telegram" in request.platforms and generated_data.get("telegram"):
            tg = generated_data["telegram"]
            telegram = TelegramContent(
                title=tg.get("title", ""),
                post=tg.get("post", "")
            )
        
        if youtube or telegram:
        logger.info("Контент успешно сгенерирован")
        else:
            logger.warning("Контент не был сгенерирован для выбранных платформ")
        
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