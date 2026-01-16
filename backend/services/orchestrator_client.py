import httpx
import logging
import config
from models import ProcessingResult

logger = logging.getLogger(__name__)


class OrchestratorClient:
    """
    HTTP клиент для взаимодействия с Orchestrator
    """
    
    def __init__(self):
        self.base_url = config.ORCHESTRATOR_URL
        self.timeout = config.HTTP_TIMEOUT
    
    async def process_video(self, video_path: str, platforms: list[str] = None, post_format: str = "neutral", custom_prompt: str = None, pipeline_actions: list[str] = None) -> ProcessingResult:
        """
        Отправить видео на обработку в оркестратор
        Args:
            video_path: Путь к видео файлу в shared volume
            platforms: Список платформ ["youtube", "telegram"]
            post_format: Формат поста
            custom_prompt: Кастомный промт
            pipeline_actions: Список действий
        Returns:
            ProcessingResult с результатами обработки
        """
        logger.info(f"Отправка видео на обработку: {video_path}, platforms={platforms}, pipeline_actions={pipeline_actions}")
        
        payload = {
            "video_path": video_path,
            "post_format": post_format,
            "pipeline_actions": pipeline_actions or []
        }
        if platforms:
            payload["platforms"] = platforms
        if custom_prompt:
            payload["custom_prompt"] = custom_prompt
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/process",
                    json=payload
                )
                response.raise_for_status()
                
                result = response.json()
                logger.info(f"Обработка завершена: {result.get('status')}")
                
                return ProcessingResult(**result)
                
        except httpx.HTTPError as e:
            logger.error(f"Ошибка HTTP при обращении к orchestrator: {e}")
            return ProcessingResult(
                job_id="error",
                status="failed",
                error=str(e)
            )
        except Exception as e:
            logger.error(f"Неожиданная ошибка при обработке: {e}")
            return ProcessingResult(
                job_id="error",
                status="failed",
                error=str(e)
            )
    
