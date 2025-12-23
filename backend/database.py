import sqlite3
import os
import logging
from typing import Dict, Any


logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/data/bot_data.db")

def init_db():
    """Инициализация базы данных"""
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Таблица настроек пользователя
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                platform TEXT DEFAULT 'all',  -- all, youtube, telegram
                post_format TEXT DEFAULT 'neutral', -- neutral, selling, etc.
                custom_prompt TEXT DEFAULT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            
            conn.commit()
            logger.info(f"База данных инициализирована: {DB_PATH}")
            
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")

def get_settings(user_id: int) -> Dict[str, Any]:
    """Получить настройки пользователя"""
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
    """Обновить настройки пользователя"""
    try:
        current = get_settings(user_id)
        
        # Обновляем только переданные поля
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
