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
from database import (
    init_db, get_settings, update_settings,
    add_api_key, get_api_keys, delete_api_key, get_api_key_by_id,
    add_scenario, get_scenarios, delete_scenario, get_scenario_by_id
)
from publishers.youtube import publish_to_youtube_draft, save_credentials as save_yt_creds
from publishers.vk import publish_to_vk_draft
from publishers.telegram import publish_to_telegram_channel

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
user_status_messages = {}

async def send_status(user_id: int, text: str, parse_mode=None):
    """Отправка и обновление статусных сообщений"""
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
    """Получение размеров видео через ffprobe"""
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

def get_scenarios_menu(user_id):
    """Создание меню сценариев"""
    scenarios = get_scenarios(user_id)
    markup = types.InlineKeyboardMarkup()
    for s_id, name, platform, content_type, fmt in scenarios:
        markup.row(types.InlineKeyboardButton(
            f"🎭 {name}",
            callback_data=f"select_scenario_{s_id}"
        ))
    markup.row(types.InlineKeyboardButton("➕ Создать сценарий", callback_data="create_scenario"))
    markup.row(types.InlineKeyboardButton("🗑 Удалить сценарий", callback_data="delete_scenario"))
    markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
    return markup

def get_api_keys_menu(user_id):
    """Создание меню API-ключей"""
    keys = get_api_keys(user_id)
    markup = types.InlineKeyboardMarkup()
    for k_id, name, platform in keys:
        markup.row(types.InlineKeyboardButton(
            f"🔑 {name} ({platform})",
            callback_data=f"view_key_{k_id}"
        ))
    markup.row(types.InlineKeyboardButton("➕ Добавить ключ", callback_data="add_api_key"))
    markup.row(types.InlineKeyboardButton("🗑 Удалить ключ", callback_data="delete_api_key"))
    markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
    return markup

def get_settings_ui(user_id):
    """Создание UI настроек"""
    settings = get_settings(user_id)
    markup = types.InlineKeyboardMarkup()
    
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

@bot.message_handler(commands=['start'])
async def start(message):
    """Обработка команды /start"""
    if message.from_user.is_bot:
        return
    user_id = message.from_user.id
    user_states[user_id] = None
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🎬 Обработать видео")
    markup.add("🎭 Сценарии", "🔑 API-ключи")
    markup.add("⚙️ Настройки")
    await bot.send_message(
        user_id,
        "👋 Привет! Я бот для обработки видео.\n\n"
        "Отправь ссылку — я удалю паузы, создам транскрибацию "
        "и проверю на соответствие политике YouTube!",
        reply_markup=markup
    )

@bot.message_handler(commands=['settings'])
async def settings_command(message):
    """Обработка команды /settings"""
    if message.from_user.is_bot:
        return
    user_id = message.from_user.id
    text, markup = get_settings_ui(user_id)
    await bot.send_message(user_id, text, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text == "🎭 Сценарии")
async def scenarios_menu(message):
    """Обработка кнопки Сценарии"""
    user_id = message.from_user.id
    markup = get_scenarios_menu(user_id)
    await bot.send_message(user_id, "🎭 Управление сценариями:", reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text == "🔑 API-ключи")
