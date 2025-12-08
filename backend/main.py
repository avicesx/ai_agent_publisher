import asyncio
import subprocess
import json
import uuid
import os
from telebot.async_telebot import AsyncTeleBot
from telebot import types
import re
import logging
import config
from services import OrchestratorClient
from utils import download_video

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = AsyncTeleBot(config.BOT_TOKEN)
orchestrator_client = OrchestratorClient()

user_states = {}


def get_video_dimensions(video_path: str) -> tuple:
    """Получает ширину и высоту видео через ffprobe"""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0]
        return stream.get("width", 0), stream.get("height", 0)
    except Exception:
        return 0, 0


@bot.message_handler(commands=['start'])
async def start(message):
    user_id = message.from_user.id
    user_states[user_id] = None
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("👋 Поздороваться")
    btn2 = types.KeyboardButton("🎬 Обработать видео")
    markup.add(btn1, btn2)
    await bot.send_message(
        user_id,
        "👋 Привет! Я бот для обработки видео.\n\n"
        "Отправь ссылку на видео — я удалю паузы, создам транскрибацию "
        "и проверю на соответствие политике YouTube!",
        reply_markup=markup
    )


@bot.message_handler(content_types=['text'])
async def handle_text(message):
    user_id = message.from_user.id
    
    if message.text == "👋 Поздороваться":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        btn1 = types.KeyboardButton("Что ты умеешь?")
        btn2 = types.KeyboardButton("🎬 Обработать видео")
        markup.add(btn1, btn2)
        await bot.send_message(user_id, "❓ Выберите действие:", reply_markup=markup)
    
    elif message.text == "Что ты умеешь?":
        await bot.send_message(
            user_id,
            "✅ Я умею:\n\n"
            "• Удалять паузы из видео\n"
            "• Создавать транскрибацию\n"
            "• Проверять на соответствие политике YouTube\n"
            "• Скачивать видео с YouTube\n\n"
            "Просто отправь ссылку на видео!",
            parse_mode='Markdown'
        )
    
    elif message.text == "🎬 Обработать видео":
        user_states[user_id] = 'waiting_for_link'
        await bot.send_message(
            user_id,
            "📎 Отправь ссылку на видео или видеофайл"
        )
    
    elif user_states.get(user_id) == 'waiting_for_link':
        user_states[user_id] = None
        url = message.text.strip()
        
        if not url:
            await bot.send_message(user_id, "❌ Ссылка не может быть пустой.")
            return
        
        if not re.match(r'^https?://', url):
            await bot.send_message(user_id, "❌ Нужна ссылка, начинающаяся с http:// или https://")
            return
        
        await bot.send_message(user_id, "⏳ Начинаю обработку видео...\n1️⃣ Скачивание...")
        
        try:
            await process_video_workflow(user_id, url)
        except Exception as e:
            logger.error(f"Ошибка обработки видео: {e}", exc_info=True)
            await bot.send_message(
                user_id,
                f"❌ Произошла ошибка: {str(e)}\n\n"
                "Попробуйте другую ссылку или обратитесь в поддержку."
            )


@bot.message_handler(content_types=['video', 'document'])
async def handle_video_or_document(message):
    """Обработка видео, отправленного напрямую в Telegram"""
    user_id = message.from_user.id
    
    if user_states.get(user_id) != 'waiting_for_link':
        await bot.send_message(
            user_id,
            "📎 Сначала нажмите кнопку '🎬 Обработать видео', затем отправьте файл."
        )
        return
    
    user_states[user_id] = None
    
    file_id = None
    file_name = None
    mime_type = ""
    
    if message.content_type == 'video':
        file_id = message.video.file_id
        mime_type = message.video.mime_type or "video/mp4"
        ext = mime_type.split('/')[-1] if '/' in mime_type else 'mp4'
        file_name = f"tg_video_{user_id}_{uuid.uuid4()}.{ext}"
    elif message.content_type == 'document':
        if message.document.mime_type and message.document.mime_type.startswith('video/'):
            file_id = message.document.file_id
            mime_type = message.document.mime_type
            if '.' in message.document.file_name:
                ext = message.document.file_name.split('.')[-1]
            else:
                ext = mime_type.split('/')[-1] or 'mp4'
            file_name = f"tg_video_{user_id}_{uuid.uuid4()}.{ext}"
        else:
            await bot.send_message(user_id, "📎 Я обрабатываю только видео. Этот документ не является видео.")
            return
    else:
        return
    
    await bot.send_message(user_id, "⏳ Получаю видео из Telegram...")
    
    try:
        file_info = await bot.get_file(file_id)
        downloaded_file = await bot.download_file(file_info.file_path)
        
        save_path = os.path.join(config.UPLOAD_DIR, file_name)
        
        with open(save_path, 'wb') as f:
            f.write(downloaded_file)
        
        logger.info(f"Сохранено видео от пользователя {user_id}: {save_path}")
        
        await process_video_from_path(user_id, save_path)
        
    except Exception as e:
        logger.error(f"Ошибка скачивания видео из Telegram: {e}", exc_info=True)
        await bot.send_message(
            user_id,
            f"❌ Не удалось скачать видео: {str(e)}\n\n"
            "Попробуйте отправить видео ещё раз или используйте ссылку."
        )


