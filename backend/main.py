import asyncio
import subprocess
import json
import uuid
import os
import shutil
import sqlite3
from telebot.async_telebot import AsyncTeleBot
from telebot import types, apihelper, asyncio_helper
import re
import logging
import config
from services import OrchestratorClient
from utils import download_video
from database import (
    init_db,
    add_api_key, get_api_keys, delete_api_key, get_api_key_by_id,
    add_scenario, get_scenarios, delete_scenario, get_scenario_by_id, update_scenario,
    set_user_state, get_user_state_db, clear_user_state_db, DB_PATH
)
from publishers import (
    publish_to_youtube_draft,
    save_credentials as save_yt_creds,
    publish_to_vk_draft,
    publish_to_telegram_channel
)

# константы для русификации UI
PLATFORM_NAMES = {
    "youtube": "YouTube",
    "telegram": "Telegram",
    "vk": "ВКонтакте"
}

CONTENT_TYPE_NAMES = {
    "shorts": "Shorts",
    "video": "Видео",
    "post": "Пост",
    "clip": "Клип"
}

CONTENT_TYPES_BY_PLATFORM = {
    "youtube": ["shorts", "video"],
    "telegram": ["post", "video"],
    "vk": ["clip", "post"],
}

CONTENT_TYPE_PLATFORM_ORDER = ["youtube", "telegram", "vk"]

FORMAT_NAMES = {
    "neutral": "Нейтральный",
    "selling": "Продающий",
    "cta_subscribe": "Призыв подписаться",
    "cta_comment": "Призыв комментировать",
    "cta_engage": "Призыв лайкнуть/репостнуть",
    "warming": "Прогрев (интрига)",
    "expert": "Экспертный тон",
    "storytelling": "Сторителлинг",
    "custom": "Свой промт"
}

PIPELINE_ACTIONS = {
    "cut_silence": "✂️ Удаление пауз",
    "transcribe": "📝 Транскрибация",
    "check_policy": "🛡 Проверка политики",
    "generate_content": "✍️ Генерация контента",
    "generate_thumbnails": "🖼 Генерировать обложки",
    "publish": "🚀 Авто-публикация"
}

HELP_TEXT = """
🤖 **Справка по AI Publisher Bot**

**Как начать:**
1. Перейдите в '🎭 Сценарии' и создайте сценарий.
2. Выберите платформу, тип контента и формат.
3. Перейдите в '🔑 API-ключи' и добавьте ключи для публикации.
4. Нажмите '🎬 Обработать видео', выберите сценарий и отправьте файл.

❓ Используйте кнопки ниже для инструкций по получению API-ключей.
"""

API_HELP_YOUTUBE = """
📺 **Как получить API для YouTube**

1. Перейдите в [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте новый проект или выберите существующий
3. Включите YouTube Data API v3
4. Перейдите в "Учетные данные" → "Создать" → "OAuth"
5. Выберите тип "Приложение для ПК"
6. Скачайте файл `client_secret.json`
7. Отправьте этот файл боту при добавлении ключа
"""

API_HELP_TELEGRAM = """
📱 **Как получить API для Telegram**

1. Откройте @BotFather в Telegram
2. Отправьте команду /newbot
3. Следуйте инструкциям и получите токен бота
4. Добавьте бота в канал как администратора
5. Узнайте ID канала (через @userinfobot)
6. При добавлении ключа укажите:
   • Название: ID канала (например: -100123456789)
   • Ключ: токен бота
"""

API_HELP_VK = """
💬 **Как получить API для ВКонтакте**

1. Перейдите в [VK для разработчиков](https://vk.com/apps?act=manage)
2. Создайте новое приложение типа "Standalone"
3. В настройках сообщества включите API
4. Получите ключ доступа сообщества
5. При добавлении ключа вставьте этот токен
"""

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def _content_type_label(ct: str) -> str:
    return CONTENT_TYPE_NAMES.get(ct, ct)

def _platform_label(p: str) -> str:
    return PLATFORM_NAMES.get(p, p)

def _format_scenario_content_types(scenario: dict) -> str:
    ct = scenario.get("content_type")
    if isinstance(ct, dict):
        parts = []
        for p in CONTENT_TYPE_PLATFORM_ORDER:
            if p in ct:
                parts.append(f"{_platform_label(p)}: {_content_type_label(ct[p])}")
        for p, v in ct.items():
            if p not in CONTENT_TYPE_PLATFORM_ORDER:
                parts.append(f"{_platform_label(p)}: {_content_type_label(v)}")
        return "\n".join(parts) if parts else "Не выбран"
    return _content_type_label(ct) if ct else "Не выбран"

def _get_content_type_for_platform(scenario: dict, platform: str) -> str:
    ct = scenario.get("content_type")
    if isinstance(ct, dict):
        return (ct.get(platform) or "").strip()
    return (ct or "").strip()

async def _show_next_content_type_step(user_id: int, chat_id: int, message_id: int):
    state = get_user_state_db(user_id)
    if not (isinstance(state, (list, tuple)) and len(state) >= 6 and state[0] == "waiting_scenario_content_types"):
        return
    name = state[1]
    platforms = state[2]
    order = state[3]
    idx = int(state[4])
    selected_map = state[5] if isinstance(state[5], dict) else {}

    if idx >= len(order):
        set_user_state(user_id, ("waiting_scenario_format", name, platforms, selected_map))
        await bot.answer_callback_query("", show_alert=False)
        return

    platform = order[idx]
    allowed = CONTENT_TYPES_BY_PLATFORM.get(platform, [])
    markup = types.InlineKeyboardMarkup()
    for ct in allowed:
        markup.row(types.InlineKeyboardButton(_content_type_label(ct), callback_data=f"scen_ct_{ct}"))
    markup.row(types.InlineKeyboardButton("Отмена", callback_data="back_to_main"))

    await bot.edit_message_text(
        f"Выберите тип контента для {_platform_label(platform)}:",
        chat_id,
        message_id,
        reply_markup=markup
    )

async def _show_next_api_key_step(user_id: int, chat_id: int, message_id: int):
    state = get_user_state_db(user_id)
    if not (isinstance(state, (list, tuple)) and len(state) >= 8 and state[0] == "waiting_scenario_api_keys"):
        return
    name = state[1]
    platforms = state[2]
    content_types_map = state[3]
    fmt = state[4]
    actions = state[5]
    order = state[6]
    idx = int(state[7])
    api_keys_map = dict(state[8]) if len(state) >= 9 and isinstance(state[8], dict) else {}

    if idx >= len(order):
        ct_value = content_types_map
        if isinstance(content_types_map, dict):
            ct_value = json.dumps(content_types_map, ensure_ascii=False)
        add_scenario(user_id, name, platforms, actions, api_keys_map, ct_value, fmt)

        await bot.edit_message_text(
            f"✅ Сценарий **{name}** успешно сохранён!",
            chat_id,
            message_id,
            parse_mode="Markdown"
        )
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_main"))
        await bot.send_message(user_id, "Что желаете сделать дальше?", reply_markup=markup)
        clear_user_state_db(user_id)
        return

    platform = order[idx]
    keys = [k for k in get_api_keys(user_id) if len(k) >= 3 and k[2] == platform]

    markup = types.InlineKeyboardMarkup()
    if keys:
        for k_id, k_name, _plat in keys:
            markup.row(types.InlineKeyboardButton(f"🔑 {k_name}", callback_data=f"scen_key_{platform}_{k_id}"))
    else:
        markup.row(types.InlineKeyboardButton("➕ добавить ключ", callback_data="add_api_key"))

    markup.row(types.InlineKeyboardButton("➡️ пропустить", callback_data=f"scen_key_skip_{platform}"))
    markup.row(types.InlineKeyboardButton("отмена", callback_data="back_to_main"))

    await bot.edit_message_text(
        f"Выберите API-ключ для {_platform_label(platform)}:",
        chat_id,
        message_id,
        reply_markup=markup
    )

async def _show_edit_content_type_step(user_id: int, chat_id: int, message_id: int):
    state = get_user_state_db(user_id)
    if not (isinstance(state, (list, tuple)) and len(state) >= 6 and state[0] == "edit_scenario_content_types"):
        return
    scenario_id = int(state[1])
    platforms = state[2]
    order = state[3]
    idx = int(state[4])
    selected_map = state[5] if isinstance(state[5], dict) else {}

    if idx >= len(order):
        ct_value = json.dumps(selected_map, ensure_ascii=False) if selected_map else ""
        update_scenario(scenario_id, user_id, content_type=ct_value)

        scenario = get_scenario_by_id(scenario_id, user_id)
        if scenario:
            markup = types.InlineKeyboardMarkup()
            markup.row(types.InlineKeyboardButton("📝 Название", callback_data=f"edit_scen_field_name_{scenario_id}"))
            markup.row(types.InlineKeyboardButton("🌍 Платформы", callback_data=f"edit_scen_field_plat_{scenario_id}")) 
            markup.row(types.InlineKeyboardButton("📦 Типы контента", callback_data=f"edit_scen_field_ct_{scenario_id}"))
            markup.row(types.InlineKeyboardButton("🔑 API-ключи", callback_data=f"edit_scen_field_keys_{scenario_id}"))
            markup.row(types.InlineKeyboardButton("⚙️ Действия", callback_data=f"edit_scen_field_act_{scenario_id}"))
            markup.row(types.InlineKeyboardButton("📝 Формат", callback_data=f"edit_scen_field_fmt_{scenario_id}"))
            markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"view_scen_{scenario_id}"))

            await bot.edit_message_text(
                f"✏️ Редактирование сценария: **{scenario['name']}**\nВыберите, что хотите изменить:",
                chat_id,
                message_id,
                reply_markup=markup,
                parse_mode="Markdown"
            )

        clear_user_state_db(user_id)
        return

    platform = order[idx]
    allowed = CONTENT_TYPES_BY_PLATFORM.get(platform, [])
    current_value = selected_map.get(platform)
    
    markup = types.InlineKeyboardMarkup()
    for ct in allowed:
        label = _content_type_label(ct)
        if current_value == ct:
            label = f"✅ {label}"
        markup.row(types.InlineKeyboardButton(label, callback_data=f"edit_ct_{scenario_id}_{platform}_{ct}"))
    markup.row(types.InlineKeyboardButton("Отмена", callback_data=f"edit_scen_{scenario_id}"))

    await bot.edit_message_text(
        f"Выберите тип контента для {_platform_label(platform)}:",
        chat_id,
        message_id,
        reply_markup=markup
    )

