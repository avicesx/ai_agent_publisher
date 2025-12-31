import logging
from telebot.async_telebot import AsyncTeleBot

logger = logging.getLogger(__name__)

async def publish_to_telegram_channel(
    bot_token: str,
    channel_id: str,  # @username или -100... 
    video_path: str,
    title: str,
    post_text: str
):
    """
    Отправляет видео в Telegram-канал от имени бота.
    Бот должен быть админом канала.
    """
    try:
        bot = AsyncTeleBot(bot_token)
        caption = f"<b>{title}</b>\n\n{post_text}"[:1024]  # лимит caption
        
        with open(video_path, "rb") as video:
            msg = await bot.send_video(
                chat_id=channel_id,
                video=video,
                caption=caption,
                parse_mode="HTML"
            )
        
        # Возвращаем ссылку на пост
        link = f"https://t.me/{channel_id.lstrip('@')}/{msg.message_id}" if channel_id.startswith("@") else f"Сообщение отправлено в канал {channel_id}"
        logger.info(f"Telegram post sent: {link}")
        return link

    except Exception as e:
        logger.error(f"Telegram publish error: {e}")
        raise