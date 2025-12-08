import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException

from models import CheckRequest, CheckResponse
from services import get_checker, get_supported_platforms

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/check_policy", response_model=CheckResponse)
async def check_policy(request: CheckRequest):
    """
    Проверка контента на соответствие политике платформы
    
    Args:
        request: text (прямой текст) или file_path (путь к файлу)
    Returns:
        Результат проверки: verdict, confidence, details
    """
    logger.info(f"Получен запрос на проверку для платформы: {request.platform}")
    
    try:
        if request.text:
            text = request.text
        elif request.file_path:
            file_path = Path(request.file_path)
            if not file_path.exists():
                raise HTTPException(status_code=404, detail=f"Файл не найден: {request.file_path}")
            
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
            logger.info(f"Прочитан файл: {request.file_path}")
        else:
            raise HTTPException(status_code=400, detail="Необходимо указать text или file_path")
        
        checker = get_checker(request.platform)
        
        result = checker.check(text)
        logger.info(f"Проверка завершена: {result['verdict']} (уверенность: {result['confidence']:.2f})")
        
        return CheckResponse(
            platform=request.platform,
            verdict=result["verdict"],
            confidence=result["confidence"],
            details=result["details"]
        )
        
    except ValueError as e:
        logger.error(f"Неподдерживаемая платформа: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Ошибка при проверке контента: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/platforms")
async def get_platforms():
    """Возвращает список поддерживаемых платформ"""
    return {"platforms": get_supported_platforms()}