async def api_keys_menu(message):
    """Обработка кнопки API-ключи"""
    user_id = message.from_user.id
    markup = get_api_keys_menu(user_id)
    await bot.send_message(user_id, "🔑 Управление API-ключами:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
async def back_to_main(call):
    """Возврат в главное меню"""
    user_id = call.from_user.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🎬 Обработать видео")
    markup.add("🎭 Сценарии", "🔑 API-ключи")
    markup.add("⚙️ Настройки")
    await bot.send_message(user_id, "Главное меню:", reply_markup=markup)
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "create_scenario")
async def start_create_scenario(call):
    """Начало создания сценария"""
    user_id = call.from_user.id
    user_states[user_id] = "waiting_scenario_name"
    await bot.send_message(user_id, "✏️ Введите название сценария:")
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("select_scenario_"))
async def select_scenario_for_publish(call):
    """Выбор сценария для публикации"""
    user_id = call.from_user.id
    scenario_id = int(call.data.split("_")[-1])
    scenario = get_scenario_by_id(scenario_id, user_id)
    if scenario:
        user_states[user_id] = f"publish_with_{scenario_id}"
        await bot.send_message(
            user_id,
            f"✅ Выбран сценарий: *{scenario['name']}*\n"
            f"Платформа: {scenario['platform']}\n"
            f"Тип: {scenario['content_type']}\n"
            f"Формат: {scenario['format']}\n\n"
            "Теперь отправьте видео для публикации.",
            parse_mode="Markdown"
        )
    else:
        await bot.send_message(user_id, "❌ Сценарий не найден.")
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "delete_scenario")
async def delete_scenario_start(call):
    """Начало удаления сценария"""
    user_id = call.from_user.id
    scenarios = get_scenarios(user_id)
    if not scenarios:
        await bot.send_message(user_id, "Нет сценариев для удаления.")
        return
    markup = types.InlineKeyboardMarkup()
    for s_id, name, _, _, _ in scenarios:
        markup.row(types.InlineKeyboardButton(name, callback_data=f"confirm_del_scenario_{s_id}"))
    markup.row(types.InlineKeyboardButton("Отмена", callback_data="back_to_main"))
    await bot.send_message(user_id, "Выберите сценарий для удаления:", reply_markup=markup)
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_del_scenario_"))
async def confirm_delete_scenario(call):
    """Подтверждение удаления сценария"""
    user_id = call.from_user.id
    s_id = int(call.data.split("_")[-1])
    delete_scenario(s_id, user_id)
    await bot.send_message(user_id, "🗑 Сценарий удалён.")
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "add_api_key")
async def start_add_api_key(call):
    """Начало добавления API-ключа"""
    user_id = call.from_user.id
    user_states[user_id] = "waiting_api_key_name"
    await bot.send_message(user_id, "✏️ Введите название ключа (например: 'Мой YouTube канал'):")
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "delete_api_key")
async def delete_api_key_start(call):
    """Начало удаления API-ключа"""
    user_id = call.from_user.id
    keys = get_api_keys(user_id)
    if not keys:
        await bot.send_message(user_id, "Нет ключей для удаления.")
        return
    markup = types.InlineKeyboardMarkup()
    for k_id, name, _ in keys:
        markup.row(types.InlineKeyboardButton(name, callback_data=f"confirm_del_key_{k_id}"))
    markup.row(types.InlineKeyboardButton("Отмена", callback_data="back_to_main"))
    await bot.send_message(user_id, "Выберите ключ для удаления:", reply_markup=markup)
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_del_key_"))
async def confirm_delete_key(call):
    """Подтверждение удаления API-ключа"""
    user_id = call.from_user.id
    k_id = int(call.data.split("_")[-1])
    delete_api_key(k_id, user_id)
    await bot.send_message(user_id, "🗑 Ключ удалён.")
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("scen_platform_"))
async def select_scenario_platform(call):
    """Выбор платформы для сценария"""
    user_id = call.from_user.id
    platform = call.data.split("_")[-1]
    if isinstance(user_states[user_id], tuple) and len(user_states[user_id]) >= 2:
        name = user_states[user_id][1]
    else:
        name = ""
    user_states[user_id] = ("waiting_scenario_content_type", name, platform)
    
    content_types = []
    if platform == "youtube":
        content_types = ["shorts", "video"]
    elif platform == "vk":
        content_types = ["clip"]
    else:
        content_types = ["post", "video"]
    
    markup = types.InlineKeyboardMarkup()
    for ct in content_types:
        markup.row(types.InlineKeyboardButton(ct, callback_data=f"scen_ct_{ct}"))
    await bot.send_message(user_id, "Выберите тип контента:", reply_markup=markup)
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("scen_ct_"))
async def select_scenario_content_type(call):
    """Выбор типа контента для сценария"""
    user_id = call.from_user.id
    content_type = call.data.split("_")[-1]
    if isinstance(user_states[user_id], tuple) and len(user_states[user_id]) >= 3:
        name = user_states[user_id][1]
        platform = user_states[user_id][2]
    else:
        name = ""
        platform = ""
    user_states[user_id] = ("waiting_scenario_format", name, platform, content_type)
    
    formats = ["warming", "neutral", "selling", "custom"]
    markup = types.InlineKeyboardMarkup()
    for fmt in formats:
        markup.row(types.InlineKeyboardButton(fmt, callback_data=f"scen_fmt_{fmt}"))
    await bot.send_message(user_id, "Выберите формат:", reply_markup=markup)
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("scen_fmt_"))
async def select_scenario_format(call):
    """Выбор формата для сценария"""
    user_id = call.from_user.id
    fmt = call.data.split("_")[-1]
    if isinstance(user_states[user_id], tuple) and len(user_states[user_id]) >= 4:
        name = user_states[user_id][1]
        platform = user_states[user_id][2]
        content_type = user_states[user_id][3]
        add_scenario(user_id, name, platform, content_type, fmt)
        await bot.send_message(user_id, "✅ Сценарий сохранён!")
    else:
        await bot.send_message(user_id, "❌ Ошибка: данные сценария повреждены")
    user_states[user_id] = None
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("key_platform_") and call.data != "key_platform_youtube")
async def select_api_key_platform(call):
    """Выбор платформы для API-ключа (кроме YouTube)"""
    user_id = call.from_user.id
    platform = call.data.split("_")[-1]
    if isinstance(user_states[user_id], tuple) and len(user_states[user_id]) >= 2:
        name = user_states[user_id][1]
    else:
        name = ""
    user_states[str(user_id) + "_key_meta"] = (name, platform)
    user_states[user_id] = "waiting_api_key_value"
    await bot.send_message(user_id, "🔑 Введите API-ключ (токен):")
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "key_platform_youtube")
async def handle_youtube_key(call):
    """Обработка выбора платформы YouTube для API-ключа"""
    user_id = call.from_user.id
    if isinstance(user_states[user_id], tuple) and len(user_states[user_id]) >= 2:
        name = user_states[user_id][1]
    else:
        name = ""
    await bot.send_message(
        user_id,
        "📌 Для YouTube требуется JSON с данными OAuth2.\n"
        "Пришлите файл credentials.json или вставьте содержимое JSON."
    )
    user_states[user_id] = "waiting_youtube_json"
    user_states[str(user_id) + "_key_meta"] = (name, "youtube")
    await bot.answer_callback_query(call.id)

