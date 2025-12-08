from fastapi import FastAPI, HTTPException
import logging
import uuid
import uvicorn
import config
from models import GenerateThumbnailsRequest, GenerateThumbnailsResponse, ThumbnailInfo
from services import run_agent

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("thumbnail_generator")

app = FastAPI(
    title="Thumbnail Generator",
    description="Генерация обложек для видео",
    version="1.0.0"
)


@app.post("/generate_thumbnails", response_model=GenerateThumbnailsResponse)
async def generate_thumbnails(request: GenerateThumbnailsRequest):
    """
    Генерация обложек для видео
    
    Args:
        request: Путь к видео и количество обложек
    Returns:
        Список сгенерированных обложек с метаданными
    """
    try:
        logger.info(f"Генерация {request.n_thumbnails} обложек для {request.video_path}")
        
        job_id = str(uuid.uuid4())
        out_dir = config.OUTPUT_DIR / job_id
        
        saved_data = run_agent(
            request.video_path,
            out_dir=str(out_dir),
            n_thumbs=request.n_thumbnails,
            frame_step_scene=config.FRAME_STEP_SCENE,
            frame_step_sample=config.FRAME_STEP_SAMPLE,
            scene_hist_thresh=config.SCENE_HIST_THRESH,
            per_scene_max=config.PER_SCENE_MAX
        )
        
        thumbnails = [
            ThumbnailInfo(**item) for item in saved_data
        ]
        
        logger.info(f"Успешно сгенерировано {len(thumbnails)} обложек")
        return GenerateThumbnailsResponse(thumbnails=thumbnails)
    
    except Exception as e:
        logger.error(f"Ошибка генерации обложек: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "thumbnail_generator"}


if __name__ == "__main__":
    logger.info("Запуск Thumbnail Generator...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
