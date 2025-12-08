import httpx
import logging
from pathlib import Path
import config
from models import Job, JobStatus

logger = logging.getLogger(__name__)


async def process_pipeline(job: Job, input_path: Path, platform: str = "youtube") -> Job:
    """
    Полный пайплайн обработки видео
    
    Args:
        job: Объект задачи
        input_path: Путь к входному видео
    Returns:
        Обновленный объект Job с результатами
    """
    logger.info(f"Запрос {job.id}: запуск пайплайна для {input_path}")
    
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
            logger.info(f"Запрос {job.id}: Проверка транскрипта...")
            job.message = "Проверка транскрипта..."
            
            try:
                transcript_check_response = await client.post(
                    f"{config.CHECKING_TERMS_URL}/check_policy",
                    json={
                        "file_path": str(transcription_file),
                        "platform": platform
                    }
                )
                transcript_check_response.raise_for_status()
            except httpx.RequestError as e:
                raise Exception(f"Сервис Checking Terms недоступен: {e}")
            
            transcript_check = transcript_check_response.json()
            job.transcript_check = transcript_check
            logger.info(f"Запрос {job.id}: Проверка транскрипта: {transcript_check['verdict']}")
            
            if transcript_check.get("verdict") == "rejected":
                job.status = JobStatus.FAILED
                job.message = "Транскрипт не прошёл проверку политики"
                logger.warning(f"Запрос {job.id}: Транскрипт отклонён")
                return job
            
            # Text Generator
            logger.info(f"Запрос {job.id}: Вызов Text Generator...")
            job.message = "Генерация контента..."
            
            try:
                text_gen_response = await client.post(
                    f"{config.TEXT_GENERATOR_URL}/generate",
                    json={
                        "transcript": transcription_text,
                        "post_format": "neutral"  # пока что поставила дефолтное значение
                    }
                )
                text_gen_response.raise_for_status()
            except httpx.RequestError as e:
                raise Exception(f"Сервис Text Generator недоступен: {e}")
            
            generated = text_gen_response.json()
            logger.info(f"Запрос {job.id}: Text Generator завершен")
            
            # Checking Terms (ютуб)
            logger.info(f"Запрос {job.id}: Проверка YouTube контента...")
            job.message = "Проверка YouTube контента..."
            
            youtube_text = f"{generated['youtube']['title']}\n{generated['youtube']['description']}\n{' '.join(generated['youtube']['tags'])}"
            
            try:
                youtube_check_response = await client.post(
                    f"{config.CHECKING_TERMS_URL}/check_policy",
                    json={
                        "text": youtube_text,
                        "platform": "youtube"
                    }
                )
                youtube_check_response.raise_for_status()
            except httpx.RequestError as e:
                raise Exception(f"Сервис Checking Terms недоступен (YouTube check): {e}")
            
            youtube_check = youtube_check_response.json()
            logger.info(f"Запрос {job.id}: YouTube проверка: {youtube_check['verdict']}")
            
            # # Checking Terms (Telegram)
            # logger.info(f"Запрос {job.id}: Проверка Telegram контента...")
            # job.message = "Проверка Telegram контента..."
            
            # telegram_text = f"{generated['telegram']['title']}\n{generated['telegram']['post']}"
            
            # try:
            #     telegram_check_response = await client.post(
            #         f"{config.CHECKING_TERMS_URL}/check_policy",
            #         json={
            #             "text": telegram_text,
            #             "platform": "youtube"  # пока поставила правила ютуба
            #         }
            #     )
            #     telegram_check_response.raise_for_status()
            # except httpx.RequestError as e:
            #     raise Exception(f"Сервис Checking Terms недоступен (Telegram check): {e}")
            
            # telegram_check = telegram_check_response.json()
            # logger.info(f"Задание {job.id}: Telegram проверка: {telegram_check['verdict']}")
            
            # Thumbnail Generator
            logger.info(f"Задание {job.id}: Генерация обложек...")
            job.message = "Генерация обложек..."
            
            try:
                thumbnail_response = await client.post(
                    f"{config.THUMBNAIL_GENERATOR_URL}/generate_thumbnails",
                    json={
                        "video_path": processed_video_path,
                        "n_thumbnails": 3
                    }
                )
                thumbnail_response.raise_for_status()
            except httpx.RequestError as e:
                raise Exception(f"Сервис Thumbnail Generator недоступен: {e}")
            
            thumbnails_data = thumbnail_response.json()["thumbnails"]
            logger.info(f"Запрос {job.id}: Сгенерировано {len(thumbnails_data)} обложек")
            
            job.video_path = processed_video_path
            job.text = transcription_text
            job.generated_content = {
                "youtube": {
                    "content": generated["youtube"],
                    "policy_check": youtube_check,
                    "thumbnails": thumbnails_data
                },
                # "telegram": {
                #     "content": generated["telegram"],
                #     "policy_check": telegram_check,
                #     "thumbnails": thumbnails_data
                # }
            }
            job.status = JobStatus.COMPLETED
            job.message = "Пайплайн успешно завершен"
            logger.info(f"Запрос {job.id}: Пайплайн завершен успешно")
            
            return job

    except Exception as e:
        logger.error(f"Запрос {job.id}: Ошибка в пайплайне: {e}", exc_info=True)
        job.status = JobStatus.FAILED
        job.message = str(e)
        return job

