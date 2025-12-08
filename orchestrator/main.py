from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Request
import shutil
import uuid
from pathlib import Path
from typing import Dict
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

jobs: Dict[str, Job] = {}


async def process_task_background(job_id: str, input_path: Path):
    """Фоновая задача для обработки"""
    job = jobs[job_id]
    jobs[job_id] = await process_pipeline(job, input_path)


@app.post("/jobs", response_model=Job)
async def create_job(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    Загрузить файл и запустить обработку в фоне
    Returns:
        Job с id и статусом
    """
    try:
        job_id = str(uuid.uuid4())
        input_filename = f"{job_id}_{file.filename}"
        input_path = config.UPLOAD_DIR / input_filename
        
        logger.info(f"Получен файл: {file.filename} -> {input_path}")
        
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        job = Job(
            id=job_id,
            status=JobStatus.PENDING,
            message="Файл загружен, поставлен в очередь"
        )
        jobs[job_id] = job
        
        background_tasks.add_task(process_task_background, job_id, input_path)
        
        logger.info(f"Задание {job_id} поставлено в очередь")
        return job

    except Exception as e:
        logger.error(f"Ошибка создания задания: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/jobs/{job_id}", response_model=Job)
async def get_job_status(job_id: str):
    """Получить статус задания"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    return jobs[job_id]


@app.post("/process", response_model=Job)
async def process_video(request: ProcessRequest):
    """
    Синхронная обработка видео
    
    Args:
        request: Путь к видео файлу и платформа
    Returns:
        Job с результатами обработки
    """
    job_id = str(uuid.uuid4())
    input_path = Path(request.video_path)
    
    job = Job(id=job_id, status=JobStatus.PENDING)
    jobs[job_id] = job
    
    jobs[job_id] = await process_pipeline(job, input_path, platform=request.platform)
    
    return jobs[job_id]


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "orchestrator"}


if __name__ == "__main__":
    logger.info("Запуск Orchestrator...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