async def _show_edit_api_key_step(user_id: int, chat_id: int, message_id: int):
    state = get_user_state_db(user_id)
    if not (isinstance(state, (list, tuple)) and len(state) >= 6 and state[0] == "edit_scenario_api_keys"):
        return
    scenario_id = int(state[1])
    platforms = state[2]
    order = state[3]
    idx = int(state[4])
    api_keys_map = dict(state[5]) if isinstance(state[5], dict) else {}

    if idx >= len(order):
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM scenario_api_keys WHERE scenario_id = ?", (scenario_id,))
            for platform, key_id in api_keys_map.items():
                cursor.execute(
                    "INSERT INTO scenario_api_keys (scenario_id, platform, api_key_id) VALUES (?, ?, ?)",
                    (scenario_id, platform, int(key_id))
                )
            conn.commit()

        scenario = get_scenario_by_id(scenario_id, user_id)
        if scenario:
            markup = types.InlineKeyboardMarkup()
            markup.row(types.InlineKeyboardButton("📝 Название", callback_data=f"edit_scen_field_name_{scenario_id}"))
            markup.row(types.InlineKeyboardButton("🌍 Платформы", callback_data=f"edit_scen_field_plat_{scenario_id}")) 
            markup.row(types.InlineKeyboardButton("📦 Типы контента", callback_data=f"edit_scen_field_ct_{scenario_id}"))
            markup.row(types.InlineKeyboardButton("🔑 API-ключи", callback_data=f"edit_scen_field_keys_{scenario_id}"))
            markup.row(types.InlineKeyboardButton("⚙️ Действия", callback_data=f"edit_scen_field_act_{scenario_id}"))
            markup.row(types.InlineKeyboardButton("📝 Формат", callback_data=f"edit_scen_field_fmt_{scenario_id}"))
            markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"view_scen_{scenario_id}"))

            await bot.edit_message_text(
                f"✏️ Редактирование сценария: **{scenario['name']}**\nВыберите, что хотите изменить:",
                chat_id,
                message_id,
                reply_markup=markup,
                parse_mode="Markdown"
            )

        clear_user_state_db(user_id)
        return

    platform = order[idx]
    keys = [k for k in get_api_keys(user_id) if len(k) >= 3 and k[2] == platform]
    current_key_id = api_keys_map.get(platform)

    markup = types.InlineKeyboardMarkup()
    if keys:
        for k_id, k_name, _plat in keys:
            label = f"🔑 {k_name}"
            if current_key_id == k_id:
                label = f"✅ {label}"
            markup.row(types.InlineKeyboardButton(label, callback_data=f"edit_key_{scenario_id}_{platform}_{k_id}"))
    else:
        markup.row(types.InlineKeyboardButton("➕ добавить ключ", callback_data="add_api_key"))

    markup.row(types.InlineKeyboardButton("➡️ пропустить", callback_data=f"edit_key_skip_{scenario_id}_{platform}"))
    markup.row(types.InlineKeyboardButton("Отмена", callback_data=f"edit_scen_{scenario_id}"))

    await bot.edit_message_text(
        f"Выберите API-ключ для {_platform_label(platform)}:",
        chat_id,
        message_id,
        reply_markup=markup
    )

if config.TELEGRAM_API_URL:
    apihelper.API_URL = config.TELEGRAM_API_URL + "/bot{0}/{1}"
    apihelper.FILE_URL = config.TELEGRAM_API_URL + "/file/bot{0}/{1}"
    asyncio_helper.API_URL = config.TELEGRAM_API_URL + "/bot{0}/{1}"
    asyncio_helper.FILE_URL = config.TELEGRAM_API_URL + "/file/bot{0}/{1}"
    logger.info(f"Используется локальный Bot API: {config.TELEGRAM_API_URL}")

bot = AsyncTeleBot(config.BOT_TOKEN)
orchestrator_client = OrchestratorClient()

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
    """Создание упрощённого меню сценариев"""
    scenarios = get_scenarios(user_id)
    markup = types.InlineKeyboardMarkup()
    for row in scenarios:
        s_id = row[0]
        name = row[1]
        markup.row(types.InlineKeyboardButton(
            f"🎭 {name}",
            callback_data=f"view_scen_{s_id}"
        ))
    markup.row(types.InlineKeyboardButton("➕ Создать сценарий", callback_data="create_scenario"))
    markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
    return markup

def get_api_keys_menu(user_id):
    """Создание меню API-ключей"""
    keys = get_api_keys(user_id)
    markup = types.InlineKeyboardMarkup()
    for k_id, name, platform in keys:
        markup.row(types.InlineKeyboardButton(
            f"🔑 {name} ({PLATFORM_NAMES.get(platform, platform)})",
            callback_data=f"view_key_{k_id}"
        ))
    markup.row(types.InlineKeyboardButton("➕ Добавить ключ", callback_data="add_api_key"))
    markup.row(types.InlineKeyboardButton("🗑 Удалить ключ", callback_data="delete_api_key"))
    markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
    return markup


def get_main_menu_keyboard():
    """Создание главного инлайн-меню"""
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("🎬 Обработать видео", callback_data="start_processing"))
    markup.row(types.InlineKeyboardButton("🎭 Сценарии", callback_data="open_scenarios"),
               types.InlineKeyboardButton("🔑 API-ключи", callback_data="open_api_keys"))
    markup.row(types.InlineKeyboardButton("ℹ️ Помощь", callback_data="open_help"))
    return markup

@bot.message_handler(commands=['help'])
async def help_command(message):
    """Справка по боту"""
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("📺 YouTube API", callback_data="api_help_youtube"))
    markup.row(types.InlineKeyboardButton("📱 Telegram API", callback_data="api_help_telegram"))
    markup.row(types.InlineKeyboardButton("💬 VK API", callback_data="api_help_vk"))
    markup.row(types.InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_main"))
    await bot.send_message(message.chat.id, HELP_TEXT, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "open_help")
async def help_callback(call):
    """Показать справку инлайн"""
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("📺 YouTube API", callback_data="api_help_youtube"))
    markup.row(types.InlineKeyboardButton("📱 Telegram API", callback_data="api_help_telegram"))
    markup.row(types.InlineKeyboardButton("💬 VK API", callback_data="api_help_vk"))
    markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
    await bot.edit_message_text(HELP_TEXT, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "api_help_youtube")
async def api_help_youtube_callback(call):
    """Инструкция по YouTube API"""
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data="open_help"))
    await bot.edit_message_text(API_HELP_YOUTUBE, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "api_help_telegram")
async def api_help_telegram_callback(call):
    """Инструкция по Telegram API"""
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data="open_help"))
    await bot.edit_message_text(API_HELP_TELEGRAM, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "api_help_vk")
async def api_help_vk_callback(call):
    """Инструкция по VK API"""
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data="open_help"))
    await bot.edit_message_text(API_HELP_VK, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    await bot.answer_callback_query(call.id)


@bot.message_handler(commands=['start'])
async def start(message):
    """Обработка команды /start"""
    if message.from_user.is_bot:
        return
    user_id = message.from_user.id
    clear_user_state_db(user_id)
    
    await bot.send_message(user_id, "⌛", reply_markup=types.ReplyKeyboardRemove())
    markup = get_main_menu_keyboard()
    await bot.send_message(
        user_id,
        "👋 Привет! Я AI Publisher Bot.\n\n"
        "Я умею:\n"
        "✂️ Удалять тишину из видео\n"
        "📝 Создавать транскрибацию и посты\n"
        "🚀 Публиковать контент в соцсети\n\n"
        "Выберите действие в меню 👇",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data == "open_scenarios")
async def scenarios_menu_callback(call):
    """Инлайн меню сценариев"""
    user_id = call.from_user.id
    markup = get_scenarios_menu(user_id)
    await bot.edit_message_text("🎭 Управление сценариями:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    await bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "open_api_keys")
async def api_keys_menu_callback(call):
    """Инлайн меню ключей"""
    user_id = call.from_user.id
    markup = get_api_keys_menu(user_id)
    await bot.edit_message_text("🔑 Управление API-ключами:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    await bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
async def back_to_main(call):
    """Возврат в главное меню (редактирование сообщения)"""
    user_id = call.from_user.id
    clear_user_state_db(user_id)
    markup = get_main_menu_keyboard()
    await bot.edit_message_text(
        "👋 Главное меню:",
        call.message.chat.id, 
        call.message.message_id, 
        reply_markup=markup
    )
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "create_scenario")
async def start_create_scenario(call):
    """Начало создания сценария"""
    user_id = call.from_user.id
    set_user_state(user_id, "waiting_scenario_name")
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("Отмена", callback_data="cancel_create_scenario"))
    await bot.send_message(user_id, "✏️ Введите название сценария:", reply_markup=markup)
    await bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "cancel_create_scenario")
