import logging
from llama_cpp import Llama
from typing import List
import config

logger = logging.getLogger(__name__)

llm = None


def load_llm():
    """Загрузка GGUF модели при старте сервиса"""
    global llm
    logger.info(f"Загрузка модели из {config.MODEL_PATH}...")
    llm = Llama(
        model_path=config.MODEL_PATH,
        n_ctx=config.N_CTX,
        n_threads=config.N_THREADS,
        n_gpu_layers=config.N_GPU_LAYERS,
        verbose=False 
    )
    logger.info("Модель успешно загружена")


def ask_llm(prompt: str) -> str:
    """Генерация текста через LLM"""
    messages = [
        {"role": "system", "content": "Ты — помощник по созданию контента. Пиши только на русском языке. Твоя задача — переписать или кратко изложить предоставленный текст в нужном формате. Не пиши вводных фраз, отвечай сразу готовым текстом."},
        {"role": "user", "content": prompt}
    ]
    
    output = llm.create_chat_completion(
        messages=messages,
        max_tokens=config.MAX_TOKENS,
        temperature=config.TEMPERATURE,
        top_p=config.TOP_P
    )
    
    return output["choices"][0]["message"]["content"]


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


def clean_text(text: str, max_chars: int = 4000) -> str:
    """Очистка текста от мусора, вводных фраз и заголовков секций + лимит по длине"""
    lines = text.strip().split('\n')
    cleaned_lines = []
    
    # Фразы, которые точно являются мусором, если идут в начале
    junk_prefixes = (
        "Вот ", "Конечно", "Задание", "Ваше сообщение", 
        "Транскрипция", "Текст видео", "Информативный пост",
        "---", "###", "Заголовок:", "Описание:", "Пост:",
        "Понятно", "Хорошо", "ОК", "Окей", "Извините"
    )
    
    # Секции, которые модель любит добавлять
    unwanted_headers = (
        "Интересные факты", "Заключение", "Итог", "Важное",
        "Ключевые моменты", "Основные идеи", "Ваше сообщение"
    )

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            cleaned_lines.append("")
            continue
            
        # Пропускаем разделители и технические строки
        if any(line_stripped.startswith(prefix) for prefix in junk_prefixes):
            continue
            
        # Пропускаем заголовки секций (с двоеточием в конце или просто в начале)
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


def generate_youtube_title(transcript: str, post_format: str = "neutral", custom_prompt: str = None) -> str:
    """Генерация заголовка для YouTube"""
    
    if custom_prompt:
        instruction = f"Инструкция: {custom_prompt}"
    else:
        instruction = POST_FORMAT_INSTRUCTIONS.get(post_format, "")

    prompt = f"""
Текст видео:
{transcript}

{instruction}

Задание: Придумай 1 короткий и яркий заголовок для этого видео на русском языке (до 60 символов).
Правила:
- Без кавычек, без звездочек
- Без вступительных фраз
- Только сам текст заголовка и ничего больше
"""
    return clean_text(ask_llm(prompt), max_chars=100)


def generate_youtube_description(transcript: str, post_format: str = "neutral", custom_prompt: str = None) -> str:
    """Генерация краткого описания для YouTube"""
    
    if custom_prompt:
        instruction = f"Инструкция: {custom_prompt}"
    else:
        instruction = POST_FORMAT_INSTRUCTIONS.get(post_format, "")

    prompt = f"""
Текст видео:
{transcript}

{instruction}

Задание: Напиши описание для YouTube Shorts (на русском языке).
Правила:
- Максимум 3 предложения, до 300 символов
- Разделяй абзацы двойным переносом строки
- БЕЗ заголовков секций (не пиши "Описание", "Итог" и т.д.)
- БЕЗ вступительных фраз (не пиши "Вот текст")
- Пиши только текст описания
"""
    return clean_text(ask_llm(prompt), max_chars=1000)


def generate_tags(transcript: str) -> List[str]:
    """Генерация тегов для YouTube"""
    prompt = f"""
Текст видео:
{transcript}

Задание: Напиши 7 релевантных хэштегов для этого видео через пробел.
Правила:
- Только теги на русском языке
- Каждый тег начинается с #
- Никакого другого текста, только теги
"""
    tags_text = ask_llm(prompt).strip()
    tags = []
    for word in tags_text.replace(',', ' ').split():
        tag = word.strip().strip('"').strip('*')
        if not tag:
            continue
        if not tag.startswith('#'):
            tag = '#' + tag
        tags.append(tag)
        
    return tags[:10] if tags else ['#видео', '#shorts']


def generate_telegram_title(transcript: str, post_format: str = "neutral", custom_prompt: str = None) -> str:
    """Генерация заголовка для Telegram"""
    if custom_prompt:
        instruction = f"Инструкция: {custom_prompt}"
    else:
        instruction = POST_FORMAT_INSTRUCTIONS.get(post_format, "")

    prompt = f"""
Текст видео:
{transcript}

{instruction}

Задание: Придумай цепляющий заголовок для поста в Telegram (до 100 символов).
Правила:
- Без кавычек и звездочек
- Без вводных фраз
- Только текст заголовка
"""
    return clean_text(ask_llm(prompt), max_chars=200)


def generate_telegram_post(transcript: str, post_format: str = "neutral", custom_prompt: str = None) -> str:
    """Генерация поста для Telegram с учётом формата"""
    
    if custom_prompt:
        instruction = f"Инструкция: {custom_prompt}"
    else:
        instruction = POST_FORMAT_INSTRUCTIONS.get(post_format, "")
    
    prompt = f"""
Текст для переработки:
{transcript}

{instruction}

Задание: Напиши полноценный пост для Telegram на основе текста выше (на русском языке).
Правила:
- Разделяй текст на абзацы двойным переносом строки (\n\n)
- До 3000 символов
- БЕЗ заголовков секций (не пиши "Заключение", "Факты")
- БЕЗ вступительных фраз (не пиши "Вот пост")
- НЕ ПОВТОРЯЙ исходный текст целиком
- Пиши только сам пост, начни сразу с сути
"""
    return clean_text(ask_llm(prompt), max_chars=3500)
