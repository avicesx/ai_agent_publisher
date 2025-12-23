import asyncio
import subprocess
import json
import uuid
import os
import shutil
from telebot.async_telebot import AsyncTeleBot
from telebot import types, apihelper, asyncio_helper
import re
import logging
import config
from services import OrchestratorClient
from utils import download_video
from database import init_db, get_settings, update_settings


user_states = {}


logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if config.TELEGRAM_API_URL:
    apihelper.API_URL = config.TELEGRAM_API_URL + "/bot{0}/{1}"
    apihelper.FILE_URL = config.TELEGRAM_API_URL + "/file/bot{0}/{1}"
    asyncio_helper.API_URL = config.TELEGRAM_API_URL + "/bot{0}/{1}"
    asyncio_helper.FILE_URL = config.TELEGRAM_API_URL + "/file/bot{0}/{1}"
    logger.info(f"Используется локальный Bot API: {config.TELEGRAM_API_URL}")

bot = AsyncTeleBot(config.BOT_TOKEN)
orchestrator_client = OrchestratorClient()

user_states = {}
user_status_messages = {} # {user_id: message_id}

async def send_status(user_id: int, text: str, parse_mode=None):
    """
    Отправляет статусное сообщение, удаляя предыдущее.
    """
    try:
        if user_id in user_status_messages:
            try:
                await bot.delete_message(user_id, user_status_messages[user_id])
            except Exception as e:
                logger.debug(f"Не удалось удалить сообщение {user_status_messages[user_id]}: {e}")
        
        msg = await bot.send_message(user_id, text, parse_mode=parse_mode)
        user_status_messages[user_id] = msg.message_id
        return msg
    except Exception as e:
        logger.error(f"Ошибка в send_status: {e}")
        return await bot.send_message(user_id, text, parse_mode=parse_mode)



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
    if message.from_user.is_bot:
        return
    user_id = message.from_user.id
    user_states[user_id] = None
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("🎬 Обработать видео")
    btn2 = types.KeyboardButton("⚙️ Настройки")
    markup.add(btn1, btn2)
    await bot.send_message(
        user_id,
        "👋 Привет! Я бот для обработки видео.\n\n"
        "Отправь ссылку на видео — я удалю паузы, создам транскрибацию "
        "и проверю на соответствие политике YouTube!",
        reply_markup=markup
    )


def get_settings_ui(user_id):
    """Генерация текста и клавиатуры настроек"""
    settings = get_settings(user_id)
    markup = types.InlineKeyboardMarkup()
    
    # Платформа
    platforms = settings.get("platform", "all")
    btn_youtube = types.InlineKeyboardButton(
        f"{'✅ ' if platforms in ['youtube', 'all'] else ''}YouTube", 
        callback_data="set_platform_youtube"
    )
    btn_telegram = types.InlineKeyboardButton(
        f"{'✅ ' if platforms in ['telegram', 'all'] else ''}Telegram", 
        callback_data="set_platform_telegram"
    )
    markup.row(btn_youtube, btn_telegram)
    
    # Формат поста
    current_format = settings.get("post_format", "neutral")
    formats = {
        "neutral": "Нейтральный",
        "selling": "Продающий",
        "cta_subscribe": "Подписка",
        "warming": "Прогрев"
    }
    
    row_btns = []
    for fmt_key, fmt_name in formats.items():
        text = f"{'✅ ' if current_format == fmt_key else ''}{fmt_name}"
        row_btns.append(types.InlineKeyboardButton(text, callback_data=f"set_format_{fmt_key}"))
        if len(row_btns) == 2:
            markup.row(*row_btns)
            row_btns = []
    if row_btns:
        markup.row(*row_btns)
        
    # Кастомный промт
    custom_prompt = settings.get("custom_prompt")
    prompt_text = "✏️ Задать свой промт" if not custom_prompt else "✏️ Изменить промт"
    markup.row(types.InlineKeyboardButton(prompt_text, callback_data="set_custom_prompt"))
    
    if custom_prompt:
        markup.row(types.InlineKeyboardButton("❌ Сбросить промт", callback_data="clear_custom_prompt"))
    
    text = (
        "⚙️ **Настройки бота**\n\n"
        f"📺 **Платформы**: {platforms}\n"
        f"📝 **Формат**: {formats.get(current_format, current_format)}\n"
    )
    if custom_prompt:
        text += f"\n💡 **Свой промт**: _{custom_prompt[:50]}..._"
        
    return text, markup