async def process_video_workflow(user_id: int, url: str):
    """
    Полный пайплайн обработки видео
    """
    try:
        video_path = await download_video(url)
        await process_video_from_path(user_id, video_path)
    except Exception as e:
        logger.error(f"Ошибка в workflow: {e}", exc_info=True)
        raise


async def process_video_from_path(user_id: int, video_path: str):
    """
    Пайплайн обработки видео (из файла)
    """
    try:
        await bot.send_message(user_id, "✅ Видео получено\n2️⃣ Обработка (удаление пауз, транскрипция, проверка)...")
        
        result = await orchestrator_client.process_video(video_path)
        
        if result.status == "failed":
            await bot.send_message(
                user_id,
                f"❌ Ошибка обработки: {result.error}"
            )
            return
        
        await bot.send_message(user_id, "✅ Обработка завершена!\n\n📊 Результаты:")
        
        if result.generated_content:
            youtube_data = result.generated_content.get('youtube', {})
            
            # проверка на пользовательское соглашение ютуб
            policy_check = youtube_data.get('policy_check') if youtube_data else None
            if policy_check:
                verdict = policy_check.get('verdict', 'UNKNOWN')
                confidence = policy_check.get('confidence', 0)
                
                if verdict == "ALLOW":
                    emoji = "✅"
                    text = "Видео соответствует политике YouTube"
                else:
                    emoji = "❌"
                    text = "Видео НЕ соответствует политике YouTube"
                
                await bot.send_message(
                    user_id,
                    f"{emoji} **Проверка политики:**\n"
                    f"{text}\n"
                    f"Уверенность: {confidence:.0%}",
                    parse_mode='Markdown'
                )
            
            # сгенерированный контент для ютуб
            youtube_content = youtube_data.get('content', {})
            if youtube_content:
                yt_title = youtube_content.get('title', '')
                yt_desc = youtube_content.get('description', '')
                yt_tags = youtube_content.get('tags', [])
                
                tags_str = ' '.join(yt_tags) if yt_tags else 'Нет тегов'
                
                await bot.send_message(
                    user_id,
                    f"🎬 YouTube контент:\n\n"
                    f"Заголовок:\n{yt_title}\n\n"
                    f"Описание:\n{yt_desc}\n\n"
                    f"Теги:\n{tags_str}"
                )
            
            # сгенерированный контент для тг (если есть)
            telegram_data = result.generated_content.get('telegram', {})
            telegram_content = telegram_data.get('content', {}) if telegram_data else {}
            if telegram_content:
                tg_title = telegram_content.get('title', '')
                tg_post = telegram_content.get('post', '')
                
                await bot.send_message(
                    user_id,
                    f"📱 Telegram контент:\n\n"
                    f"Заголовок:\n{tg_title}\n\n"
                    f"Пост:\n{tg_post}"
                )
            
            # обложки
            thumbnails = youtube_data.get('thumbnails', [])
            if thumbnails:
                try:
                    media_group = []
                    for i, thumb in enumerate(thumbnails, 1):
                        thumb_path = thumb.get('path', '')
                        if thumb_path:
                            media_group.append(
                                types.InputMediaPhoto(
                                    open(thumb_path, 'rb'),
                                    caption=f"🖼 Обложки ({len(thumbnails)} шт.)" if i == 1 else None
                                )
                            )
                    
                    if media_group:
                        await bot.send_media_group(user_id, media_group)
                except Exception as e:
                    logger.error(f"Ошибка отправки обложек: {e}")
        
        # транскрибация
        if result.transcription:
            # разбиваем на части, если текст более 4096 символов (ограничение тг)
            transcription = result.transcription
            max_len = 4000  # запас для заголовка
            
            if len(transcription) <= max_len:
                await bot.send_message(
                    user_id,
                    f"📝 **Транскрибация:**\n\n{transcription}",
                    parse_mode='Markdown'
                )
            else:
                await bot.send_message(
                    user_id,
                    f"📝 **Транскрибация (часть 1):**\n\n{transcription[:max_len]}",
                    parse_mode='Markdown'
                )
                remaining = transcription[max_len:]
                part = 2
                while remaining:
                    chunk = remaining[:max_len]
                    remaining = remaining[max_len:]
                    await bot.send_message(
                        user_id,
                        f"📝 **Транскрибация (часть {part}):**\n\n{chunk}",
                        parse_mode='Markdown'
                    )
                    part += 1
        
        # обработанное видео
        if result.processed_video_path:
            await bot.send_message(user_id, "🎬 Отправляю обработанное видео...")
            try:
                width, height = get_video_dimensions(result.processed_video_path)
                with open(result.processed_video_path, 'rb') as video:
                    await bot.send_video(
                        user_id, 
                        video, 
                        caption="🎬 Видео с обрезанными паузами",
                        width=width if width else None,
                        height=height if height else None
                    )
            except Exception as e:
                logger.error(f"Ошибка отправки видео: {e}")
                await bot.send_message(user_id, f"⚠️ Не удалось отправить видео: {str(e)}")
        
    except Exception as e:
        logger.error(f"Ошибка в workflow: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    logger.info("🤖 Telegram Bot запущен")
    asyncio.run(bot.polling(none_stop=True, interval=0))