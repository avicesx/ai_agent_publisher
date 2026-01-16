import logging
import json
import re
from llama_cpp import Llama
from typing import List, Dict, Any
import config

logger = logging.getLogger(__name__)

llm = None


# форматы постов и их промты
POST_FORMAT_INSTRUCTIONS = {
    "neutral": "",
    "selling": "Используй продающий стиль: акцент на выгоды, призыв к действию.",
    "cta_subscribe": "Закончи призывом подписаться на канал.",
    "cta_comment": "Закончи призывом написать в комментариях.",
    "cta_engage": "Закончи призывом поставить лайк или сделать репост.",
    "warming": "Создай интригу, вызови эмоции и интерес.",
    "expert": "Используй авторитетный экспертный тон.",
    "storytelling": "Используй повествовательный стиль, расскажи историю.",
}


def load_llm():
    """Загрузка GGUF модели при старте сервиса"""
    global llm
    logger.info(f"Загрузка модели из {config.MODEL_PATH}...")
    llm = Llama(
        model_path=config.MODEL_PATH,
        n_ctx=config.N_CTX,
        n_threads=config.N_THREADS,
        n_gpu_layers=config.N_GPU_LAYERS,
        n_batch=128,
        verbose=False 
    )
    logger.info("Модель успешно загружена")


def ask_llm(prompt: str, json_mode: bool = False) -> str:
    """Генерация текста через LLM"""
    system_prompt = "Ты — помощник по созданию контента. Пиши только на русском языке. Твоя задача — переписать или кратко изложить предоставленный текст в нужном формате. Не пиши вводных фраз, отвечай сразу готовым текстом."
    if json_mode:
        system_prompt += " ОТВЕЧАЙ СТРОГО В ФОРМАТЕ JSON."

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]
    
    max_tokens = config.MAX_TOKENS * 2 if json_mode else config.MAX_TOKENS
    
    output = llm.create_chat_completion(
        messages=messages,
        max_tokens=max_tokens,
        temperature=config.TEMPERATURE,
        top_p=config.TOP_P,
        response_format={"type": "json_object"} if json_mode else None
    )
    
    return output["choices"][0]["message"]["content"]


def _fix_json_encoding(json_str: str) -> str:
    """Исправляет неэкранированные кавычки и переносы строк в JSON строках"""
    try:
        json.loads(json_str)
        return json_str
    except:
        pass
    fixed = re.sub(r'(?<!\\)\n', '\\n', json_str)
    return fixed


def _repair_json(json_str: str, error: json.JSONDecodeError) -> Dict[str, Any]:
    """Восстанавливает обрезанный или поврежденный JSON"""
    try:
        open_braces = json_str.count('{') - json_str.count('}')
        open_brackets = json_str.count('[') - json_str.count(']')
        if open_braces > 0 or open_brackets > 0:
            fixed = json_str + '}' * open_braces + ']' * open_brackets
            try:
                return json.loads(fixed)
            except:
                pass
        
        error_pos = getattr(error, 'pos', len(json_str))
        
        last_valid_quote = -1
        in_string = False
        escape_next = False
        
        for i in range(min(error_pos, len(json_str) - 1), -1, -1):
            char = json_str[i]
            
            if escape_next:
                escape_next = False
                continue
            
            if char == '\\':
                escape_next = True
                continue
            
            if char == '"' and not escape_next:
                if in_string:
                    last_valid_quote = i
                    break
                in_string = not in_string
        
        if last_valid_quote > 0:
            fixed = json_str[:last_valid_quote + 1] + '"'
            open_braces = fixed.count('{') - fixed.count('}')
            open_brackets = fixed.count('[') - fixed.count(']')
            fixed += '}' * open_braces + ']' * open_brackets
            try:
                return json.loads(fixed)
            except:
                pass
        
        pattern = r'"(\w+)":\s*"[^"]*"'
        matches = list(re.finditer(pattern, json_str))
        if matches:
            last_match = matches[-1]
            cut_pos = last_match.end()
            fixed = json_str[:cut_pos]
            open_braces = fixed.count('{') - fixed.count('}')
            open_brackets = fixed.count('[') - fixed.count(']')
            fixed += '}' * open_braces + ']' * open_brackets
            try:
                return json.loads(fixed)
            except:
                pass
        
        return None
    except Exception:
        return None