@bot.message_handler(commands=['settings'])
async def settings_command(message):
    if message.from_user.is_bot:
        return
    user_id = message.from_user.id
    text, markup = get_settings_ui(user_id)
    await bot.send_message(user_id, text, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data.startswith('set_platform_'))
async def callback_platform(call):
    user_id = call.from_user.id
    action = call.data.split('_')[2]  # youtube или telegram
    current = get_settings(user_id).get("platform", "all")
    
    platforms_set = set(["youtube", "telegram"]) if current == "all" else {current}
    
    if action in platforms_set:
        if len(platforms_set) > 1:
            platforms_set.remove(action)
    else:
        platforms_set.add(action)
        
    if not platforms_set:
        await bot.answer_callback_query(call.id, "Минимум одна платформа должна быть выбрана!")
        return

    if platforms_set == {"youtube", "telegram"}:
        final_platform = "all"
    else:
        final_platform = list(platforms_set)[0]
        
    update_settings(user_id, platform=final_platform)
    
    # Обновляем сообщение вместо отправки нового
    text, markup = get_settings_ui(user_id)
    try:
        await bot.edit_message_text(
            text, 
            chat_id=call.message.chat.id, 
            message_id=call.message.message_id, 
            reply_markup=markup, 
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.debug(f"Message not modified: {e}")
        
    await bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('set_format_'))
async def callback_format(call):
    user_id = call.from_user.id
    new_format = call.data.split('_')[2]
    update_settings(user_id, post_format=new_format)
    
    text, markup = get_settings_ui(user_id)
    try:
        await bot.edit_message_text(
            text, 
            chat_id=call.message.chat.id, 
            message_id=call.message.message_id, 
            reply_markup=markup, 
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.debug(f"Message not modified: {e}")
        
    await bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == 'set_custom_prompt')
async def callback_custom_prompt(call):
    user_id = call.from_user.id
    user_states[user_id] = "waiting_prompt"
    await bot.send_message(user_id, "✍️ Напишите инструкцию для генерации текста (например: 'Пиши как пират', 'Делай акцент на цифрах').")
    await bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == 'clear_custom_prompt')
