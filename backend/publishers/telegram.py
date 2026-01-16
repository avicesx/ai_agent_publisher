import logging
import re
from typing import Optional
from telebot.async_telebot import AsyncTeleBot

logger = logging.getLogger(__name__)


def _validate_bot_token(token: str) -> bool:
    """проверяет формат bot token"""
    if not token or not isinstance(token, str):
        return False
    token = token.strip()
    pattern = r'^\d+:[A-Za-z0-9_-]+$'
    return bool(re.match(pattern, token))


def _validate_channel_id(channel_id: str) -> tuple[bool, str]:
    """
    проверяет формат channel_id.
    возвращает (is_valid, normalized_id)
    """
    if not channel_id or not isinstance(channel_id, str):
        return False, ""
    
    channel_id = channel_id.strip()
    
    if channel_id.startswith("@"):
        if len(channel_id) < 2:
            return False, ""
        username = channel_id[1:]
        if re.match(r'^[a-zA-Z0-9_]{1,32}$', username):
            return True, channel_id
        return False, ""
    
    if channel_id.startswith("-"):
        try:
            num_id = int(channel_id)
            if num_id < 0:
                return True, channel_id
        except ValueError:
            pass
    
    return False, ""


async def publish_to_telegram_channel(
    bot_token: str,
    channel_id: str,
    video_path: Optional[str],
    title: str,
    post_text: str
) -> str:
    """
    отправляет пост в Telegram-канал от имени бота.
    
    Args:
        bot_token: токен бота от @BotFather
        channel_id: @username канала или числовой ID (например: @mychannel или -1001234567890)
        video_path: путь к видеофайлу (опционально)
        title: заголовок поста
        post_text: текст поста
    
    Returns:
        ссылка на опубликованный пост
    
    Raises:
        ValueError: при неверных параметрах или проблемах с доступом
    """
    if not bot_token:
        raise ValueError("Bot Token не указан")
    
    bot_token = bot_token.strip()
    if not _validate_bot_token(bot_token):
        raise ValueError(
            "Неверный формат Bot Token.\n\n"
            "Токен должен иметь формат: число:буквы_цифры\n"
            "Получить токен можно у @BotFather командой /newbot"
        )
    
    if not channel_id:
        raise ValueError("Channel ID не указан")
    
    is_valid, normalized_channel_id = _validate_channel_id(channel_id)
    if not is_valid:
        raise ValueError(
            f"Неверный формат Channel ID: {channel_id}\n\n"
            "Используйте один из форматов:\n"
            "• @username канала (например: @mychannel)\n"
            "• Числовой ID канала (например: -1001234567890)\n\n"
            "Как получить числовой ID:\n"
            "1. Перешлите любое сообщение из канала боту @userinfobot\n"
            "2. Он покажет ID канала"
        )
    
    channel_id = normalized_channel_id
    bot = AsyncTeleBot(bot_token)
    
    caption = f"<b>{title}</b>\n\n{post_text}"
    max_caption_len = 1024 if video_path else 4096
    if len(caption) > max_caption_len:
        caption = caption[:max_caption_len - 3] + "..."
    
    try:
        # проверка доступа к каналу
        try:
            chat = await bot.get_chat(channel_id)
            if chat.type not in ['channel', 'supergroup']:
                raise ValueError(
                    f"Указанный ID не является каналом или супергруппой: {channel_id}\n"
                    "Для публикации нужен именно канал или супергруппа."
                )
            logger.info(f"Доступ к каналу подтвержден: {channel_id} (тип: {chat.type})")
        except Exception as check_err:
            error_str = str(check_err).lower()
            
            if "chat not found" in error_str or "not found" in error_str:
                raise ValueError(
                    f"❌ Канал не найден или бот не имеет доступа: {channel_id}\n\n"
                    "Проверьте:\n"
                    "1. ✅ Бот добавлен в канал как администратор\n"
                    "2. ✅ @username указан правильно (без лишних символов)\n"
                    "3. ✅ Если канал приватный, используйте числовой ID\n"
                    "4. ✅ Бот имеет права на публикацию сообщений"
                )
            elif "unauthorized" in error_str or "invalid token" in error_str:
                raise ValueError(
                    "❌ Неверный Bot Token или бот не авторизован.\n\n"
                    "Проверьте правильность токена у @BotFather"
                )
            else:
                logger.warning(f"Не удалось проверить доступ к каналу: {check_err}. Продолжаем отправку...")
        
        # отправка контента
        if video_path:
            try:
                with open(video_path, "rb") as video_file:
                    msg = await bot.send_video(
                        chat_id=channel_id,
                        video=video_file,
                        caption=caption,
                        parse_mode="HTML"
                    )
            except FileNotFoundError:
                raise ValueError(f"Видеофайл не найден: {video_path}")
        else:
            msg = await bot.send_message(
                chat_id=channel_id,
                text=caption,
                parse_mode="HTML"
            )
        
        # формирование ссылки на пост
        if channel_id.startswith("@"):
            link = f"https://t.me/{channel_id.lstrip('@')}/{msg.message_id}"
        else:
            link = f"https://t.me/c/{channel_id.lstrip('-')}/{msg.message_id}"
        
        logger.info(f"✅ Telegram пост успешно отправлен: {link}")
        return link
        
    except ValueError:
        raise
    except Exception as api_err:
        error_str = str(api_err).lower()
        
        if "chat not found" in error_str or "not found" in error_str:
            raise ValueError(f"Канал не найден: {channel_id}")
        elif "unauthorized" in error_str or "invalid token" in error_str:
            raise ValueError("Неверный Bot Token")
        elif "forbidden" in error_str or "not enough rights" in error_str:
            raise ValueError(f"Бот не имеет прав на публикацию в канал: {channel_id}")
        else:
            logger.error(f"Telegram API ошибка: {api_err}")
            raise ValueError(f"Ошибка Telegram API: {str(api_err)}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка при публикации в Telegram: {e}", exc_info=True)
        raise ValueError(f"Ошибка при публикации: {str(e)}")
