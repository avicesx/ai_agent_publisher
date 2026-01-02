import logging
import os
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

# Каталог для хранения credentials
CREDENTIALS_DIR = "/data/yt_credentials"

os.makedirs(CREDENTIALS_DIR, exist_ok=True)

def save_credentials(user_id: int, token_data: str):
    """Сохранение OAuth2 credentials пользователя"""
    path = os.path.join(CREDENTIALS_DIR, f"{user_id}.json")
    with open(path, "w") as f:
        f.write(token_data)

def load_credentials(user_id: int) -> Credentials:
    """Загрузка и обновление OAuth2 credentials"""
    path = os.path.join(CREDENTIALS_DIR, f"{user_id}.json")
    if not os.path.exists(path):
        raise ValueError("YouTube credentials not found")
    
    with open(path, "r") as f:
        info = json.load(f)
    
    creds = Credentials.from_authorized_user_info(info)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(path, "w") as f:
            f.write(creds.to_json())
    
    return creds

async def publish_to_youtube_draft(
    user_id: int,
    video_path: str,
    title: str,
    description: str,
    tags: list,
    content_type: str  # 'shorts' или 'video'
):
    """Публикация видео в черновики YouTube"""
    try:
        creds = load_credentials(user_id)
        youtube = build("youtube", "v3", credentials=creds)

        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:500],
                "categoryId": "22"  # People & Blogs
            },
            "status": {
                "privacyStatus": "private",  # черновик
                "selfDeclaredMadeForKids": False
            }
        }

        # Для Shorts — особый MIME-type и категория
        if content_type == "shorts":
            body["snippet"]["categoryId"] = "24"  # Entertainment
            insert_request = youtube.videos().insert(
                part=",".join(body.keys()),
                body=body,
                media_body=MediaFileUpload(video_path, mimetype="video/quicktime")
            )
        else:
            insert_request = youtube.videos().insert(
                part=",".join(body.keys()),
                body=body,
                media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True)
            )

        response = insert_request.execute()
        video_id = response.get("id")
        logger.info(f"YouTube draft created: {video_id} for user {user_id}")
        return f"https://studio.youtube.com/video/{video_id}/edit"

    except Exception as e:
        logger.error(f"YouTube publish error for {user_id}: {e}")
        raise