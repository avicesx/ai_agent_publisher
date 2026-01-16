import logging
import os
import json
import mimetypes
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError

logger = logging.getLogger(__name__)

CREDENTIALS_DIR = "/data/yt_credentials"

os.makedirs(CREDENTIALS_DIR, exist_ok=True)

def save_credentials(user_id: int, token_data: str):
    """сохранение OAuth2 credentials пользователя"""
    path = os.path.join(CREDENTIALS_DIR, f"{user_id}.json")
    with open(path, "w") as f:
        f.write(token_data)

def load_credentials(user_id: int) -> Credentials:
    """загрузка и обновление OAuth2 credentials"""
    path = os.path.join(CREDENTIALS_DIR, f"{user_id}.json")
    if not os.path.exists(path):
        raise ValueError("Учетные данные YouTube не найдены")
    
    with open(path, "r") as f:
        info = json.load(f)
    
    creds = Credentials.from_authorized_user_info(info)
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(path, "w") as f:
                f.write(creds.to_json())
        except RefreshError as e:
            logger.error(f"Не удалось обновить учетные данные для пользователя {user_id}: {e}")
            raise ValueError("Учетные данные YouTube истекли и не могут быть обновлены")
    
    return creds

def _get_video_mimetype(video_path: str) -> str:
    """определение MIME-типа видеофайла"""
    mime_type, _ = mimetypes.guess_type(video_path)
    if mime_type and mime_type.startswith('video/'):
        return mime_type
    return 'video/mp4'

async def publish_to_youtube_draft(
    user_id: int,
    video_path: str,
    title: str,
    description: str,
    tags: list,
    content_type: str
):
    """публикация видео в черновики YouTube"""
    if not video_path or not os.path.exists(video_path):
        raise ValueError(f"Видеофайл не найден: {video_path}")
    
    if os.path.getsize(video_path) == 0:
        raise ValueError(f"Видеофайл пуст: {video_path}")
    
    if not title or not isinstance(title, str):
        raise ValueError("Заголовок не указан или имеет неверный формат")
    
    if not isinstance(description, str):
        description = str(description) if description else ""
    
    if not isinstance(tags, list):
        tags = []
    
    if content_type not in ("shorts", "video"):
        content_type = "video"
    
    try:
        creds = load_credentials(user_id)
        youtube = build("youtube", "v3", credentials=creds)

        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:500] if tags else [],
                "categoryId": "22"
            },
            "status": {
                "privacyStatus": "private",
                "selfDeclaredMadeForKids": False
            }
        }

        if content_type == "shorts":
            body["snippet"]["categoryId"] = "24"
            mime_type = _get_video_mimetype(video_path)
            insert_request = youtube.videos().insert(
                part=",".join(body.keys()),
                body=body,
                media_body=MediaFileUpload(video_path, mimetype=mime_type)
            )
        else:
            insert_request = youtube.videos().insert(
                part=",".join(body.keys()),
                body=body,
                media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True)
            )

        response = insert_request.execute()
        video_id = response.get("id")
        
        if not video_id:
            raise ValueError("YouTube API не вернул ID видео")
        
        logger.info(f"Черновик YouTube создан: {video_id} для пользователя {user_id}")
        return f"https://studio.youtube.com/video/{video_id}/edit"

    except ValueError:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Ошибка публикации YouTube для пользователя {user_id}: {error_msg}")
        
        if "quota" in error_msg.lower() or "exceeded" in error_msg.lower():
            raise ValueError("Превышен лимит запросов к YouTube API")
        elif "forbidden" in error_msg.lower() or "unauthorized" in error_msg.lower():
            raise ValueError("Ошибка авторизации YouTube")
        elif "invalid" in error_msg.lower():
            raise ValueError(f"Ошибка валидации YouTube API: {error_msg}")
        else:
            raise ValueError(f"Ошибка публикации в YouTube: {error_msg}")
