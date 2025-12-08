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
        self.timeout = 300.0
    
    async def process_video(self, video_path: str) -> ProcessingResult:
        """
        Отправить видео на обработку в оркестратор
        Args:
            video_path: Путь к видео файлу в shared volume
        Returns:
            ProcessingResult с результатами обработки
        """
        logger.info(f"Отправка видео на обработку: {video_path}")
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/process",
                    json={"video_path": video_path}
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
    
    async def get_status(self, job_id: str) -> ProcessingResult:
        """
        Проверить статус обработки
        
        не используется, может пригодиться для отладки

        Args:
            job_id: ID задачи
        Returns:
            ProcessingResult с текущим статусом
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/status/{job_id}"
                )
                response.raise_for_status()
                return ProcessingResult(**response.json())
                
        except Exception as e:
            logger.error(f"Ошибка получения статуса: {e}")
            return ProcessingResult(
                job_id=job_id,
                status="failed",
                error=str(e)
            )