async def cancel_create_scenario(call):
    """Отмена создания сценария"""
    user_id = call.from_user.id
    clear_user_state_db(user_id)
    markup = get_main_menu_keyboard()
    try:
        await bot.edit_message_text("👋 Главное меню:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception as e:
        logger.error(f"Ошибка отмены создания сценария: {e}")
        await bot.answer_callback_query(call.id, "Ошибка отмены")
        await bot.send_message(user_id, "👋 Главное меню:", reply_markup=markup)
    await bot.answer_callback_query(call.id, "Отменено")


@bot.callback_query_handler(func=lambda call: call.data.startswith('view_scen_'))
async def view_scenario_detail(call):
    """Детальный просмотр сценария"""
    user_id = call.from_user.id
    try:
        scenario_id = int(call.data.split('_')[-1])
        scenario = get_scenario_by_id(scenario_id, user_id)
        if not scenario:
            await bot.answer_callback_query(call.id, "Сценарий не найден", show_alert=True)
            return
            
        action_names = [PIPELINE_ACTIONS.get(a, a) for a in scenario.get("pipeline_actions", [])]
        actions_str = "\n".join([f"• {name}" for name in action_names]) if action_names else "Не выбраны"
             
        platforms_list = ", ".join([PLATFORM_NAMES.get(p, p) for p in scenario.get("platforms", [])])
        content_type_str = _format_scenario_content_types(scenario)
        format_str = FORMAT_NAMES.get(scenario.get("format"), scenario.get("format"))

        api_keys_map = scenario.get("api_keys_map", {}) or {}
        key_lines = []
        for p in scenario.get("platforms", []):
            key_id = api_keys_map.get(p)
            if not key_id:
                key_lines.append(f"• {_platform_label(p)}: не выбран")
                continue
            try:
                key_data = get_api_key_by_id(key_id, user_id, raw=True)
                key_name = key_data.get("name") if isinstance(key_data, dict) else None
                key_lines.append(f"• {_platform_label(p)}: {key_name or 'неизвестно'}")
            except Exception:
                key_lines.append(f"• {_platform_label(p)}: не найден")
        keys_str = "\n".join(key_lines) if key_lines else "Не выбраны"
        
        text = (
            f"🎭 **Сценарий: {scenario['name']}**\n\n"
            f"📺 **Платформы:** {platforms_list if platforms_list else 'Не выбраны'}\n"
            f"📦 **Тип контента:**\n{content_type_str}\n"
            f"🎨 **Формат поста:** {format_str}\n"
            f"🔑 **Ключи для публикации:**\n{keys_str}\n\n"
            f"⚙️ **Действия пайплайна:**\n{actions_str}"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("▶️ Использовать", callback_data=f"select_scen_process_{scenario_id}"))
        markup.row(types.InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_scen_{scenario_id}"))
        markup.row(types.InlineKeyboardButton("🗑 Удалить", callback_data=f"confirm_del_scen_{scenario_id}"))
        markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data="open_scenarios"))
        
        await bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
        await bot.answer_callback_query(call.id)
        
    except Exception as e:
        logger.error(f"Ошибка просмотра сценария: {e}")
        await bot.answer_callback_query(call.id, "Ошибка просмотра сценария")


