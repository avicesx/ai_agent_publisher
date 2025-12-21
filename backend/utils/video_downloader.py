# universal_downloader.py
import os
import uuid
import logging
import re
import asyncio
import aiofiles
import httpx
from yt_dlp import YoutubeDL
import config
from aiogram import Bot

logger = logging.getLogger(__name__)

# --- Яндекс.Диск ---
def is_yandex_disk(url: str) -> bool:
    """Проверяет, является ли ссылка Яндекс.Диск"""
    return "disk.yandex" in url or "yadi.sk" in url

async def get_yandex_disk_direct_url_async(public_url: str) -> str:
    """Асинхронно получает прямую ссылку на скачивание с Яндекс.Диска"""
    api_url = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
    async with httpx.AsyncClient() as client:
        response = await client.get(api_url, params={"public_key": public_url}, timeout=30)
        response.raise_for_status()
        return response.json()["href"]

async def download_yandex_with_progress(
    url: str,
    output_path: str,
    bot: Bot,
    chat_id: int,
    progress_msg_id: int
) -> str:
    """Скачивает файл с Яндекс.Диска с отображением прогресса."""
    direct_url = await get_yandex_disk_direct_url_async(url)

    async with httpx.stream("GET", direct_url, timeout=60) as r:
        r.raise_for_status()
        total_size = int(r.headers.get("Content-Length", 0))
        downloaded = 0
        last_percent = 0

        async with aiofiles.open(output_path, "wb") as f:
            async for chunk in r.aiter_bytes():
                await f.write(chunk)
                downloaded += len(chunk)

                if total_size:
                    percent = int(downloaded * 100 / total_size)
                    if percent - last_percent >= 5:
                        last_percent = percent
                        try:
                            await bot.edit_message_text(
                                f"⏳ Скачивание с Яндекс.Диска: {percent}%",
                                chat_id=chat_id,
                                message_id=progress_msg_id
                            )
                        except Exception:
                            pass 
                        await asyncio.sleep(0.1) # Небольшая задержка, чтобы не спамить API

    return output_path

# --- Google Drive ---
def is_google_drive(url: str) -> bool:
    """Проверяет, является ли ссылка Google Drive"""
    return "drive.google.com" in url

def normalize_google_drive_url(url: str) -> str:
    """Приводит ссылку Google Drive к формату, который понимает yt-dlp"""
    match = re.search(r"/d/([^/]+)", url)
    if match:
        return f"https://drive.google.com/uc?id={match.group(1)}"
    return url

# --- Универсальное скачивание с прогрессом для yt-dlp ---
def create_progress_hook(bot: Bot, chat_id: int, progress_msg_id: int):
    """Создает функцию-обработчик прогресса для yt-dlp."""
    last_sent_percent = [-1]  
    last_update_time = [0]

    async def hook(d):
        if d['status'] == 'downloading':
            now = asyncio.get_event_loop().time()
            # Извлекаем текущий процент выполнения
            percent_str = d.get('_percent_str', 'N/A').strip()
            try:
                # Пытаемся извлечь числовое значение процента
                current_percent = float(percent_str.replace('%', ''))
            except ValueError:
                # Если не получилось (например, 'N/A'), используем -1
                current_percent = -1

            # Обновляем, если процент изменился на 1% или больше ИЛИ прошло 10 секунд (на всякий случай)
            # Это гарантирует обновление даже если процент "зависает" на .0 или .99
            if (abs(current_percent - last_sent_percent[0]) >= 1.0 or
                now - last_update_time[0] > 10):
                
                # Проверяем, действительно ли процент изменился, чтобы не обновлять лишний раз
                if current_percent != last_sent_percent[0]:
                    last_sent_percent[0] = current_percent
                    last_update_time[0] = now # Обновляем время при отправке
                
                    try:
                        speed_str = d.get('_speed_str', 'N/A')
                        eta_str = d.get('_eta_str', 'N/A')
                        # Формируем текст с текущим процентом
                        msg_text = f"⏳ Скачивание: {percent_str} (Скорость: {speed_str}, ETA: {eta_str})"
                        await bot.edit_message_text(
                            msg_text,
                            chat_id=chat_id,
                            message_id=progress_msg_id
                        )
                    except Exception:
                        pass # Игнорируем ошибки при обновлении, если сообщение исчезло

    return hook

async def download_video(
    url: str,
    bot_instance: Bot,
    chat_id: int,
    progress_msg_id: int
) -> str:
    """
    Скачивает видео по ссылке и сохраняет в UPLOAD_DIR.
    Отображает прогресс для всех типов источников.
    """
    video_id = str(uuid.uuid4())
    output_path = os.path.join(config.UPLOAD_DIR, f"video_{video_id}.mp4")

    logger.info(f"Скачивание видео: {url}")

    # Яндекс.Диск (с асинхронным прогрессом)
    if is_yandex_disk(url):
        return await download_yandex_with_progress(url, output_path, bot_instance, chat_id, progress_msg_id)

    # Google Drive
    if is_google_drive(url):
        url = normalize_google_drive_url(url)

    # Остальные ссылки через yt-dlp с прогрессом
    ydl_opts = {
        "outtmpl": output_path,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        # "quiet": True, # Закомментировано, чтобы видеть логи yt-dlp в консоли
        "no_warnings": False, # Показываем предупреждения
        "progress_hooks": [create_progress_hook(bot_instance, chat_id, progress_msg_id)]
    }

    loop = asyncio.get_running_loop()
    def run_ydl():
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            requested_ext = 'mp4'
            actual_filename = ydl.prepare_filename(info)
            if not actual_filename.endswith('.mp4'):
                 actual_filename += '.mp4'
            return actual_filename

    final_path = await loop.run_in_executor(None, run_ydl)

    if os.path.exists(final_path):
        if final_path != output_path:
             os.rename(final_path, output_path)
        final_path_to_return = output_path
    else:
        if not os.path.exists(output_path):
            raise RuntimeError("Видео не было создано или yt-dlp не вернул ожидаемое имя файла")
        final_path_to_return = output_path

    # После завершения скачивания, обновляем сообщение
    try:
        await bot_instance.edit_message_text(
            "✅ Скачивание завершено",
            chat_id=chat_id,
            message_id=progress_msg_id
        )
    except Exception:
        pass # Игнорируем ошибки при финальном обновлении

    return final_path_to_return
