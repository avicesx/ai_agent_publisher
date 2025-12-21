# main.py (новый на aiogram)

import asyncio
import subprocess
import json
import uuid
import os
from aiogram import F, Router, Bot, Dispatcher
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import re
import logging
import config
from orchestrator_client import OrchestratorClient
from video_downloader import download_video 
from datetime import datetime

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- FSM ---
class BotStates(StatesGroup):
    waiting_for_link = State()

# --- Bot Setup ---
bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage() 
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

orchestrator_client = OrchestratorClient()

# --- Helper Functions ---

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
    except Exception as e:
        logger.warning(f"Could not get video dimensions: {e}")
        return 0, 0

# --- Handlers ---

@router.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear() 
    markup = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👋 Поздороваться")],
            [KeyboardButton(text="🎬 Обработать видео")]
        ],
        resize_keyboard=True
    )
    await message.answer(
        "👋 Привет! Я бот для обработки видео.\n\n"
        "Отправь ссылку на видео — я удалю паузы, создам транскрибацию "
        "и проверю на соответствие политике YouTube!",
        reply_markup=markup
    )

@router.message(F.text == "👋 Поздороваться")
async def handle_hello(message: Message):
    markup = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Что ты умеешь?")],
            [KeyboardButton(text="🎬 Обработать видео")]
        ],
        resize_keyboard=True
    )
    await message.answer("❓ Выберите действие:", reply_markup=markup)

@router.message(F.text == "Что ты умеешь?")
async def handle_what_can_do(message: Message):
    await message.answer(
        "✅ Я умею:\n\n"
        "• Удалять паузы из видео\n"
        "• Создавать транскрибацию\n"
        "• Проверять на соответствие политике YouTube\n"
        "• Скачивать видео с YouTube\n\n"
        "Просто отправь ссылку на видео!",
        parse_mode='Markdown'
    )

@router.message(F.text == "🎬 Обработать видео")
async def handle_start_video_processing(message: Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_link)
    await message.answer("📎 Отправь ссылку на видео или видеофайл")

@router.message(BotStates.waiting_for_link, F.text)
async def handle_link_input(message: Message, state: FSMContext):
    url = message.text.strip()
    user_id = message.from_user.id

    if not url:
        await message.answer("❌ Ссылка не может быть пустой.")
        return

    if not re.match(r'^https?://', url):
        await message.answer("❌ Нужна ссылка, начинающаяся с http:// или https://")
        return

    # Сообщение о начале обработки
    progress_msg = await message.answer("⏳ Начинаю обработку видео...\n1️⃣ Скачивание...")

    try:
        # Запускаем обработку и передаем объекты бота и сообщения для прогресса
        video_path = await download_video(
            url,
            bot_instance=bot,
            chat_id=user_id,
            progress_msg_id=progress_msg.message_id
        )
        # После успешного скачивания, запускаем остальную обработку
        await process_video_from_path(user_id, video_path, progress_msg)
    except Exception as e:
        logger.error(f"Ошибка обработки видео: {e}", exc_info=True)
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=progress_msg.message_id,
            text=f"❌ Произошла ошибка: {str(e)}\n\n"
                 "Попробуйте другую ссылку или обратитесь в поддержку."
        )
    finally:
        # Независимо от успеха/ошибки, очищаем состояние после получения ссылки
        await state.clear()


@router.message(BotStates.waiting_for_link, (F.video | F.document))
async def handle_video_or_document(message: Message, state: FSMContext):
    """Обработка видео, отправленного напрямую в Telegram"""
    user_id = message.from_user.id
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
            await message.answer("📎 Я обрабатываю только видео. Этот документ не является видео.")
            return
    else:
        return

    progress_msg = await message.answer("⏳ Получаю видео из Telegram...")

    try:
        file_info = await bot.get_file(file_id)
        downloaded_file = await bot.download_file(file_info.file_path)

        save_path = os.path.join(config.UPLOAD_DIR, file_name)

        with open(save_path, 'wb') as f:
            f.write(downloaded_file)

        logger.info(f"Сохранено видео от пользователя {user_id}: {save_path}")

        # Передаем progress_msg дальше для обновления
        await process_video_from_path(user_id, save_path, progress_msg)

    except Exception as e:
        logger.error(f"Ошибка скачивания видео из Telegram: {e}", exc_info=True)
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=progress_msg.message_id,
            text=f"❌ Не удалось скачать видео: {str(e)}\n\n"
                 "Попробуйте отправить видео ещё раз или используйте ссылку."
        )
    finally:
        await state.clear()

async def process_video_from_path(user_id: int, video_path: str, initial_progress_msg):
    """
    Пайплайн обработки видео (из файла)
    """
    try:
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=initial_progress_msg.message_id,
            text="✅ Видео получено\n2️⃣ Обработка (удаление пауз, транскрипция, проверка)..."
        )

        result = await orchestrator_client.process_video(video_path)

        if result.status == "failed":
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=initial_progress_msg.message_id,
                text=f"❌ Ошибка обработки: {result.error}"
            )
            return

        await bot.edit_message_text(
            chat_id=user_id,
            message_id=initial_progress_msg.message_id,
            text="✅ Обработка завершена!\n\n📊 Результаты:"
        )

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
                        if thumb_path and os.path.exists(thumb_path):
                            input_file = FSInputFile(thumb_path)
                            if i == 1:
                                media_group.append(
                                    InputMediaPhoto(
                                        media=input_file,
                                        caption=f"🖼 Обложки ({len(thumbnails)} шт.)"
                                    )
                                )
                            else:
                                media_group.append(
                                    InputMediaPhoto(
                                        media=input_file
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
        if result.processed_video_path and os.path.exists(result.processed_video_path):
            await bot.send_message(user_id, "🎬 Отправляю обработанное видео...")
            try:
                width, height = get_video_dimensions(result.processed_video_path)
                input_file = FSInputFile(result.processed_video_path)
                await bot.send_video(
                    user_id,
                    video=input_file,
                    caption="🎬 Видео с обрезанными паузами",
                    width=width if width > 0 else None,
                    height=height if height > 0 else None
                )
            except Exception as e:
                logger.error(f"Ошибка отправки видео: {e}")
                await bot.send_message(user_id, f"⚠️ Не удалось отправить видео: {str(e)}")

    except Exception as e:
        logger.error(f"Ошибка в workflow: {e}", exc_info=True)
        # Пытаемся отредактировать сообщение об ошибке, но если оно уже удалено/изменилось, просто отправим новое
        try:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=initial_progress_msg.message_id,
                text=f"❌ Неожиданная ошибка: {str(e)}"
            )
        except Exception:
            await bot.send_message(user_id, f"❌ Неожиданная ошибка: {str(e)}")


# --- Main Runner ---
async def main():
    logger.info("🤖 Telegram Bot (aiogram) запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