@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_scen_') and not call.data.startswith('edit_scen_field_') and not call.data.startswith('set_scen_'))
async def edit_scenario_menu(call):
    """Меню редактирования сценария (выбор поля)"""
    user_id = call.from_user.id
    try:
        scenario_id = int(call.data.split('_')[-1])
        scenario = get_scenario_by_id(scenario_id, user_id)
        if not scenario:
            await bot.answer_callback_query(call.id, "Сценарий не найден", show_alert=True)
            return

        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("📝 Название", callback_data=f"edit_scen_field_name_{scenario_id}"))
        markup.row(types.InlineKeyboardButton("🌍 Платформы", callback_data=f"edit_scen_field_plat_{scenario_id}")) 
        markup.row(types.InlineKeyboardButton("📦 Типы контента", callback_data=f"edit_scen_field_ct_{scenario_id}"))
        markup.row(types.InlineKeyboardButton("🔑 API-ключи", callback_data=f"edit_scen_field_keys_{scenario_id}"))
        markup.row(types.InlineKeyboardButton("⚙️ Действия", callback_data=f"edit_scen_field_act_{scenario_id}"))
        markup.row(types.InlineKeyboardButton("📝 Формат", callback_data=f"edit_scen_field_fmt_{scenario_id}"))
        markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"view_scen_{scenario_id}"))
        
        await bot.edit_message_text(f"✏️ Редактирование сценария: **{scenario['name']}**\nВыберите, что хотите изменить:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
        await bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка меню редактирования: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_scen_field_'))
async def edit_scenario_field_start(call):
    """Начало редактирования конкретного поля"""
    user_id = call.from_user.id
    try:
        parts = call.data.split('_')
        field = parts[3]
        scenario_id = int(parts[4])
        
        if field == "name":
            set_user_state(user_id, f"waiting_new_name_{scenario_id}")
            markup = types.InlineKeyboardMarkup()
            markup.row(types.InlineKeyboardButton("Отмена", callback_data=f"edit_scen_{scenario_id}"))
            await bot.send_message(user_id, "Введите новое название сценария:", reply_markup=markup)
            
        elif field == "fmt":
            markup = types.InlineKeyboardMarkup()
            formats = ["warming", "neutral", "selling", "custom"]
            for f in formats:
                label = FORMAT_NAMES.get(f, f)
                markup.row(types.InlineKeyboardButton(label, callback_data=f"set_scen_fmt_{scenario_id}_{f}"))
            markup.row(types.InlineKeyboardButton("Отмена", callback_data=f"edit_scen_{scenario_id}"))
            await bot.edit_message_text("Выберите новый формат:", call.message.chat.id, call.message.message_id, reply_markup=markup)

        elif field == "act":
            scenario = get_scenario_by_id(scenario_id, user_id)
            selected_actions = scenario.get("pipeline_actions", [])
            
            markup = types.InlineKeyboardMarkup()
            for key, label in PIPELINE_ACTIONS.items():
                is_selected = key in selected_actions
                btn_label = f"{'✅' if is_selected else '❌'} {label}"
                markup.row(types.InlineKeyboardButton(btn_label, callback_data=f"edit_toggle_act_{scenario_id}_{key}"))
            
            markup.row(types.InlineKeyboardButton("ГОТОВО", callback_data=f"edit_scen_{scenario_id}"))
            await bot.edit_message_text("Настройте действия пайплайна:", call.message.chat.id, call.message.message_id, reply_markup=markup)
             
        elif field == "plat":
            scenario = get_scenario_by_id(scenario_id, user_id)
            selected_platforms = scenario.get("platforms", [])
             
            markup = types.InlineKeyboardMarkup()
            for p_key, p_name in PLATFORM_NAMES.items():
                is_selected = p_key in selected_platforms
                btn_label = f"{'✅' if is_selected else '❌'} {p_name}"
                markup.row(types.InlineKeyboardButton(btn_label, callback_data=f"edit_toggle_plat_{scenario_id}_{p_key}"))
             
            markup.row(types.InlineKeyboardButton("ГОТОВО", callback_data=f"edit_scen_{scenario_id}"))
            await bot.edit_message_text("Выберите площадки для публикации:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        
        elif field == "ct":
            scenario = get_scenario_by_id(scenario_id, user_id)
            platforms = scenario.get("platforms", [])
            if not platforms:
                await bot.answer_callback_query(call.id, "Сначала выберите платформы", show_alert=True)
                return
            
            current_ct = scenario.get("content_type", "")
            if isinstance(current_ct, str) and current_ct:
                try:
                    current_ct_map = json.loads(current_ct) if current_ct.startswith("{") else {}
                except:
                    current_ct_map = {}
            else:
                current_ct_map = current_ct if isinstance(current_ct, dict) else {}
            
            order = [p for p in CONTENT_TYPE_PLATFORM_ORDER if p in platforms]
            set_user_state(user_id, ("edit_scenario_content_types", scenario_id, platforms, order, 0, current_ct_map))
            await _show_edit_content_type_step(user_id, call.message.chat.id, call.message.message_id)
        
        elif field == "keys":
            scenario = get_scenario_by_id(scenario_id, user_id)
            platforms = scenario.get("platforms", [])
            if not platforms:
                await bot.answer_callback_query(call.id, "Сначала выберите платформы", show_alert=True)
                return
            
            current_keys_map = scenario.get("api_keys_map", {}) or {}
            order = [p for p in CONTENT_TYPE_PLATFORM_ORDER if p in platforms]
            set_user_state(user_id, ("edit_scenario_api_keys", scenario_id, platforms, order, 0, current_keys_map))
            await _show_edit_api_key_step(user_id, call.message.chat.id, call.message.message_id)
        
        await bot.answer_callback_query(call.id)
    except Exception as e:
         logger.error(f"Ошибка начала редактирования поля: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_scen_'))
async def set_scenario_field_value(call):
    """Сохранение выбранного значения поля (формат, действие, платформа)"""
    user_id = call.from_user.id
    try:
        parts = call.data.split('_')
        field_type = parts[2]
        scenario_id = int(parts[3])
        value = "_".join(parts[4:])
        
        if field_type == "fmt":
            update_scenario(scenario_id, user_id, format=value)
            
        await bot.answer_callback_query(call.id, "✅ Изменения сохранены")
        call.data = f"edit_scen_{scenario_id}"
        await edit_scenario_menu(call)
        
    except Exception as e:
        logger.error(f"Ошибка установки значения поля: {e}")

@bot.message_handler(func=lambda msg: isinstance(get_user_state_db(msg.from_user.id), str) and get_user_state_db(msg.from_user.id).startswith("waiting_new_name_"))
async def save_new_scenario_name(message):
    """Сохранение нового названия сценария"""
    user_id = message.from_user.id
    state = get_user_state_db(user_id)
    scenario_id = int(state.split("_")[-1])
    new_name = message.text.strip()
    
    update_scenario(scenario_id, user_id, name=new_name)
    clear_user_state_db(user_id)
    
    await bot.send_message(user_id, f"✅ Сценарий переименован в **{new_name}**", parse_mode="Markdown")
    
    markup = get_scenarios_menu(user_id)
    await bot.send_message(user_id, "🎭 Управление сценариями:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_toggle_act_'))
async def toggle_edit_scenario_action(call):
    """Переключение действия при редактировании существующего сценария"""
    user_id = call.from_user.id
    try:
        parts = call.data.split('_')
        scenario_id = int(parts[3])
        action_key = "_".join(parts[4:])
        
        scenario = get_scenario_by_id(scenario_id, user_id)
        if not scenario:
            await bot.answer_callback_query(call.id, "Сценарий не найден")
            return
            
        actions = scenario.get("pipeline_actions", [])[:]
        if action_key in actions:
            actions.remove(action_key)
        else:
            actions.append(action_key)
            
        update_scenario(scenario_id, user_id, pipeline_actions=actions)
        
        markup = types.InlineKeyboardMarkup()
        for key, label in PIPELINE_ACTIONS.items():
            is_selected = key in actions
            btn_label = f"{'✅' if is_selected else '❌'} {label}"
            markup.row(types.InlineKeyboardButton(btn_label, callback_data=f"edit_toggle_act_{scenario_id}_{key}"))
        markup.row(types.InlineKeyboardButton("ГОТОВО", callback_data=f"edit_scen_{scenario_id}"))

        await bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
        await bot.answer_callback_query(call.id, f"Действие {'добавлено' if action_key in actions else 'удалено'}")
        
    except Exception as e:
        logger.error(f"Ошибка переключения действия: {e}")
        await bot.answer_callback_query(call.id, "Ошибка переключения")

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_toggle_plat_'))
async def toggle_edit_scenario_platform(call):
    """Переключение площадки при редактировании существующего сценария"""
    user_id = call.from_user.id
    try:
        parts = call.data.split('_')
        scenario_id = int(parts[3])
        platform_key = parts[4]
        
        scenario = get_scenario_by_id(scenario_id, user_id)
        if not scenario:
            await bot.answer_callback_query(call.id, "Сценарий не найден")
            return
            
        platforms = scenario.get("platforms", [])[:]
        if not isinstance(platforms, list):
            platforms = [platforms] if platforms else []
            
        if platform_key in platforms:
            platforms.remove(platform_key)
        else:
            platforms.append(platform_key)
            
        update_scenario(scenario_id, user_id, platforms=platforms)
        
        markup = types.InlineKeyboardMarkup()
        for p_key, p_name in PLATFORM_NAMES.items():
            is_selected = p_key in platforms
            btn_label = f"{'✅' if is_selected else '❌'} {p_name}"
            markup.row(types.InlineKeyboardButton(btn_label, callback_data=f"edit_toggle_plat_{scenario_id}_{p_key}"))
        
        markup.row(types.InlineKeyboardButton("ГОТОВО", callback_data=f"edit_scen_{scenario_id}"))
        
        await bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
        await bot.answer_callback_query(call.id, f"Площадка {'добавлена' if platform_key in platforms else 'удалена'}")
        
    except Exception as e:
        logger.error(f"Ошибка переключения платформы: {e}")
        await bot.answer_callback_query(call.id, "Ошибка переключения")

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_del_scen_'))
async def confirm_delete_scenario_detail(call):
    """Подтверждение удаления сценария"""
    try:
        scenario_id = int(call.data.split('_')[-1])
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("🗑 Да, удалить", callback_data=f"del_scen_{scenario_id}"),
            types.InlineKeyboardButton("Отмена", callback_data=f"view_scen_{scenario_id}")
        )
        await bot.edit_message_text("❓ Вы уверены, что хотите удалить этот сценарий?", call.message.chat.id, call.message.message_id, reply_markup=markup)
        await bot.answer_callback_query(call.id)
        
    except Exception as e:
        logger.error(f"Ошибка подтверждения удаления: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('del_scen_'))
async def delete_scenario_handler(call):
    """Удаление сценария"""
    user_id = call.from_user.id
    try:
        scenario_id = int(call.data.split('_')[-1])
        delete_scenario(scenario_id, user_id)
        await bot.answer_callback_query(call.id, "✅ Сценарий удален")
        markup = get_scenarios_menu(user_id)
        await bot.edit_message_text("🎭 Управление сценариями:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception as e:
        logger.error(f"Ошибка удаления сценария: {e}")
        await bot.answer_callback_query(call.id, "Ошибка удаления")



@bot.callback_query_handler(func=lambda call: call.data == "add_api_key")
async def start_add_api_key(call):
    """Начало добавления API-ключа"""
    user_id = call.from_user.id
    set_user_state(user_id, "waiting_api_key_name")
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("Отмена", callback_data="back_to_main"))
    await bot.send_message(user_id, "✏️ Введите название ключа (например: 'Мой YouTube канал'):", reply_markup=markup)
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

@bot.callback_query_handler(func=lambda call: call.data.startswith("view_key_"))
async def view_api_key_detail(call):
    """Просмотр деталей API-ключа"""
    user_id = call.from_user.id
    try:
        key_id = int(call.data.split("_")[-1])
        key_data = get_api_key_by_id(key_id, user_id, raw=True)
        if not key_data:
            await bot.answer_callback_query(call.id, "Ключ не найден", show_alert=True)
            return
        
        platform_name = PLATFORM_NAMES.get(key_data['platform'], key_data['platform'])
        text = (
            f"🔑 **{key_data['name']}**\n\n"
            f"📺 **Платформа:** {platform_name}\n"
            f"🔐 **Ключ:** `{key_data['key'][:20]}...` (скрыт)"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🗑 Удалить", callback_data=f"confirm_del_key_{key_id}"))
        markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data="open_api_keys"))
        
        await bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
        await bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка просмотра ключа: {e}")
        await bot.answer_callback_query(call.id, "Ошибка просмотра ключа")

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_del_key_"))
async def confirm_delete_key(call):
    """Подтверждение удаления API-ключа"""
    user_id = call.from_user.id
    k_id = int(call.data.split("_")[-1])
    delete_api_key(k_id, user_id)
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_main"))
    await bot.send_message(user_id, "🗑 Ключ удалён.", reply_markup=markup)
    await bot.answer_callback_query(call.id)

async def show_platforms_selection(user_id, message_id=None):
    """Показать меню выбора нескольких платформ"""
    state_data = get_user_state_db(user_id)
    if not (isinstance(state_data, (list, tuple)) and state_data[0] == "waiting_scenario_platforms"):
        return

    name = state_data[1]
    selected_platforms = state_data[2]

    markup = types.InlineKeyboardMarkup()
    for p_key, p_name in PLATFORM_NAMES.items():
        is_selected = p_key in selected_platforms
        btn_label = f"{'✅' if is_selected else '❌'} {p_name}"
        markup.row(types.InlineKeyboardButton(btn_label, callback_data=f"scen_toggle_plate_{p_key}"))

    markup.row(types.InlineKeyboardButton("➡️ Продолжить", callback_data="scen_platforms_done"))
    markup.row(types.InlineKeyboardButton("Отмена", callback_data="back_to_main"))

    text = f"⚙️ Сценарий: **{name}**\n\nВыберите площадки для публикации (можно несколько):"
    
    if message_id:
        try:
            await bot.edit_message_text(text, user_id, message_id, reply_markup=markup, parse_mode="Markdown")
        except Exception as e:
             logger.debug(f"Ошибка редактирования сообщения: {e}")
             await bot.send_message(user_id, text, reply_markup=markup, parse_mode="Markdown")
    else:
        await bot.send_message(user_id, text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("scen_toggle_plate_"))
async def toggle_scenario_platform(call):
    """Переключение площадки в списке"""
    user_id = call.from_user.id
    platform = call.data.split("_")[-1]
    state_data = get_user_state_db(user_id)

    if isinstance(state_data, (list, tuple)) and state_data[0] == "waiting_scenario_platforms":
        name = state_data[1]
        selected = list(state_data[2])
        if platform in selected:
            selected.remove(platform)
        else:
            selected.append(platform)
        
        set_user_state(user_id, ("waiting_scenario_platforms", name, selected))
        await show_platforms_selection(user_id, call.message.message_id)
    
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "scen_platforms_done")
async def finalize_platforms_selection(call):
    """Завершение выбора платформ и переход к типу контента"""
    user_id = call.from_user.id
    state_data = get_user_state_db(user_id)

    if not (isinstance(state_data, (list, tuple)) and state_data[0] == "waiting_scenario_platforms"):
        await bot.answer_callback_query(call.id, "Ошибка сессии", show_alert=True)
        return

    name = state_data[1]
    platforms = state_data[2]

    if not platforms:
        await bot.answer_callback_query(call.id, "Выберите хотя бы одну платформу!", show_alert=True)
        return

    order = [p for p in CONTENT_TYPE_PLATFORM_ORDER if p in platforms]
    set_user_state(user_id, ("waiting_scenario_content_types", name, platforms, order, 0, {}))
    await _show_next_content_type_step(user_id, call.message.chat.id, call.message.message_id)
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("scen_ct_"))
async def select_scenario_content_type(call):
    """Выбор типа контента для сценария"""
    user_id = call.from_user.id
    content_type = call.data.split("_")[-1]
    state = get_user_state_db(user_id)

    if isinstance(state, (list, tuple)) and len(state) >= 6 and state[0] == "waiting_scenario_content_types":
        name = state[1]
        platforms = state[2]
        order = state[3]
        idx = int(state[4])
        selected_map = dict(state[5]) if isinstance(state[5], dict) else {}

        if idx < len(order):
            platform = order[idx]
            allowed = CONTENT_TYPES_BY_PLATFORM.get(platform, [])
            if content_type not in allowed:
                await bot.answer_callback_query(call.id, "Недопустимый тип контента для этой платформы", show_alert=True)
                return
            selected_map[platform] = content_type

        idx += 1
        if idx < len(order):
            set_user_state(user_id, ("waiting_scenario_content_types", name, platforms, order, idx, selected_map))
            await _show_next_content_type_step(user_id, call.message.chat.id, call.message.message_id)
            await bot.answer_callback_query(call.id)
            return

        set_user_state(user_id, ("waiting_scenario_format", name, platforms, selected_map))

    elif isinstance(state, (list, tuple)) and len(state) >= 3:
        name = state[1]
        platforms = state[2]
        set_user_state(user_id, ("waiting_scenario_format", name, platforms, content_type))
    else:
        set_user_state(user_id, ("waiting_scenario_format", "", [], content_type))

    formats = ["warming", "neutral", "selling", "custom"]
    markup = types.InlineKeyboardMarkup()
    for fmt in formats:
        label = FORMAT_NAMES.get(fmt, fmt)
        markup.row(types.InlineKeyboardButton(label, callback_data=f"scen_fmt_{fmt}"))
    await bot.edit_message_text("Выберите формат:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("scen_fmt_"))
async def select_scenario_format(call):
    """Выбор формата и переход к выбору действий"""
    user_id = call.from_user.id
    fmt = call.data.split("_")[-1]
    
    state = get_user_state_db(user_id)
    if isinstance(state, (list, tuple)) and len(state) >= 4:
        prev_state = state
        initial_actions = ["transcribe", "generate_content"]
        set_user_state(user_id, ("waiting_scenario_actions", prev_state[1], prev_state[2], prev_state[3], fmt, initial_actions))
        
        await show_actions_selection(user_id, call.message.message_id)
    else:
        await bot.send_message(user_id, "❌ Ошибка: данные сценария повреждены")
        clear_user_state_db(user_id)
    
    await bot.answer_callback_query(call.id)

async def show_actions_selection(user_id, message_id=None):
    """Показать меню выбора действий с галочками"""
    state_data = get_user_state_db(user_id)
    if not (isinstance(state_data, (list, tuple)) and len(state_data) >= 6):
        return
    selected_actions = state_data[5]
    
    markup = types.InlineKeyboardMarkup()
    for key, label in PIPELINE_ACTIONS.items():
        is_selected = key in selected_actions
        btn_label = f"{'✅' if is_selected else '❌'} {label}"
        markup.row(types.InlineKeyboardButton(btn_label, callback_data=f"scen_toggle_act_{key}"))
    
    markup.row(types.InlineKeyboardButton("ГОТОВО (СОХРАНИТЬ)", callback_data="scen_save_actions"))
    markup.row(types.InlineKeyboardButton("Отмена", callback_data="back_to_main"))
    
    text = "Выберите необходимые действия для пайплайна:"
    if message_id:
        try:
            await bot.edit_message_text(text, user_id, message_id, reply_markup=markup)
        except Exception:
            await bot.send_message(user_id, text, reply_markup=markup)
    else:
        await bot.send_message(user_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("scen_toggle_act_"))
async def toggle_scenario_action(call):
    """Переключение действия в списке выбора"""
    user_id = call.from_user.id
    parts = call.data.split("_")
    action_key = "_".join(parts[3:]) # scen (0), toggle (1), act (2), action_key (3+)
    
    state = get_user_state_db(user_id)
    if isinstance(state, (list, tuple)) and len(state) >= 6:
        state_list = list(state)
        selected_actions = state_list[5][:]
        
        if action_key in selected_actions:
            selected_actions.remove(action_key)
        else:
            selected_actions.append(action_key)
            
        state_list[5] = selected_actions
        set_user_state(user_id, state_list)
        
        markup = types.InlineKeyboardMarkup()
        for key, label in PIPELINE_ACTIONS.items():
            is_selected = key in selected_actions
            btn_label = f"{'✅' if is_selected else '❌'} {label}"
            markup.row(types.InlineKeyboardButton(btn_label, callback_data=f"scen_toggle_act_{key}"))
        
        markup.row(types.InlineKeyboardButton("ГОТОВО (СОХРАНИТЬ)", callback_data="scen_save_actions"))
        markup.row(types.InlineKeyboardButton("Отмена", callback_data="back_to_main"))
        
        await bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
    
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "scen_save_actions")
async def finalize_scenario_selection(call):
    """Переход к выбору API-ключей (финальное сохранение после выбора ключей)"""
    user_id = call.from_user.id
    try:
        state = get_user_state_db(user_id)
        if isinstance(state, (list, tuple)) and len(state) >= 6:
            name = state[1]
            platforms = state[2]
            content_type = state[3]
            fmt = state[4]
            actions = state[5]
            
            if not actions:
                await bot.answer_callback_query(call.id, "❌ Выберите хотя бы одно действие!")
                return

            order = [p for p in CONTENT_TYPE_PLATFORM_ORDER if p in platforms]
            set_user_state(
                user_id,
                ("waiting_scenario_api_keys", name, platforms, content_type, fmt, actions, order, 0, {})
            )
            await _show_next_api_key_step(user_id, call.message.chat.id, call.message.message_id)
        else:
            await bot.send_message(user_id, "❌ Ошибка: данные сценария повреждены")
            
        await bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка сохранения сценария: {e}", exc_info=True)
        await bot.edit_message_text(f"❌ Ошибка сохранения: {e}", call.message.chat.id, call.message.message_id)
        await bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("scen_key_skip_"))
