import logging
import aiohttp
import os

logger = logging.getLogger(__name__)

async def publish_to_vk_draft(
    access_token: str,
    video_path: str,
    title: str,
    description: str,
    content_type: str  # 'clip'
):
    """
    Публикует видео в черновики VK (на самом деле — создаёт запись в альбоме, но не публикует на стене)
    Для VK Clips используется метод video.save
    """
    try:
        async with aiohttp.ClientSession() as session:
            # Шаг 1: Получить URL для загрузки
            async with session.get(
                "https://api.vk.com/method/video.save",
                params={
                    "access_token": access_token,
                    "v": "5.199",
                    "name": title[:128],
                    "description": description[:5000],
                    "is_private": 1,  # черновик
                    "wallpost": 0,
                    "group_id": 0  # личная страница
                }
            ) as resp:
                data = await resp.json()
                if "error" in data:
                    raise ValueError(f"VK API error: {data['error']['error_msg']}")
                
                upload_url = data["response"]["upload_url"]

            # Шаг 2: Загрузить видео
            with open(video_path, "rb") as f:
                form = aiohttp.FormData()
                form.add_field("video_file", f, filename=os.path.basename(video_path))
                async with session.post(upload_url, data=form) as upload_resp:
                    result = await upload_resp.json()
                    if "error" in result:
                        raise ValueError(f"VK upload error: {result.get('error', 'unknown')}")

            video_id = result.get("video_id")
            owner_id = result.get("owner_id")
            logger.info(f"VK draft created: video{owner_id}_{video_id}")
            return f"https://vk.com/video{owner_id}_{video_id}"

    except Exception as e:
        logger.error(f"VK publish error: {e}")
        raise