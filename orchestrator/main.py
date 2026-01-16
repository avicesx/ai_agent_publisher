from fastapi import FastAPI, Request
from pathlib import Path
import uuid
import logging
import uvicorn
import config
from models import Job, JobStatus, ProcessRequest
from services import process_pipeline

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("orchestrator")

app = FastAPI(
    title="Orchestrator",
    description="Координатор обработки видео",
    version="1.0.0",
    root_path="/pipeline"
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Входящий запрос: {request.method} {request.url.path}")
    response = await call_next(request)
    logger.info(f"Статус ответа: {response.status_code}")
    return response


@app.post("/process", response_model=Job)
async def process_video(request: ProcessRequest):
    """
    Синхронная обработка видео
    """
    job_id = str(uuid.uuid4())
    input_path = Path(request.video_path)
    
    job = Job(id=job_id, status=JobStatus.PENDING)
    
    job = await process_pipeline(
        job, 
        input_path, 
        platforms=request.platforms, 
        post_format=request.post_format, 
        custom_prompt=request.custom_prompt,
        pipeline_actions=request.pipeline_actions
    )
    return job
    

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "orchestrator"}


if __name__ == "__main__":
    logger.info("Запуск Orchestrator...")
    uvicorn.run(app, host="0.0.0.0", port=8000)