async def scenario_key_skip(call):
    user_id = call.from_user.id
    state = get_user_state_db(user_id)
    if not (isinstance(state, (list, tuple)) and len(state) >= 9 and state[0] == "waiting_scenario_api_keys"):
        await bot.answer_callback_query(call.id)
        return
    platform = call.data.split("_")[-1]
    name, platforms, content_types_map, fmt, actions, order, idx, api_keys_map = state[1], state[2], state[3], state[4], state[5], state[6], int(state[7]), dict(state[8])
    set_user_state(user_id, ("waiting_scenario_api_keys", name, platforms, content_types_map, fmt, actions, order, idx + 1, api_keys_map))
    await _show_next_api_key_step(user_id, call.message.chat.id, call.message.message_id)
    await bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("scen_key_") and not call.data.startswith("scen_key_skip_"))
async def scenario_key_select(call):
    user_id = call.from_user.id
    state = get_user_state_db(user_id)
    if not (isinstance(state, (list, tuple)) and len(state) >= 9 and state[0] == "waiting_scenario_api_keys"):
        await bot.answer_callback_query(call.id)
        return
    parts = call.data.split("_")
    if len(parts) < 4:
        await bot.answer_callback_query(call.id)
        return
    platform = parts[2]
    key_id = int(parts[3])

    name, platforms, content_types_map, fmt, actions, order, idx, api_keys_map = state[1], state[2], state[3], state[4], state[5], state[6], int(state[7]), dict(state[8])

    try:
        key_data = get_api_key_by_id(key_id, user_id, raw=True)
        if key_data.get("platform") != platform:
            await bot.answer_callback_query(call.id, "Этот ключ не подходит для выбранной платформы", show_alert=True)
            return
    except Exception:
        await bot.answer_callback_query(call.id, "Ключ не найден", show_alert=True)
        return

    api_keys_map[platform] = key_id
    set_user_state(user_id, ("waiting_scenario_api_keys", name, platforms, content_types_map, fmt, actions, order, idx + 1, api_keys_map))
    await _show_next_api_key_step(user_id, call.message.chat.id, call.message.message_id)
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_ct_"))
async def edit_content_type_select(call):
    user_id = call.from_user.id
    state = get_user_state_db(user_id)
    if not (isinstance(state, (list, tuple)) and len(state) >= 6 and state[0] == "edit_scenario_content_types"):
        await bot.answer_callback_query(call.id)
        return
    
    parts = call.data.split("_")
    if len(parts) < 4:
        await bot.answer_callback_query(call.id)
        return
    
    scenario_id = int(parts[2])
    platform = parts[3]
    content_type = "_".join(parts[4:])
    
    scenario_id_state, platforms, order, idx, selected_map = int(state[1]), state[2], state[3], int(state[4]), dict(state[5])
    
    if scenario_id != scenario_id_state:
        await bot.answer_callback_query(call.id, "Ошибка сессии", show_alert=True)
        return
    
    allowed = CONTENT_TYPES_BY_PLATFORM.get(platform, [])
    if content_type not in allowed:
        await bot.answer_callback_query(call.id, "Недопустимый тип контента", show_alert=True)
        return
    
    selected_map[platform] = content_type
    set_user_state(user_id, ("edit_scenario_content_types", scenario_id, platforms, order, idx + 1, selected_map))
    await _show_edit_content_type_step(user_id, call.message.chat.id, call.message.message_id)
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_key_skip_"))
async def edit_key_skip(call):
    user_id = call.from_user.id
    state = get_user_state_db(user_id)
    if not (isinstance(state, (list, tuple)) and len(state) >= 6 and state[0] == "edit_scenario_api_keys"):
        await bot.answer_callback_query(call.id)
        return
    
    parts = call.data.split("_")
    if len(parts) < 4:
        await bot.answer_callback_query(call.id)
        return
    
    scenario_id = int(parts[3])
    platform = parts[4]
    
    scenario_id_state, platforms, order, idx, api_keys_map = int(state[1]), state[2], state[3], int(state[4]), dict(state[5])
    
    if scenario_id != scenario_id_state:
        await bot.answer_callback_query(call.id, "Ошибка сессии", show_alert=True)
        return
    
    if platform in api_keys_map:
        del api_keys_map[platform]
    
    set_user_state(user_id, ("edit_scenario_api_keys", scenario_id, platforms, order, idx + 1, api_keys_map))
    await _show_edit_api_key_step(user_id, call.message.chat.id, call.message.message_id)
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_key_") and not call.data.startswith("edit_key_skip_"))
async def edit_key_select(call):
    user_id = call.from_user.id
    state = get_user_state_db(user_id)
    if not (isinstance(state, (list, tuple)) and len(state) >= 6 and state[0] == "edit_scenario_api_keys"):
        await bot.answer_callback_query(call.id)
        return
    
    parts = call.data.split("_")
    if len(parts) < 4:
        await bot.answer_callback_query(call.id)
        return
    
    scenario_id = int(parts[2])
    platform = parts[3]
    key_id = int(parts[4])
    
    scenario_id_state, platforms, order, idx, api_keys_map = int(state[1]), state[2], state[3], int(state[4]), dict(state[5])
    
    if scenario_id != scenario_id_state:
        await bot.answer_callback_query(call.id, "Ошибка сессии", show_alert=True)
        return
    
    try:
        key_data = get_api_key_by_id(key_id, user_id, raw=True)
        if key_data.get("platform") != platform:
            await bot.answer_callback_query(call.id, "Этот ключ не подходит для выбранной платформы", show_alert=True)
            return
    except Exception:
        await bot.answer_callback_query(call.id, "Ключ не найден", show_alert=True)
        return
    
    api_keys_map[platform] = key_id
    set_user_state(user_id, ("edit_scenario_api_keys", scenario_id, platforms, order, idx + 1, api_keys_map))
    await _show_edit_api_key_step(user_id, call.message.chat.id, call.message.message_id)
    await bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("key_platform_") and call.data != "key_platform_youtube")
