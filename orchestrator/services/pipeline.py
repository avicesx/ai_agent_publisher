import httpx
import logging
from pathlib import Path
import config
from models import Job, JobStatus

logger = logging.getLogger(__name__)


async def process_pipeline(job: Job, input_path: Path, platforms: list[str] = ["youtube", "telegram"], post_format: str = "neutral", custom_prompt: str = None) -> Job:
    """
    Полный пайплайн обработки видео
    
    Args:
        job: Объект задачи
        input_path: Путь к входному видео
        platforms: Список платформ для генерации
        post_format: Формат поста
        custom_prompt: Пользовательский промт
    Returns:
        Обновленный объект Job с результатами
    """
    logger.info(f"Запрос {job.id}: запуск пайплайна для {input_path}, платформы: {platforms}")
    
    try:
        job.status = JobStatus.PROCESSING
        job.message = "Начало обработки..."

        async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as client:
            # Silence Cutter
            logger.info(f"Запрос {job.id}: вызов Silence Cutter...")
            job.message = "Удаление пауз..."
            
            try:
                silence_response = await client.post(
                    f"{config.SILENCE_CUTTER_URL}/process_file",
                    json={"file_path": str(input_path)}
                )
                silence_response.raise_for_status()
            except httpx.RequestError as e:
                raise Exception(f"Сервис Silence_cutter недоступен: {e}")
            
            processed_video_path = silence_response.json()["output_path"]
            logger.info(f"Запрос {job.id}: Silence Cutter завершен: {processed_video_path}")
            
            # Transcriber
            logger.info(f"Запрос {job.id}: вызов Transcriber...")
            job.message = "Транскрибация..."
            
            try:
                transcriber_response = await client.post(
                    f"{config.TRANSCRIBER_URL}/transcribe",
                    json={"file_path": processed_video_path}
                )
                transcriber_response.raise_for_status()
            except httpx.RequestError as e:
                raise Exception(f"Сервис Transcriber недоступен: {e}")
            
            transcription_text = transcriber_response.json()["text"]
            logger.info(f"Запрос {job.id}: Transcriber завершен")
            
            transcription_file = config.PROCESSED_DIR / f"{job.id}_transcription.txt"
            with open(transcription_file, "w", encoding="utf-8") as f:
                f.write(transcription_text)
            
            # Checking Terms (транскрипт)
            check_platform = platforms[0] if platforms else "youtube"
            
            logger.info(f"Запрос {job.id}: Проверка транскрипта (для {check_platform})...")
            job.message = "Проверка транскрипта..."
            
            try:
                transcript_check_response = await client.post(
                    f"{config.CHECKING_TERMS_URL}/check_policy",
                    json={
                        "file_path": str(transcription_file),
                        "platform": check_platform
                    }
                )
                transcript_check_response.raise_for_status()
            except httpx.RequestError as e:
                raise Exception(f"Сервис Checking Terms недоступен: {e}")
            
            transcript_check = transcript_check_response.json()
            job.transcript_check = transcript_check
            logger.info(f"Запрос {job.id}: Проверка транскрипта: {transcript_check['verdict']}")
            
            if transcript_check.get("verdict") == "rejected":
                logger.warning(f"Запрос {job.id}: Транскрипт не соответствует политике")
            
            # Text Generator
            logger.info(f"Запрос {job.id}: Вызов Text Generator...")
            job.message = "Генерация контента..."
            
            try:
                text_gen_response = await client.post(
                    f"{config.TEXT_GENERATOR_URL}/generate",
                    json={
                        "transcript": transcription_text,
                        "post_format": post_format,
                        "custom_prompt": custom_prompt,
                        "platforms": platforms
                    }
                )
                text_gen_response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(f"Ошибка HTTP Status Text Generator: {e.response.text}")
                raise
            except httpx.RequestError as e:
                raise Exception(f"Сервис Text Generator недоступен: {e}")
            
            generated = text_gen_response.json()
            logger.info(f"Запрос {job.id}: Text Generator завершен")
            
            job.generated_content = {}
            
            # YouTube Flow
            if "youtube" in platforms and generated.get("youtube"):
                logger.info(f"Запрос {job.id}: Проверка YouTube контента...")
                job.message = "Проверка YouTube контента..."
                
                youtube_content = generated["youtube"]
                youtube_text = f"{youtube_content['title']}\n{youtube_content['description']}\n{' '.join(youtube_content['tags'])}"
                
                try:
                    youtube_check_response = await client.post(
                        f"{config.CHECKING_TERMS_URL}/check_policy",
                        json={
                            "text": youtube_text,
                            "platform": "youtube"
                        }
                    )
                    youtube_check_response.raise_for_status()
                    youtube_check = youtube_check_response.json()
                except Exception as e:
                    logger.error(f"Ошибка проверки YouTube: {e}")
                    youtube_check = {"verdict": "error", "reason": str(e)}

                # Thumbnail Generator
                logger.info(f"Задание {job.id}: Генерация обложек...")
                job.message = "Генерация обложек..."
                
                thumbnails_data = []
                try:
                    thumbnail_response = await client.post(
                        f"{config.THUMBNAIL_GENERATOR_URL}/generate_thumbnails",
                        json={
                            "video_path": processed_video_path,
                            "n_thumbnails": 3
                        }
                    )
                    thumbnail_response.raise_for_status()
                    thumbnails_data = thumbnail_response.json()["thumbnails"]
                except Exception as e:
                    logger.error(f"Ошибка генерации обложек: {e}")

                job.generated_content["youtube"] = {
                    "content": youtube_content,
                    "policy_check": youtube_check,
                    "thumbnails": thumbnails_data
                }

            # Telegram Flow
            if "telegram" in platforms and generated.get("telegram"):
                logger.info(f"Запрос {job.id}: Обработка Telegram контента...")
                job.generated_content["telegram"] = {
                    "content": generated["telegram"]
                }
            
            job.video_path = processed_video_path
            job.text = transcription_text
            job.status = JobStatus.COMPLETED
            job.message = "Пайплайн успешно завершен"
            logger.info(f"Запрос {job.id}: Пайплайн завершен успешно")
            
            return job

    except Exception as e:
        logger.error(f"Запрос {job.id}: Ошибка в пайплайне: {e}", exc_info=True)
        job.status = JobStatus.FAILED
        job.message = str(e)
        return job

