import logging
from fastapi import FastAPI
from routes import policy_router
import uvicorn
import config

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Content Policy Checker",
    description="Сервис для проверки контента на соответствие политикам платформ (YouTube, Rutube, VK)",
    version="1.0.0"
)

app.include_router(policy_router, tags=["policy"])

logger.info("Content Policy Checker запущен")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "checking_terms"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