async def select_api_key_platform(call):
    """Выбор платформы для API-ключа (кроме YouTube)"""
    user_id = call.from_user.id
    platform = call.data.split("_")[-1]
    state = get_user_state_db(user_id)
    if isinstance(state, (list, tuple)) and len(state) >= 2:
        name = state[1]
    else:
        name = ""
    
    if platform == "telegram":
        set_user_state(f"{user_id}_key_meta", (name, platform))
        set_user_state(user_id, "waiting_telegram_bot_token")
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("Отмена", callback_data="back_to_main"))
        await bot.send_message(
            user_id,
            "🤖 Введите Bot Token для Telegram:\n"
            "📌 Получить можно у @BotFather\n"
            "(Создайте бота командой /newbot)",
            reply_markup=markup
        )
    else:
        set_user_state(f"{user_id}_key_meta", (name, platform))
        set_user_state(user_id, "waiting_api_key_value")
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("Отмена", callback_data="back_to_main"))
        await bot.send_message(user_id, "🔑 Введите API-ключ (токен):", reply_markup=markup)
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "key_platform_youtube")
async def handle_youtube_key(call):
    """Обработка выбора платформы YouTube для API-ключа"""
    user_id = call.from_user.id
    state = get_user_state_db(user_id)
    if isinstance(state, (list, tuple)) and len(state) >= 2:
        name = state[1]
    else:
        name = ""
    await bot.send_message(
        user_id,
        "📌 Для YouTube требуется JSON с данными OAuth2.\n"
        "Пришлите файл credentials.json или вставьте содержимое JSON."
    )
    set_user_state(user_id, "waiting_youtube_json")
    set_user_state(f"{user_id}_key_meta", (name, "youtube"))
    await bot.answer_callback_query(call.id)

@bot.message_handler(content_types=['document'], func=lambda msg: get_user_state_db(msg.from_user.id) == "waiting_youtube_json")
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
        
        meta_key = f"{user_id}_key_meta"
        meta = get_user_state_db(meta_key)
        if meta:
            name, platform = meta
            save_yt_creds(user_id, json_content)
            add_api_key(user_id, name, platform, "oauth2_refresh_token_saved")
            await bot.send_message(user_id, "✅ YouTube ключ сохранён!")
            clear_user_state_db(user_id)
            clear_user_state_db(meta_key)
    except Exception as e:
        await bot.send_message(user_id, f"❌ Ошибка: {e}")

@bot.message_handler(func=lambda msg: get_user_state_db(msg.from_user.id) == "waiting_youtube_json")
async def handle_youtube_json_text(message):
    """Обработка текстового JSON для YouTube"""
    user_id = message.from_user.id
    try:
        json_content = message.text
        json.loads(json_content)
        meta_key = f"{user_id}_key_meta"
        meta = get_user_state_db(meta_key)
        if meta:
            name, platform = meta
            save_yt_creds(user_id, json_content)
            add_api_key(user_id, name, platform, "oauth2_refresh_token_saved")
            await bot.send_message(user_id, "✅ YouTube ключ сохранён!")
            clear_user_state_db(user_id)
            clear_user_state_db(meta_key)
    except Exception as e:
        await bot.send_message(user_id, f"❌ Неверный JSON: {e}")



@bot.message_handler(content_types=['text'])
async def handle_text(message):
    """Обработка текстовых сообщений"""
    if message.from_user.is_bot:
        return
    user_id = message.from_user.id
    text = message.text.strip()
    state = get_user_state_db(user_id)

    if state == "waiting_scenario_name":
        set_user_state(user_id, ("waiting_scenario_platforms", text, []))
        await show_platforms_selection(user_id)
        return

    elif state == "waiting_api_key_name":
        set_user_state(user_id, ("waiting_api_key_platform", text))
        markup = types.InlineKeyboardMarkup()
        for p_key in ["youtube", "vk", "telegram"]:
             p_name = PLATFORM_NAMES.get(p_key, p_key)
             markup.row(types.InlineKeyboardButton(p_name, callback_data=f"key_platform_{p_key}"))
        markup.row(types.InlineKeyboardButton("Отмена", callback_data="back_to_main"))
        await bot.send_message(user_id, "Выберите платформу:", reply_markup=markup)
        return

    elif state == "waiting_api_key_value":
        meta_key = f"{user_id}_key_meta"
        meta = get_user_state_db(meta_key)
        if meta:
            name, platform = meta
            add_api_key(user_id, name, platform, text)
            await bot.send_message(user_id, "✅ Ключ сохранён!")
            clear_user_state_db(user_id)
            clear_user_state_db(meta_key)
            markup = get_main_menu_keyboard()
            await bot.send_message(user_id, "Главное меню:", reply_markup=markup)
        return
    
    elif state == "waiting_telegram_bot_token":
        set_user_state(f"{user_id}_telegram_bot_token", text)
        set_user_state(user_id, "waiting_telegram_channel_id")
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("Отмена", callback_data="back_to_main"))
        await bot.send_message(
            user_id,
            "📺 Введите @username вашего канала:\n"
            "💡 Например: @mychannel\n\n"
            "📌 Если у канала нет @username, используйте числовой ID:\n"
            "(Получить можно через @userinfobot, переслав ему любое сообщение из канала)\n\n"
            "⚠️ Важно: бот должен быть администратором канала!",
            reply_markup=markup
        )
        return
    
    elif state == "waiting_telegram_channel_id":
        bot_token = get_user_state_db(f"{user_id}_telegram_bot_token")
        meta_key = f"{user_id}_key_meta"
        meta = get_user_state_db(meta_key)
        if meta and bot_token:
            name, platform = meta
            channel_id = text.strip()
            combined_key = f"{bot_token}|||{channel_id}"
            add_api_key(user_id, name, platform, combined_key)
            await bot.send_message(user_id, "✅ Telegram ключ сохранён!")
            clear_user_state_db(user_id)
            clear_user_state_db(meta_key)
            clear_user_state_db(f"{user_id}_telegram_bot_token")
            markup = get_main_menu_keyboard()
            await bot.send_message(user_id, "Главное меню:", reply_markup=markup)
        return

    elif state and isinstance(state, str) and state.startswith("waiting_link_scen_"):
        scenario_id = int(state.split("_")[-1])
        clear_user_state_db(user_id)
        
        url = text.strip()
        if not url:
            await bot.send_message(user_id, "❌ Ссылка не может быть пустой.")
            return
        if not re.match(r'^https?://', url):
             await bot.send_message(user_id, "❌ Нужна ссылка, начинающаяся с http:// или https://")
             return
        
        scenario = get_scenario_by_id(scenario_id, user_id)
        if not scenario:
             await bot.send_message(user_id, "❌ Сценарий не найден.")
             return
             
        await send_status(user_id, f"✅ Сценарий '{scenario['name']}' выбран.\n⏳ Начинаю обработку видео...\n1️⃣ Скачивание...")
        
        try:
            await process_video_workflow(user_id, url, scenario)
        except Exception as e:
            logger.error(f"Ошибка обработки видео: {e}", exc_info=True)
            error_msg = str(e)
            if "empty" in error_msg.lower() or "скачать" in error_msg.lower():
                user_message = (
                    f"❌ Ошибка скачивания видео:\n{error_msg}\n\n"
                    "💡 Попробуйте:\n"
                    "• Другую ссылку на видео\n"
                    "• Загрузить видео файлом напрямую\n"
                    "• Проверить доступность видео"
                )
            else:
                user_message = (
                    f"❌ Произошла ошибка: {error_msg}\n\n"
                    "Попробуйте еще раз или обратитесь в поддержку."
                )
            await send_status(user_id, user_message)