def clean_text(text: str, max_chars: int = 4000) -> str:
    """Очистка текста от мусора, вводных фраз и заголовков секций + лимит по длине"""
    if not text:
        return ""
    lines = text.strip().split('\n')
    cleaned_lines = []
    
    # фразы, которые точно являются мусором, если идут в начале
    junk_prefixes = (
        "Вот ", "Конечно", "Задание", "Ваше сообщение", 
        "Транскрипция", "Текст видео", "Информативный пост",
        "---", "###", "Заголовок:", "Описание:", "Пост:",
        "Понятно", "Хорошо", "ОК", "Окей", "Извините",
        "Вступление:", "Основной текст:", "Видеорежиссер:", "Заключение:",
        "Заголовок "
    )
    
    # секции, которые модель любит добавлять
    unwanted_headers = (
        "Интересные факты", "Заключение", "Итог", "Важное",
        "Ключевые моменты", "Основные идеи", "Ваше сообщение",
        "Заголовок", "Вступление", "Основной текст", "Видеорежиссер"
    )

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            cleaned_lines.append("")
            continue
            
        if any(line_stripped.startswith(prefix) for prefix in junk_prefixes):
            continue
            
        is_unwanted = False
        for header in unwanted_headers:
            if line_stripped.lower().startswith(header.lower()):
                is_unwanted = True
                break
        if is_unwanted:
            continue
            
        cleaned_lines.append(line)
        
    result = "\n".join(cleaned_lines).strip().strip('"').strip('*').strip()
    return result[:max_chars]


def bulk_generate_content(transcript: str, platforms: List[str], post_format: str = "neutral", custom_prompt: str = None) -> Dict[str, Any]:
    """Генерация всего контента за один запрос к LLM"""
    
    instruction = custom_prompt if custom_prompt else POST_FORMAT_INSTRUCTIONS.get(post_format, "")
    
    platform_requests = []
    if "youtube" in platforms:
        platform_requests.append("- YouTube: заголовок (до 60 симв), описание (до 300 симв), 7 тегов через запятую")
    if "telegram" in platforms:
        platform_requests.append("- Telegram: цепляющий заголовок, полноценный пост с разделением на абзацы")

    requests_text = "\n".join(platform_requests)

    prompt = f"""
Текст видео для обработки:
{transcript}

Стиль/Инструкция: {instruction}

ЗАДАНИЕ: Сгенерируй контент для следующих платформ:
{requests_text}

ОТВЕТЬ СТРОГО В ФОРМАТЕ JSON:
{{
  "youtube": {{
    "title": "...",
    "description": "...",
    "tags": ["tag1", "tag2", ...]
  }},
  "telegram": {{
    "title": "...",
    "post": "..."
  }}
}}

ПРАВИЛА:
1. Пиши только на русском языке.
2. Никаких вводных фраз ("Вот ваш контент", "Конечно").
3. В полях YouTube description и Telegram post используй символы переноса строки \\n (НЕ реальные переносы строк).
4. ВСЕ кавычки внутри текста должны быть экранированы как \\".
5. Поля для невыбранных платформ оставь null.
6. ВАЖНО: убедись, что весь JSON корректен и все строки закрыты.
"""

    try:
        raw_response = ask_llm(prompt, json_mode=True)
        logger.debug(f"Raw LLM response: {raw_response}")
        clean_json = re.sub(r'```json\s*|\s*```', '', raw_response).strip()
        
        try:
        data = json.loads(clean_json)
        except json.JSONDecodeError as json_err:
            fixed_json = _fix_json_encoding(clean_json)
            try:
                data = json.loads(fixed_json)
            except json.JSONDecodeError as fixed_err:
                data = _repair_json(clean_json, fixed_err)
                if not data:
                    return {"youtube": None, "telegram": None}
        
        if data.get("youtube"):
            data["youtube"]["title"] = clean_text(data["youtube"].get("title", ""), 100)
            data["youtube"]["description"] = clean_text(data["youtube"].get("description", ""), 1000)
            tags = data["youtube"].get("tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",")]
            data["youtube"]["tags"] = [t if t.startswith("#") else f"#{t}" for t in tags[:10]]

        if data.get("telegram"):
            data["telegram"]["title"] = clean_text(data["telegram"].get("title", ""), 200)
            data["telegram"]["post"] = clean_text(data["telegram"].get("post", ""), 3500)
            
        logger.info("Контент успешно сгенерирован")
        return data
    except Exception as e:
        logger.error(f"Ошибка при массовой генерации: {e}", exc_info=True)
        return {"youtube": None, "telegram": None}