@bot.message_handler(content_types=['document'], func=lambda msg: user_states.get(msg.from_user.id) == "waiting_youtube_json")
async def handle_youtube_json_file(message):
    """Обработка JSON-файла для YouTube"""
    user_id = message.from_user.id
    if not message.document.file_name.endswith('.json'):
        await bot.send_message(user_id, "Пожалуйста, отправьте JSON-файл.")
        return
    
    try:
        file_info = await bot.get_file(message.document.file_id)
        downloaded = await bot.download_file(file_info.file_path)
        json_content = downloaded.decode('utf-8')
        json.loads(json_content)
        
        meta_key = str(user_id) + "_key_meta"
        if meta_key in user_states:
            name, platform = user_states[meta_key]
            save_yt_creds(user_id, json_content)
            add_api_key(user_id, name, platform, "oauth2_refresh_token_saved")
            await bot.send_message(user_id, "✅ YouTube ключ сохранён!")
            user_states[user_id] = None
            user_states.pop(meta_key, None)
    except Exception as e:
        await bot.send_message(user_id, f"❌ Ошибка: {e}")

@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id) == "waiting_youtube_json")
async def handle_youtube_json_text(message):
    """Обработка текстового JSON для YouTube"""
    user_id = message.from_user.id
    try:
        json_content = message.text
        json.loads(json_content)
        meta_key = str(user_id) + "_key_meta"
        if meta_key in user_states:
            name, platform = user_states[meta_key]
            save_yt_creds(user_id, json_content)
            add_api_key(user_id, name, platform, "oauth2_refresh_token_saved")
            await bot.send_message(user_id, "✅ YouTube ключ сохранён!")
            user_states[user_id] = None
            user_states.pop(meta_key, None)
    except Exception as e:
        await bot.send_message(user_id, f"❌ Неверный JSON: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_platform_'))
async def callback_platform(call):
    """Обработка выбора платформы в настройках"""
    user_id = call.from_user.id
    action = call.data.split('_')[2]
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
    """Обработка выбора формата в настройках"""
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
    """Обработка установки кастомного промта"""
    user_id = call.from_user.id
    user_states[user_id] = "waiting_prompt"
    await bot.send_message(user_id, "✍️ Напишите инструкцию для генерации текста...")
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'clear_custom_prompt')
async def callback_clear_prompt(call):
    """Обработка очистки кастомного промта"""
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
    """Обработка текстовых сообщений"""
    if message.from_user.is_bot:
        return
    user_id = message.from_user.id
    text = message.text.strip()
    state = user_states.get(user_id)

    if state == "waiting_scenario_name":
        user_states[user_id] = ("waiting_scenario_platform", text)
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("YouTube", callback_data="scen_platform_youtube"),
            types.InlineKeyboardButton("VK", callback_data="scen_platform_vk")
        )
        markup.row(types.InlineKeyboardButton("Telegram", callback_data="scen_platform_telegram"))
        await bot.send_message(user_id, "Выберите платформу:", reply_markup=markup)
        return

    elif state == "waiting_api_key_name":
        user_states[user_id] = ("waiting_api_key_platform", text)
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("YouTube", callback_data="key_platform_youtube"),
            types.InlineKeyboardButton("VK", callback_data="key_platform_vk")
        )
        markup.row(types.InlineKeyboardButton("Telegram", callback_data="key_platform_telegram"))
        await bot.send_message(user_id, "Выберите платформу:", reply_markup=markup)
        return

    elif state == "waiting_api_key_value":
        meta_key = str(user_id) + "_key_meta"
        if meta_key in user_states:
            name, platform = user_states[meta_key]
            add_api_key(user_id, name, platform, text)
            await bot.send_message(user_id, "✅ Ключ сохранён!")
            user_states[user_id] = None
            user_states.pop(meta_key, None)
        return

    elif state == "waiting_prompt":
        update_settings(user_id, custom_prompt=text)
        user_states[user_id] = None
        await bot.send_message(user_id, "✅ Промт сохранен!")
        await settings_command(message)
        return

    if text == "⚙️ Настройки":
        await settings_command(message)
    elif text == "🎬 Обработать видео":
        user_states[user_id] = 'waiting_for_link'
        await bot.send_message(user_id, "📎 Отправь ссылку на видео или видеофайл")
    elif state == "waiting_for_link":
        user_states[user_id] = None
        url = text.strip()
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
    """Обработка видео и документов"""
    if message.from_user.is_bot:
        return
    user_id = message.from_user.id
    
    expected_state = user_states.get(user_id)
    if expected_state not in ['waiting_for_link'] and not (isinstance(expected_state, str) and expected_state.startswith("publish_with_")):
        await bot.send_message(
            user_id,
            "📎 Сначала нажмите '🎬 Обработать видео' или выберите сценарий для публикации."
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
            await bot.send_message(user_id, "📎 Я обрабатываю только видео.")
            return
    else:
        return
    
    await send_status(user_id, "⏳ Получаю видео из Telegram...")
    
    try:
        file_info = await bot.get_file(file_id)
        save_path = os.path.join(config.UPLOAD_DIR, file_name)
        
        if config.TELEGRAM_API_URL and file_info.file_path.startswith('/'):
            local_file_path = file_info.file_path
            if os.path.exists(local_file_path):
                shutil.copy(local_file_path, save_path)
                logger.info(f"Скопирован файл из локального Bot API: {local_file_path}")
            else:
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
        logger.error(f"Ошибка скачивания видео: {e}", exc_info=True)
        await send_status(user_id, f"❌ Не удалось скачать видео: {str(e)}")

async def publish_to_draft(user_id: int, scenario: dict, result):
    """Публикация видео по сценарию"""
    platform = scenario["platform"]
    content_type = scenario["content_type"]
    
    content = result.generated_content.get(platform, {}).get("content", {})
    title = content.get("title", "Без названия")[:100]
    description = content.get("description", content.get("post", ""))[:5000]
    tags = content.get("tags", [])
    video_path = result.processed_video_path
    
    keys = [k for k in get_api_keys(user_id) if k[2] == platform]
    if not keys:
        await bot.send_message(user_id, f"❌ Нет API-ключа для {platform}. Добавьте в настройках.")
        return
    
    try:
        if platform == "youtube":
            link = await publish_to_youtube_draft(user_id, video_path, title, description, tags, content_type)
            await bot.send_message(user_id, f"✅ Видео отправлено в черновики YouTube:\n{link}")
        
        elif platform == "vk":
            access_token = get_api_key_by_id(keys[0][0], user_id)
            link = await publish_to_vk_draft(access_token, video_path, title, description, content_type)
            await bot.send_message(user_id, f"✅ Видео отправлено в черновики VK:\n{link}")
        
        elif platform == "telegram":
            channel_id = keys[0][1]
            bot_token = get_api_key_by_id(keys[0][0], user_id)
            link = await publish_to_telegram_channel(bot_token, channel_id, video_path, title, description)
            await bot.send_message(user_id, f"✅ Пост отправлен в Telegram:\n{link}")
    
    except Exception as e:
        logger.error(f"Publish error for {user_id}: {e}")
        await bot.send_message(user_id, f"❌ Ошибка публикации: {str(e)}")

async def process_video_workflow(user_id: int, url: str):
    """Основной процесс обработки видео по URL"""
    try:
        video_path = await download_video(url)
        await process_video_from_path(user_id, video_path)
    except Exception as e:
        logger.error(f"Ошибка в workflow: {e}", exc_info=True)
        raise

async def process_video_from_path(user_id: int, video_path: str):
    """Обработка видео из файла"""
    try:
        await send_status(user_id, "✅ Видео получено\n2️⃣ Обработка...")
        
        settings = get_settings(user_id)
        platforms_val = settings.get("platform", "all")
        platforms = ["youtube", "telegram"] if platforms_val == "all" else [platforms_val]
        post_format = settings.get("post_format", "neutral")
        custom_prompt = settings.get("custom_prompt")
        
        result = await orchestrator_client.process_video(
            video_path,
            platforms=platforms,
            post_format=post_format,
            custom_prompt=custom_prompt
        )
        
        if result.status == "failed":
            await send_status(user_id, f"❌ Ошибка: {result.error}")
            return
        
        await send_status(user_id, "✅ Обработка завершена!\n\n📊 Результаты:")
        
        if result.generated_content:
            youtube_data = result.generated_content.get('youtube', {})
            if youtube_data:
                policy_check = youtube_data.get('policy_check')
                if policy_check:
                    verdict = policy_check.get('verdict', 'UNKNOWN')
                    confidence = policy_check.get('confidence', 0)
                    emoji = "✅" if verdict == "ALLOW" else "❌"
                    text = "соответствует" if verdict == "ALLOW" else "НЕ соответствует"
                    await bot.send_message(
                        user_id,
                        f"{emoji} **Проверка политики:**\nВидео {text} политике YouTube\nУверенность: {confidence:.0%}",
                        parse_mode='Markdown'
                    )
                
                youtube_content = youtube_data.get('content', {})
                if youtube_content:
                    yt_title = youtube_content.get('title', '').strip('"')
                    yt_desc = youtube_content.get('description', '').strip('"')
                    yt_tags = youtube_content.get('tags', [])
                    tags_str = ' '.join(yt_tags) if yt_tags else 'Нет тегов'
                    await bot.send_message(user_id, f"🎬 YouTube:\n\n{yt_title}\n\n{yt_desc}\n\n{tags_str}")
            
            telegram_data = result.generated_content.get('telegram', {})
            if telegram_data:
                telegram_content = telegram_data.get('content', {})
                if telegram_content:
                    tg_title = telegram_content.get('title', '').strip('"')
                    tg_post = telegram_content.get('post', '').strip('"')
                    await bot.send_message(user_id, f"📱 Telegram:\n\n**{tg_title}**\n\n{tg_post}", parse_mode='Markdown')
            
            thumbnails = youtube_data.get('thumbnails', [])
            if thumbnails:
                try:
                    media_group = []
                    for i, thumb in enumerate(thumbnails[:10], 1):
                        thumb_path = thumb.get('path', '')
                        if thumb_path and os.path.exists(thumb_path):
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
        
        if result.processed_video_path:
            await send_status(user_id, "🎬 Отправляю обработанное видео...")
            try:
                width, height = get_video_dimensions(result.processed_video_path)
                with open(result.processed_video_path, 'rb') as video:
                    await bot.send_video(
                        user_id, 
                        video, 
                        caption="🎬 Видео с обрезанными паузами",
                        width=width or None,
                        height=height or None
                    )
                if user_id in user_status_messages:
                    try:
                        await bot.delete_message(user_id, user_status_messages[user_id])
                        del user_status_messages[user_id]
                    except:
                        pass
            except Exception as e:
                logger.error(f"Ошибка отправки видео: {e}")
                await bot.send_message(user_id, f"⚠️ Не удалось отправить видео: {str(e)}")
        
        publish_state = user_states.get(user_id, "")
        if publish_state.startswith("publish_with_"):
            scenario_id = int(publish_state.split("_")[-1])
            scenario = get_scenario_by_id(scenario_id, user_id)
            if scenario:
                await publish_to_draft(user_id, scenario, result)
            user_states[user_id] = None

    except Exception as e:
        logger.error(f"Ошибка в workflow: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    init_db()
    logger.info("🤖 Telegram Bot запущен")
    asyncio.run(bot.polling(none_stop=True, interval=0))