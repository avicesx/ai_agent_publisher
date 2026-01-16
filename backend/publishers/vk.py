import logging
import aiohttp
import aiofiles
import os

logger = logging.getLogger(__name__)

async def publish_to_vk_draft(
    access_token: str,
    video_path: str,
    title: str,
    description: str,
    content_type: str
):
    """
    публикует видео в черновики VK.
    для VK Clips используется метод video.save
    """
    if not access_token or not isinstance(access_token, str):
        raise ValueError("VK access token не указан или имеет неверный формат")
    
    if not video_path or not os.path.exists(video_path):
        raise ValueError(f"Видеофайл не найден: {video_path}")
    
    if os.path.getsize(video_path) == 0:
        raise ValueError(f"Видеофайл пуст: {video_path}")
    
    if not title or not isinstance(title, str):
        raise ValueError("Заголовок не указан или имеет неверный формат")
    
    if not isinstance(description, str):
        description = str(description) if description else ""
    
    try:
        async with aiohttp.ClientSession() as session:
            # получение URL для загрузки
            async with session.get(
                "https://api.vk.com/method/video.save",
                params={
                    "access_token": access_token,
                    "v": "5.199",
                    "name": title[:128],
                    "description": description[:5000],
                    "is_private": 1,
                    "wallpost": 0,
                    "group_id": 0
                }
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise ValueError(f"VK API вернул ошибку: HTTP {resp.status} - {error_text}")
                
                data = await resp.json()
                if "error" in data:
                    error_info = data["error"]
                    error_msg = error_info.get("error_msg", "Неизвестная ошибка")
                    error_code = error_info.get("error_code", 0)
                    raise ValueError(f"Ошибка VK API ({error_code}): {error_msg}")
                
                if "response" not in data:
                    raise ValueError("VK API не вернул ответ")
                
                upload_url = data["response"].get("upload_url")
                if not upload_url:
                    raise ValueError("VK API не вернул URL для загрузки")

            # загрузка видео
            async with aiofiles.open(video_path, "rb") as video_file:
                video_content = await video_file.read()
                
                form = aiohttp.FormData()
                form.add_field(
                    "video_file",
                    video_content,
                    filename=os.path.basename(video_path),
                    content_type="video/mp4"
                )
                
                async with session.post(upload_url, data=form) as upload_resp:
                    if upload_resp.status != 200:
                        error_text = await upload_resp.text()
                        raise ValueError(f"VK upload вернул ошибку: HTTP {upload_resp.status} - {error_text}")
                    
                    result = await upload_resp.json()
                    if "error" in result:
                        error_info = result["error"]
                        if isinstance(error_info, dict):
                            error_msg = error_info.get("error_msg", "Неизвестная ошибка загрузки")
                            error_code = error_info.get("error_code", 0)
                            raise ValueError(f"Ошибка загрузки VK ({error_code}): {error_msg}")
                        else:
                            raise ValueError(f"Ошибка загрузки VK: {error_info}")
                    
                    video_id = result.get("video_id")
                    owner_id = result.get("owner_id")
                    
                    if not video_id or not owner_id:
                        raise ValueError("VK не вернул video_id или owner_id после загрузки")
                    
                    logger.info(f"Черновик VK создан: video{owner_id}_{video_id}")
                    return f"https://vk.com/video{owner_id}_{video_id}"

    except ValueError:
        raise
    except aiohttp.ClientError as e:
        error_msg = str(e)
        logger.error(f"Ошибка сети VK: {error_msg}")
        raise ValueError(f"Ошибка сети при публикации в VK: {error_msg}")
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Ошибка публикации VK: {error_msg}")
        
        if "invalid token" in error_msg.lower() or "unauthorized" in error_msg.lower():
            raise ValueError("Неверный VK access token")
        elif "quota" in error_msg.lower() or "limit" in error_msg.lower():
            raise ValueError("Превышен лимит запросов к VK API")
        else:
            raise ValueError(f"Ошибка публикации в VK: {error_msg}")
