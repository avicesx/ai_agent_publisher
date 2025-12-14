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
    messages = [{"role": "user", "content": prompt}]
    
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


def generate_youtube_title(transcript: str) -> str:
    """Генерация заголовка для YouTube"""
    prompt = f"""
Сгенерируй яркий короткий заголовок для видео.

Текст:
{transcript}
"""
    return ask_llm(prompt).strip()


def generate_youtube_description(transcript: str) -> str:
    """Генерация краткого описания для YouTube"""
    prompt = f"""
Кратко опиши смысл видео одним предложением.
{transcript}
"""
    return ask_llm(prompt).strip()


def generate_tags(transcript: str) -> List[str]:
    """Генерация тегов для YouTube"""
    prompt = f"""
Выдели 5-10 ключевых тегов (хэштегов) для видео.
Формат: #тег1 #тег2 #тег3

Текст:
{transcript}
"""
    tags_text = ask_llm(prompt).strip()

    tags = [tag.strip() for tag in tags_text.split() if tag.startswith('#')]
    return tags if tags else ['#видео']


def generate_telegram_title(transcript: str) -> str:
    """Генерация заголовка для Telegram"""
    prompt = f"""
Сгенерируй привлекательный заголовок для поста.

Текст:
{transcript}
"""
    return ask_llm(prompt).strip()


def generate_telegram_post(transcript: str, post_format: str = "neutral") -> str:
    """Генерация поста для Telegram с учётом формата"""
    format_instruction = POST_FORMAT_INSTRUCTIONS.get(post_format, "")
    
    prompt = f"""
Сгенерируй связный и привлекательный пост.
10-15 предложений, человеческий стиль, без воды.
{format_instruction}

Текст:
{transcript}
"""
    return ask_llm(prompt).strip()
