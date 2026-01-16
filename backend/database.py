import sqlite3
import os
import json
import logging
from typing import Dict, Any, List, Optional
from security import encrypt_key, decrypt_key

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/data/bot_data.db")


def init_db():
    """Инициализация базы данных с поддержкой сценариев и API-ключей"""
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.cursor()

            # таблица API-ключей (токенов)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                platform TEXT NOT NULL CHECK(platform IN ('youtube', 'vk', 'telegram')),
                encrypted_key TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # таблица сценариев
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS scenarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                platforms TEXT NOT NULL,
                pipeline_actions TEXT NOT NULL,
                content_type TEXT,
                format TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            conn.commit()


            # таблица связей сценариев и API-ключей
            cursor.execute("""

            CREATE TABLE IF NOT EXISTS scenario_api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scenario_id INTEGER NOT NULL,
                api_key_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                FOREIGN KEY (scenario_id) REFERENCES scenarios(id) ON DELETE CASCADE,
                FOREIGN KEY (api_key_id) REFERENCES api_keys(id) ON DELETE CASCADE
            )
            """)

            # таблица состояний пользователя
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_states (
                state_key TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            
            try:
                cursor.execute("ALTER TABLE scenario_api_keys ADD COLUMN platform TEXT DEFAULT 'unknown'")
            except sqlite3.OperationalError:
                pass

            conn.commit()
            logger.info(f"База данных инициализирована: {DB_PATH}")

    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")


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


def get_api_key_by_id(key_id: int, user_id: int, raw: bool = False) -> Any:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, encrypted_key, platform FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user_id))
        row = cursor.fetchone()
        if row:
            decrypted = decrypt_key(row[1])
            if raw:
                return {"name": row[0], "key": decrypted, "platform": row[2]}
            return decrypted
        raise ValueError("API-ключ не найден или доступ запрещён")


def delete_api_key(key_id: int, user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user_id))
        conn.commit()


def add_scenario(
    user_id: int,
    name: str,
    platforms: List[str],
    pipeline_actions: List[str],
    api_keys_map: Dict[str, int],
    content_type: str = None,
    format: str = None
) -> int:
    """
    Добавить новый сценарий
    
    Args:
        api_keys_map: Словарь {platform: api_key_id}
    """
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO scenarios (
                user_id, name, platforms, pipeline_actions, content_type, format
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id, name,
            json.dumps(platforms),
            json.dumps(pipeline_actions),
            content_type or "",
            format or ""
        ))
        
        scenario_id = cursor.lastrowid
        
        for platform, api_key_id in api_keys_map.items():
            cursor.execute("""
                INSERT INTO scenario_api_keys (scenario_id, platform, api_key_id)
                VALUES (?, ?, ?)
            """, (scenario_id, platform, api_key_id))
        
        conn.commit()
        return scenario_id



def get_scenarios(user_id: int) -> List[tuple]:
    """Получить все сценарии пользователя"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, platforms, pipeline_actions, content_type, format
            FROM scenarios WHERE user_id = ?
        """, (user_id,))
        return cursor.fetchall()



def get_scenario_by_id(scenario_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    """Получить сценарий по ID с полной информацией"""
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, name, platforms, pipeline_actions, content_type, format
            FROM scenarios WHERE id = ? AND user_id = ?
        """, (scenario_id, user_id))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        cursor.execute("""
            SELECT platform, api_key_id FROM scenario_api_keys
            WHERE scenario_id = ?
        """, (scenario_id,))
        
        api_keys_rows = cursor.fetchall()
        api_keys_map = {platform: key_id for platform, key_id in api_keys_rows}
        
        content_type_raw = row[4]
        content_type_value = content_type_raw
        if isinstance(content_type_raw, str):
            ct_str = content_type_raw.strip()
            if ct_str.startswith("{") and ct_str.endswith("}"):
                try:
                    parsed = json.loads(ct_str)
                    if isinstance(parsed, dict):
                        content_type_value = parsed
                except Exception:
                    content_type_value = content_type_raw
        
        return {
            "id": row[0],
            "name": row[1],
            "platforms": json.loads(row[2]) if row[2] else [],
            "pipeline_actions": json.loads(row[3]) if row[3] else [],
            "content_type": content_type_value,
            "format": row[5],
            "api_keys_map": api_keys_map
        }


def delete_scenario(scenario_id: int, user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM scenarios WHERE id = ? AND user_id = ?", (scenario_id, user_id))
        conn.commit()


def update_scenario(
    scenario_id: int,
    user_id: int,
    name: str = None,
    platforms: List[str] = None,
    pipeline_actions: List[str] = None,
    content_type: str = None,
    format: str = None
):
    """Обновить существующий сценарий"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        
        if platforms is not None:
            updates.append("platforms = ?")
            params.append(json.dumps(platforms))
            
        if pipeline_actions is not None:
            updates.append("pipeline_actions = ?")
            params.append(json.dumps(pipeline_actions))
            
        if content_type is not None:
            updates.append("content_type = ?")
            if isinstance(content_type, (dict, list)):
                params.append(json.dumps(content_type, ensure_ascii=False))
            else:
                params.append(content_type)
            
        if format is not None:
            updates.append("format = ?")
            params.append(format)
            
        if not updates:
            return

        params.append(scenario_id)
        params.append(user_id)
        
        sql = f"UPDATE scenarios SET {', '.join(updates)} WHERE id = ? AND user_id = ?"
        cursor.execute(sql, params)
        conn.commit()


def set_user_state(state_key: str, state: Any):
    """Сохранить состояние в БД"""
    state_json = json.dumps(state)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO user_states (state_key, state_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(state_key) DO UPDATE SET 
                state_json = excluded.state_json,
                updated_at = CURRENT_TIMESTAMP
        """, (str(state_key), state_json))
        conn.commit()


def get_user_state_db(state_key: str) -> Any:
    """Получить состояние из БД"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT state_json FROM user_states WHERE state_key = ?", (str(state_key),))
        row = cursor.fetchone()
        if row:
            return json.loads(row[0])
        return None


def clear_user_state_db(state_key: str):
    """Очистить состояние"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_states WHERE state_key = ?", (str(state_key),))
        conn.commit()