async def callback_clear_prompt(call):
    user_id = call.from_user.id
    update_settings(user_id, custom_prompt=None)
    
    text, markup = get_settings_ui(user_id)
    try:
        await bot.edit_message_text(
            text, 
            chat_id=call.message.chat.id, 
            message_id=call.message.message_id, 
            reply_markup=markup, 
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.debug(f"Message not modified: {e}")
        
    await bot.answer_callback_query(call.id)


@bot.message_handler(content_types=['text'])
async def handle_text(message):
    if message.from_user.is_bot:
        return
    user_id = message.from_user.id
    
    if user_states.get(user_id) == "waiting_prompt":
        update_settings(user_id, custom_prompt=message.text)
        user_states[user_id] = None
        await bot.send_message(user_id, "✅ Промт сохранен!")
        await settings_command(message)
        return

    if message.text == "⚙️ Настройки":
        await settings_command(message)
    
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
        
        await send_status(user_id, "⏳ Начинаю обработку видео...\n1️⃣ Скачивание...")
        
        try:
            await process_video_workflow(user_id, url)
        except Exception as e:
            logger.error(f"Ошибка обработки видео: {e}", exc_info=True)
            await send_status(
                user_id,
                f"❌ Произошла ошибка: {str(e)}\n\n"
                "Попробуйте другую ссылку или обратитесь в поддержку."
            )


@bot.message_handler(content_types=['video', 'document'])
async def handle_video_or_document(message):
    """Обработка видео, отправленного напрямую в Telegram"""
    if message.from_user.is_bot:
        return
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
    
    await send_status(user_id, "⏳ Получаю видео из Telegram...")
    
    try:
        file_info = await bot.get_file(file_id)
        logger.info(f"Получена информация о файле: {file_info}")
        save_path = os.path.join(config.UPLOAD_DIR, file_name)
        
        if config.TELEGRAM_API_URL and file_info.file_path.startswith('/'):
            local_file_path = file_info.file_path
            logger.info(f"Попытка прямого копирования из: {local_file_path}")
            if os.path.exists(local_file_path):
                shutil.copy(local_file_path, save_path)
                logger.info(f"Скопирован файл из локального Bot API: {local_file_path}")
            else:
                logger.warning(f"Файл не найден локально: {local_file_path}, скачиваю через API")
                downloaded_file = await bot.download_file(file_info.file_path)
                with open(save_path, 'wb') as f:
                    f.write(downloaded_file)
        else:
            downloaded_file = await bot.download_file(file_info.file_path)
            with open(save_path, 'wb') as f:
                f.write(downloaded_file)
        
        logger.info(f"Сохранено видео от пользователя {user_id}: {save_path}")
        
        await process_video_from_path(user_id, save_path)
        
    except Exception as e:
        logger.error(f"Ошибка скачивания видео из Telegram: {e}", exc_info=True)
        await send_status(
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
        await send_status(user_id, "✅ Видео получено\n2️⃣ Обработка (удаление пауз, транскрипция, проверка)...")
        
        settings = get_settings(user_id)
        
        platforms_val = settings.get("platform", "all")
        if platforms_val == "all":
            platforms = ["youtube", "telegram"]
        else:
            platforms = [platforms_val]
        
        post_format = settings.get("post_format", "neutral")
        custom_prompt = settings.get("custom_prompt")
        
        result = await orchestrator_client.process_video(
            video_path,
            platforms=platforms,
            post_format=post_format,
            custom_prompt=custom_prompt
        )
        
        if result.status == "failed":
            await send_status(
                user_id,
                f"❌ Ошибка обработки: {result.error}"
            )
            return
        
        await send_status(user_id, "✅ Обработка завершена!\n\n📊 Результаты:")
        
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
                yt_title = youtube_content.get('title', '').strip('"')
                yt_desc = youtube_content.get('description', '').strip('"')
                yt_tags = youtube_content.get('tags', [])
                
                tags_str = ' '.join(yt_tags) if yt_tags else 'Нет тегов'
                
                await bot.send_message(
                    user_id,
                    f"🎬 YouTube контент:\n\n"
                    f"{yt_title}\n\n"
                    f"{yt_desc}\n\n"
                    f"{tags_str}"
                )
            
            # сгенерированный контент для тг (если есть)
            telegram_data = result.generated_content.get('telegram', {})
            telegram_content = telegram_data.get('content', {}) if telegram_data else {}
            if telegram_content:
                tg_title = telegram_content.get('title', '').strip('"')
                tg_post = telegram_content.get('post', '').strip('"')
                
                await bot.send_message(
                    user_id,
                    f"📱 Telegram контент:\n\n"
                    f"**{tg_title}**\n\n"
                    f"{tg_post}",
                    parse_mode='Markdown'
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
            # transcription = result.transcription
            # max_len = 4000  # запас для заголовка
            
            # if len(transcription) <= max_len:
            #     await bot.send_message(
            #         user_id,
            #         f"📝 **Транскрибация:**\n\n{transcription}",
            #         parse_mode='Markdown'
            #     )
            # else:
            #     await bot.send_message(
            #         user_id,
            #         f"📝 **Транскрибация (часть 1):**\n\n{transcription[:max_len]}",
            #         parse_mode='Markdown'
            #     )
            #     remaining = transcription[max_len:]
            #     part = 2
            #     while remaining:
            #         chunk = remaining[:max_len]
            #         remaining = remaining[max_len:]
            #         await bot.send_message(
            #             user_id,
            #             f"📝 **Транскрибация (часть {part}):**\n\n{chunk}",
            #             parse_mode='Markdown'
            #         )
            #         part += 1
            pass
        
        # обработанное видео
        if result.processed_video_path:
            await send_status(user_id, "🎬 Отправляю обработанное видео...")
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
                if user_id in user_status_messages:
                     try:
                        await bot.delete_message(user_id, user_status_messages[user_id])
                        del user_status_messages[user_id]
                     except Exception:
                        pass

            except Exception as e:
                logger.error(f"Ошибка отправки видео: {e}")
                await bot.send_message(user_id, f"⚠️ Не удалось отправить видео: {str(e)}")
        
    except Exception as e:
        logger.error(f"Ошибка в workflow: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    init_db()
    logger.info("🤖 Telegram Bot запущен")
    asyncio.run(bot.polling(none_stop=True, interval=0))