@bot.callback_query_handler(func=lambda call: call.data == "start_processing")
async def start_processing_callback(call):
    """Начало обработки видео (выбор сценария)"""
    user_id = call.from_user.id
    scenarios = get_scenarios(user_id)
    if not scenarios:
         await bot.answer_callback_query(call.id, "У вас нет сценариев", show_alert=True)
         markup = types.InlineKeyboardMarkup()
         markup.row(types.InlineKeyboardButton("➕ Создать сценарий", callback_data="create_scenario"))
         markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
         await bot.edit_message_text("⚠️ У вас нет сценариев. Создайте сценарий в меню '🎭 Сценарии'.", call.message.chat.id, call.message.message_id, reply_markup=markup)
         return

    markup = types.InlineKeyboardMarkup()
    for s_id, name, _, _, _, _ in scenarios:
        markup.add(types.InlineKeyboardButton(name, callback_data=f"select_scen_process_{s_id}"))
    markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
    
    await bot.edit_message_text("🎞 Выберите сценарий для обработки:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    await bot.answer_callback_query(call.id)


@bot.message_handler(content_types=['video', 'document'])
async def handle_video_or_document(message):
    """Обработка видео и документов"""
    if message.from_user.is_bot:
        return
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
            await bot.send_message(user_id, "📎 Я обрабатываю только видео.")
            return
    else:
        return
    
    scenario_id_state = None
    state = get_user_state_db(user_id)
    if isinstance(state, str) and state.startswith("waiting_link_scen_"):
        scenario_id_state = int(state.split("_")[-1])

    if not scenario_id_state:
        scenarios = get_scenarios(user_id)
        if not scenarios:
             await bot.send_message(user_id, "⚠️ У вас нет сценариев. Создайте сценарий в меню '🎭 Сценарии'.")
             return

        markup = types.InlineKeyboardMarkup()
        for s_id, name, _, _, _, _ in scenarios:
            markup.add(types.InlineKeyboardButton(name, callback_data=f"use_scen_{s_id}_with_file"))
        
        pending_data = {
            "type": message.content_type,
            "file_id": file_id,
            "file_name": file_name,
            "mime_type": mime_type
        }
        set_user_state(f"pending_file_{user_id}", pending_data)
        await bot.send_message(user_id, "🎞 Выберите сценарий для обработки этого файла:", reply_markup=markup)
        return
    
    user_id = message.from_user.id
    scenario = get_scenario_by_id(scenario_id_state, user_id)
    if not scenario:
         await bot.send_message(user_id, "❌ Сценарий не найден.")
         return

    clear_user_state_db(user_id)
    await download_and_process_file(user_id, file_id, file_name, message, scenario)

async def publish_to_draft(user_id: int, scenario: dict, result):
    """Публикация видео по сценарию на все платформы"""
    platforms = scenario.get("platforms", [])
    video_path = result.processed_video_path
    
    if not video_path:
        await bot.send_message(user_id, "❌ Ошибка: путь к обработанному видео не найден")
        return
    
    for platform in platforms:
        try:
            content = result.generated_content.get(platform, {}).get("content", {})
            if not content:
                await bot.send_message(user_id, f"⚠️ Контент для {_platform_label(platform)} не был сгенерирован, пропускаю публикацию.")
                continue

            title = content.get("title", "Без названия")[:100]
            description = content.get("description", content.get("post", ""))[:5000]
            tags = content.get("tags", [])
            
            api_keys_map = scenario.get("api_keys_map", {})
            key_id = api_keys_map.get(platform)
            
            if not key_id:
                await bot.send_message(user_id, f"⚠️ Нет привязанного API-ключа для {platform} в этом сценарии, пропускаю.")
                continue
            
            if platform == "youtube":
                try:
                    scenario_ct = _get_content_type_for_platform(scenario, "youtube")
                    content_type = scenario_ct if scenario_ct in ("shorts", "video") else "video"
                    link = await publish_to_youtube_draft(user_id, video_path, title, description, tags, content_type)
                    await bot.send_message(user_id, f"✅ Видео отправлено в черновики YouTube:\n{link}")
                except ValueError as ve:
                    error_msg = str(ve)
                    logger.error(f"Ошибка валидации YouTube для {user_id}: {error_msg}")
                    await bot.send_message(user_id, f"❌ Ошибка публикации в YouTube:\n{error_msg}")
                except Exception as e:
                    logger.error(f"Неожиданная ошибка публикации в YouTube для {user_id}: {e}", exc_info=True)
                    await bot.send_message(
                        user_id,
                        f"❌ Ошибка публикации в YouTube: {str(e)}\n\n"
                        "Проверьте:\n"
                        "1. Правильность YouTube credentials\n"
                        "2. Существование и доступность видеофайла"
                    )
            
            elif platform == "vk":
                try:
                    scenario_ct = _get_content_type_for_platform(scenario, "vk")
                    content_type = scenario_ct if scenario_ct in ("clip", "post") else "clip"
                    if content_type == "post":
                        await bot.send_message(user_id, "⚠️ VK: публикация текстового поста пока не реализована, пропускаю.")
                        continue
                    access_token = get_api_key_by_id(key_id, user_id)
                    link = await publish_to_vk_draft(access_token, video_path, title, description, content_type)
                    await bot.send_message(user_id, f"✅ Видео отправлено в черновики VK:\n{link}")
                except ValueError as ve:
                    error_msg = str(ve)
                    logger.error(f"Ошибка валидации VK для {user_id}: {error_msg}")
                    await bot.send_message(user_id, f"❌ Ошибка публикации в VK:\n{error_msg}")
                except Exception as e:
                    logger.error(f"Неожиданная ошибка публикации в VK для {user_id}: {e}", exc_info=True)
                    await bot.send_message(
                        user_id,
                        f"❌ Ошибка публикации в VK: {str(e)}\n\n"
                        "Проверьте:\n"
                        "1. Правильность VK access token\n"
                        "2. Существование и доступность видеофайла"
                    )
            
            elif platform == "telegram":
                try:
                    key_data = get_api_key_by_id(key_id, user_id, raw=True)
                    if not key_data:
                        logger.warning(f"API ключ {key_id} не найден для пользователя {user_id}")
                        continue
                    
                    combined_key = key_data.get('key', '').strip()
                    
                    if not combined_key:
                        await bot.send_message(
                            user_id,
                            "⚠️ Ошибка: пустой API ключ для Telegram. Пересоздайте ключ."
                        )
                        continue
                    
                    # парсинг ключа (формат: bot_token|||channel_id)
                    if "|||" in combined_key:
                        parts = combined_key.split("|||", 1)
                        bot_token = parts[0].strip()
                        channel_id = parts[1].strip() if len(parts) > 1 else ""
                    else:
                        bot_token = combined_key.strip()
                        channel_id = key_data.get('name', '').strip()
                    
                    if not bot_token:
                        await bot.send_message(
                            user_id,
                            "⚠️ Ошибка: Bot Token не найден в ключе. Пересоздайте ключ."
                        )
                        continue
                    
                    if not channel_id:
                        await bot.send_message(
                            user_id,
                            "⚠️ Ошибка: Channel ID не найден в ключе. Пересоздайте ключ."
                        )
                        continue
                    
                    scenario_ct = _get_content_type_for_platform(scenario, "telegram")
                    tg_ct = scenario_ct if scenario_ct in ("post", "video") else "video"
                    tg_video_path = None if tg_ct == "post" else video_path
                    
                    link = await publish_to_telegram_channel(
                        bot_token, 
                        channel_id, 
                        tg_video_path, 
                        title, 
                        description
                    )
                    await bot.send_message(user_id, f"✅ Пост отправлен в Telegram:\n{link}")
                    
                except ValueError as ve:
                    error_msg = str(ve)
                    logger.error(f"Ошибка валидации Telegram ключа для {user_id}: {error_msg}")
                    await bot.send_message(user_id, f"❌ Ошибка публикации в Telegram:\n{error_msg}")
                except Exception as e:
                    logger.error(f"Неожиданная ошибка публикации в Telegram для {user_id}: {e}", exc_info=True)
                    await bot.send_message(
                        user_id,
                        f"❌ Ошибка публикации в Telegram: {str(e)}\n\n"
                        "Проверьте:\n"
                        "1. Правильность Bot Token и Channel ID\n"
                        "2. Бот добавлен в канал как администратор"
                    )
        
        except Exception as e:
            logger.error(f"Ошибка публикации для {user_id} в {platform}: {e}")
            await bot.send_message(user_id, f"❌ Ошибка публикации в {platform}: {str(e)}")

async def process_video_workflow(user_id: int, url: str, scenario: dict):
    """Основной процесс обработки видео по URL с выбранным сценарием"""
    try:
        video_path = await download_video(url)
        await run_processing_with_scenario(user_id, video_path, scenario)
    except Exception as e:
        logger.error(f"Ошибка в workflow: {e}", exc_info=True)
        raise

async def download_and_process_file(user_id, file_id, file_name, message, scenario):
    """Скачивание файла и запуск обработки по сценарию"""
    await send_status(user_id, f"⏳ Получаю видео для сценария '{scenario['name']}'...")
    try:
        file_info = await bot.get_file(file_id)
        save_path = os.path.join(config.UPLOAD_DIR, file_name)
        
        if config.TELEGRAM_API_URL and file_info.file_path.startswith('/'):
            local_file_path = file_info.file_path
            if os.path.exists(local_file_path):
                shutil.copy(local_file_path, save_path)
            else:
                downloaded_file = await bot.download_file(file_info.file_path)
                with open(save_path, 'wb') as f:
                    f.write(downloaded_file)
        else:
            downloaded_file = await bot.download_file(file_info.file_path)
            with open(save_path, 'wb') as f:
                f.write(downloaded_file)
        
        logger.info(f"Сохранено видео от пользователя {user_id}: {save_path}")
        await run_processing_with_scenario(user_id, save_path, scenario)
        
    except Exception as e:
        logger.error(f"Ошибка скачивания видео: {e}", exc_info=True)
        error_msg = str(e)
        await send_status(
            user_id,
            f"❌ Не удалось обработать видео: {error_msg}\n\n"
            "Попробуйте загрузить видео еще раз или выберите другой файл."
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_scen_process_'))
async def callback_select_scenario_process(call):
    """Выбор сценария и ожидание ссылки"""
    user_id = call.from_user.id
    scenario_id = int(call.data.split('_')[-1])
    scenario = get_scenario_by_id(scenario_id, user_id)
    if not scenario:
         await bot.answer_callback_query(call.id, "Сценарий не найден")
         return
    
    set_user_state(user_id, f"waiting_link_scen_{scenario_id}")
    await bot.send_message(user_id, f"🎞 Выбран сценарий: **{scenario['name']}**\n📎 Теперь отправьте ссылку на видео или сам видеофайл.", parse_mode="Markdown")
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('use_scen_'))
async def use_scenario_for_pending_file(call):
    """Запуск сценария для уже отправленного (но не скачанного) файла"""
    user_id = call.from_user.id
    parts = call.data.split('_')
    scenario_id = int(parts[2])
    
    pending_data = get_user_state_db(f"pending_file_{user_id}")
    if not pending_data:
         await bot.send_message(user_id, "❌ Файл не найден или сессия истекла. Отправьте файл заново.")
         return

    scenario = get_scenario_by_id(scenario_id, user_id)
    if not scenario:
         await bot.send_message(user_id, "❌ Сценарий не найден.")
         return

    await bot.answer_callback_query(call.id, "✅ Начинаю обработку...")
    await bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    
    clear_user_state_db(f"pending_file_{user_id}")
    
    await download_and_process_file(user_id, pending_data["file_id"], pending_data["file_name"], None, scenario)


async def run_processing_with_scenario(user_id: int, video_path: str, scenario: dict):
    """Запуск оркестратора с параметрами сценария"""
    try:
        await send_status(user_id, f"🎬 Запуск сценария '{scenario['name']}'...\n2️⃣ Обработка...")
        
        platforms = scenario.get("platforms", [])
        pipeline_actions = scenario.get("pipeline_actions", [])
        post_format = scenario.get("format", "neutral")
        custom_prompt = None

        result = await orchestrator_client.process_video(
            video_path,
            platforms=platforms,
            post_format=post_format,
            custom_prompt=custom_prompt,
            pipeline_actions=pipeline_actions
        )
        
        if result.status == "failed":
            await send_status(user_id, f"❌ Ошибка: {result.error}")
            return
        
        await send_status(user_id, "✅ Обработка завершена!\n\n📊 Результаты:")
        
        # 0. отображение транскрибации, если она была выбрана
        if "transcribe" in pipeline_actions and result.transcription:
            await bot.send_message(user_id, f"📝 **Транскрибация:**\n\n{result.transcription}", parse_mode='Markdown')

        # проверка политики по транскрипту (если запрашивалась)
        if "check_policy" in pipeline_actions and result.transcript_check:
            tc = result.transcript_check
            verdict = tc.get("verdict", "UNKNOWN")
            confidence = tc.get("confidence", 0)
            emoji = "✅" if verdict == "ALLOW" else "❌"
            verdict_text = "соответствует" if verdict == "ALLOW" else "НЕ соответствует"
            platform_name = PLATFORM_NAMES.get(tc.get("platform", "youtube"), tc.get("platform", ""))
            header = f"Проверка политики ({platform_name})" if platform_name else "Проверка политики"
            await bot.send_message(
                user_id,
                f"{emoji} **{header}:** {verdict_text} ({confidence:.0%})",
                parse_mode='Markdown'
            )

        if result.generated_content:
            text_blocks = []
            
            # 1. YouTube результаты
            youtube_data = result.generated_content.get('youtube', {})
            if youtube_data and 'youtube' in platforms:
                policy_check = youtube_data.get('policy_check')
                if policy_check:
                    verdict = policy_check.get('verdict', 'UNKNOWN')
                    confidence = policy_check.get('confidence', 0)
                    emoji = "✅" if verdict == "ALLOW" else "❌"
                    verdict_text = "соответствует" if verdict == "ALLOW" else "НЕ соответствует"
                    text_blocks.append(f"{emoji} **YouTube Policy:** {verdict_text} ({confidence:.0%})")

                yt_content = youtube_data.get('content', {})
                if yt_content:
                    yt_title = yt_content.get('title', 'Без заголовка').strip('"')
                    yt_desc = yt_content.get('description', 'Без описания').strip('"')
                    yt_tags = yt_content.get('tags', [])
                    tags_str = ' '.join(yt_tags) if yt_tags else '#shorts'
                    
                    await bot.send_message(user_id, f"🎬 **YouTube**\n\n📌 **{yt_title}**\n\n📝 {yt_desc}\n\n🏷 {tags_str}", parse_mode='Markdown')
            
            # 2. Telegram результаты
            telegram_data = result.generated_content.get('telegram', {})
            if telegram_data and 'telegram' in platforms:
                tg_content = telegram_data.get('content', {})
                if tg_content:
                    tg_title = tg_content.get('title', 'Без заголовка').strip('"')
                    tg_post = tg_content.get('post', 'Без текста').strip('"')
                    await bot.send_message(user_id, f"📱 **Telegram**\n\n**{tg_title}**\n\n{tg_post}", parse_mode='Markdown')

            if text_blocks:
                await bot.send_message(user_id, "\n".join(text_blocks), parse_mode='Markdown')

            # обложки
            thumbnails = youtube_data.get('thumbnails', [])
            if thumbnails:
                try:
                    media_group = []
                    for i, thumb in enumerate(thumbnails[:5], 1):
                        thumb_path = thumb.get('path', '')
                        if thumb_path and os.path.exists(thumb_path):
                            with open(thumb_path, 'rb') as thumb_file:
                                media_group.append(
                                    types.InputMediaPhoto(
                                        thumb_file.read(),
                                        caption="🖼 Варианты обложек" if i == 1 else None
                                    )
                                )
                    if media_group:
                        await bot.send_media_group(user_id, media_group)
                except Exception as e:
                    logger.error(f"Ошибка отправки обложек: {e}")

        if result.processed_video_path and ("cut_silence" in pipeline_actions):
            await send_status(user_id, "🎬 Отправляю готовое видео...")
            try:
                width, height = get_video_dimensions(result.processed_video_path)
                with open(result.processed_video_path, 'rb') as video:
                    await bot.send_video(user_id, video, caption="✨ Ваше видео готово!", width=width, height=height)
            except Exception as e:
                logger.error(f"Ошибка отправки видео: {e}")
        
        if "publish" in pipeline_actions and result.processed_video_path:
            await publish_to_draft(user_id, scenario, result)

        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_main"))
        await bot.send_message(user_id, "✨ Обработка завершена. Что желаете сделать дальше?", reply_markup=markup)

    except Exception as e:
        logger.error(f"Ошибка обработки: {e}", exc_info=True)
        await send_status(user_id, f"❌ Ошибка обработки: {e}")
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_main"))
        await bot.send_message(user_id, "Попробуйте еще раз или вернитесь в меню.", reply_markup=markup)

if __name__ == "__main__":
    init_db()
    logger.info("🤖 Telegram Bot запущен")
    asyncio.run(bot.polling(non_stop=True))