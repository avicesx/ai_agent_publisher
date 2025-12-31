# backend/database.py
import sqlite3
import os
import logging
from typing import Dict, Any, List, Optional
from .security import encrypt_key, decrypt_key

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/data/bot_data.db")


def init_db():
    """Инициализация базы данных с поддержкой сценариев и API-ключей"""
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()

            # Таблица настроек пользователя (остаётся для совместимости)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                platform TEXT DEFAULT 'all',
                post_format TEXT DEFAULT 'neutral',
                custom_prompt TEXT DEFAULT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Таблица API-ключей (токенов)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                platform TEXT NOT NULL CHECK(platform IN ('youtube', 'vk', 'telegram')),
                encrypted_key TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES user_settings(user_id) ON DELETE CASCADE
            )
            """)

            # Таблица сценариев
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS scenarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                platform TEXT NOT NULL CHECK(platform IN ('youtube', 'vk', 'telegram')),
                content_type TEXT NOT NULL CHECK(content_type IN ('shorts', 'clip', 'post', 'video')),
                format TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES user_settings(user_id) ON DELETE CASCADE
            )
            """)

            conn.commit()
            logger.info(f"База данных инициализирована: {DB_PATH}")

    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")


# === Существующие функции (без изменений) ===
def get_settings(user_id: int) -> Dict[str, Any]:
    default_settings = {
        "platform": "all",
        "post_format": "neutral",
        "custom_prompt": None
    }
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT platform, post_format, custom_prompt FROM user_settings WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "platform": row[0],
                    "post_format": row[1],
                    "custom_prompt": row[2]
                }
            return default_settings
    except Exception as e:
        logger.error(f"Ошибка получения настроек для {user_id}: {e}")
        return default_settings


def update_settings(user_id: int, **kwargs):
    try:
        current = get_settings(user_id)
        new_settings = {**current, **kwargs}
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO user_settings (user_id, platform, post_format, custom_prompt, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                user_id,
                new_settings["platform"],
                new_settings["post_format"],
                new_settings["custom_prompt"]
            ))
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка обновления настроек для {user_id}: {e}")


# === НОВЫЕ: API-ключи ===
def add_api_key(user_id: int, name: str, platform: str, api_key: str):
    encrypted = encrypt_key(api_key)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO api_keys (user_id, name, platform, encrypted_key)
            VALUES (?, ?, ?, ?)
        """, (user_id, name, platform, encrypted))
        conn.commit()


def get_api_keys(user_id: int) -> List[tuple]:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, platform FROM api_keys WHERE user_id = ?", (user_id,))
        return cursor.fetchall()


def get_api_key_by_id(key_id: int, user_id: int) -> str:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT encrypted_key FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user_id))
        row = cursor.fetchone()
        if row:
            return decrypt_key(row[0])
        raise ValueError("API-ключ не найден или доступ запрещён")


def delete_api_key(key_id: int, user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user_id))
        conn.commit()


# === НОВЫЕ: Сценарии ===
def add_scenario(user_id: int, name: str, platform: str, content_type: str, format: str):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO scenarios (user_id, name, platform, content_type, format)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, name, platform, content_type, format))
        conn.commit()


def get_scenarios(user_id: int) -> List[tuple]:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, platform, content_type, format FROM scenarios WHERE user_id = ?", (user_id,))
        return cursor.fetchall()


def get_scenario_by_id(scenario_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, platform, content_type, format FROM scenarios WHERE id = ? AND user_id = ?", (scenario_id, user_id))
        row = cursor.fetchone()
        if row:
            return {
                "id": row[0],
                "name": row[1],
                "platform": row[2],
                "content_type": row[3],
                "format": row[4]
            }
        return None


def delete_scenario(scenario_id: int, user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM scenarios WHERE id = ? AND user_id = ?", (scenario_id, user_id))
        conn.commit()