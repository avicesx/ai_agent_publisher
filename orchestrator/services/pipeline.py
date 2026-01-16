import httpx
import logging
from pathlib import Path
import config
from models import Job, JobStatus

logger = logging.getLogger(__name__)

SUPPORTED_POLICY_PLATFORMS = {"youtube", "vk", "rutube"}


def _normalize_policy_platform(platform: str) -> str:
    """
    Приводит платформу к поддерживаемой checking_terms.
    Если платформа не поддерживается (например, telegram),
    используем youtube как дефолтную политику.
    """
    if platform in SUPPORTED_POLICY_PLATFORMS:
        return platform
    return "youtube"


async def process_pipeline(job: Job, input_path: Path, platforms: list[str] = ["youtube", "telegram"], post_format: str = "neutral", custom_prompt: str = None, pipeline_actions: list[str] = None) -> Job:
    """
    Полный пайплайн обработки видео с поддержкой выборочного выполнения шагов
    """
    logger.info(f"Запрос {job.id}: запуск пайплайна для {input_path}, платформы: {platforms}, действия: {pipeline_actions}")
    
    if not pipeline_actions:
        pipeline_actions = ["cut_silence", "transcribe", "check_policy", "generate_content", "generate_thumbnails"]

    try:
        job.status = JobStatus.PROCESSING
        job.message = "Начало обработки..."

        async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as client:
            processed_video_path = str(input_path)
            
            # 1. Silence Cutter
            if "cut_silence" in pipeline_actions:
                job.message = "Удаление пауз..."
                try:
                    silence_response = await client.post(
                        f"{config.SILENCE_CUTTER_URL}/process_file",
                        json={"file_path": str(input_path)}
                    )
                    silence_response.raise_for_status()
                    processed_video_path = silence_response.json()["output_path"]
                except Exception as e:
                    logger.error(f"Silence Cutter: ошибка {e}")
            
            # 2. Transcriber
            transcription_text = ""
            if any(a in pipeline_actions for a in ["transcribe", "generate_content", "publish"]):
                logger.info(f"Запрос {job.id}: вызов Transcriber (нужен для: {[a for a in ['transcribe', 'generate_content', 'publish'] if a in pipeline_actions]})")
                job.message = "Транскрибация..."
                try:
                    transcriber_response = await client.post(
                        f"{config.TRANSCRIBER_URL}/transcribe",
                        json={"file_path": processed_video_path}
                    )
                    transcriber_response.raise_for_status()
                    transcription_text = transcriber_response.json()["text"]
                    logger.info(f"Запрос {job.id}: Транскрибация получена, длина: {len(transcription_text)}")
                except Exception as e:
                    logger.error(f"Транскрибер: ошибка {e}")
                    transcription_text = "Ошибка транскрибации"
            
            # 3. Checking terms
            if "check_policy" in pipeline_actions and transcription_text:
                # выбираем первую поддерживаемую платформу для политики
                base_platform = None
                for p in platforms or []:
                    if p in SUPPORTED_POLICY_PLATFORMS:
                        base_platform = p
                        break
                check_platform = _normalize_policy_platform(base_platform or "youtube")
                logger.info(f"Запрос {job.id}: Проверка транскрипта...")
                job.message = "Проверка политики..."
                
                tmp_file = config.PROCESSED_DIR / f"{job.id}_transcript.txt"
                with open(tmp_file, "w", encoding="utf-8") as f:
                    f.write(transcription_text)

                try:
                    transcript_check_response = await client.post(
                        f"{config.CHECKING_TERMS_URL}/check_policy",
                        json={"file_path": str(tmp_file), "platform": check_platform}
                    )
                    job.transcript_check = transcript_check_response.json()
                except Exception as e:
                    logger.error(f"Проверка политики: ошибка {e}")

            # 4. Text generator
            generated = {}
            if any(a in pipeline_actions for a in ["generate_content", "publish"]) and transcription_text:
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
                    generated = text_gen_response.json()
                    logger.info(f"Запрос {job.id}: Text Generator вернул ключи: {list(generated.keys())}")
                except Exception as e:
                    logger.error(f"Text Generator: ошибка {e}")

            job.generated_content = {}
            
            # 5. Platform specific, Thumbnails
            for platform in platforms:
                platform_data = {}
                
                if any(a in pipeline_actions for a in ["generate_content", "publish"]) and platform in generated and generated[platform] is not None:
                    platform_data["content"] = generated[platform]
                    
                    if "check_policy" in pipeline_actions:
                        platform_content = generated[platform]
                        if isinstance(platform_content, dict):
                            text_to_check = f"{platform_content.get('title', '')} {platform_content.get('description', '')}"
                        try:
                                policy_platform = _normalize_policy_platform(platform)
                            check_res = await client.post(
                                f"{config.CHECKING_TERMS_URL}/check_policy",
                                    json={"text": text_to_check, "platform": policy_platform}
                            )
                            platform_data["policy_check"] = check_res.json()
                        except Exception as e:
                            logger.debug(f"Проверка политики пропущена для {platform}: {e}")

                if platform == "youtube" and "generate_thumbnails" in pipeline_actions:
                    logger.info(f"Задание {job.id}: Генерация обложек...")
                    try:
                        thumb_res = await client.post(
                            f"{config.THUMBNAIL_GENERATOR_URL}/generate_thumbnails",
                            json={"video_path": processed_video_path, "n_thumbnails": 3}
                        )
                        platform_data["thumbnails"] = thumb_res.json()["thumbnails"]
                    except Exception as e:
                        logger.debug(f"Генерация обложек пропущена: {e}")
                
                if platform_data:
                    job.generated_content[platform] = platform_data

            job.video_path = processed_video_path
            job.text = transcription_text if "transcribe" in pipeline_actions else None
            job.status = JobStatus.COMPLETED
            job.message = "Обработка завершена успешно"
            return job

    except Exception as e:
        logger.error(f"Запрос {job.id}: Ошибка в пайплайне: {e}", exc_info=True)
        job.status = JobStatus.FAILED
        job.message = str(e)
        return job

