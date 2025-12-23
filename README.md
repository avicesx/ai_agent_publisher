# AI Agent Publisher

> Telegram бот для автоматической обработки видео: удаление пауз, транскрибация, проверка соответствия политике YouTube и генерация контента.

[![Docker](https://img.shields.io/badge/Docker-20.10%2B-blue.svg)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Latest-green.svg)](https://fastapi.tiangolo.com/)

---

## 📋 Требования

- **Docker Desktop** (версия 20.10+) - [Скачать](https://www.docker.com/products/docker-desktop)
- **Docker Compose** (версия 2.0+)
- **Git**
- **Минимум 16 GB RAM** (на 8 GB не работает)
- **50 GB свободного места** на диске
- **NVIDIA GPU** (опционально, для ускорения) - GTX 1060 6GB или выше

---

## 🚀 Быстрая установка

### Шаг 1: Клонирование репозитория

```bash
git clone <URL_вашего_репозитория>
cd ai_agent_publisher
```

### Шаг 2: Настройка переменных окружения

Создайте файл `.env`:

```bash
# Windows PowerShell
Copy-Item .env.example .env

# Linux/Mac
cp .env.example .env
```

Откройте `.env` и заполните:

```env
BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
```

**Как получить токен бота:**
1. Найдите [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot`
3. Следуйте инструкциям
4. Скопируйте токен в `.env`

**Как получить API_ID и API_HASH:**
1. Перейдите на [my.telegram.org](https://my.telegram.org/auth)
2. Войдите с номером телефона
3. Создайте приложение (API development tools)
4. Скопируйте `api_id` и `api_hash` в `.env`

### Шаг 3: Скачивание LLM модели

Скачайте одну из моделей Qwen для `text_generator`:

- **[Qwen2.5 1.5B](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/blob/main/qwen2.5-1.5b-instruct-q4_k_m.gguf)** (Легкая, быстрая (рекомендуется для начала))
- **[Qwen2 7B](https://huggingface.co/Qwen/Qwen2-7B-Instruct-GGUF/blob/main/qwen2-7b-instruct-q4_k_m.gguf)** (Тяжелая, качественнее)

Поместите скачанный файл в папку `llm_models/`:

```bash
# Windows PowerShell
New-Item -Path llm_models -ItemType Directory -Force

# Linux/Mac
mkdir -p llm_models
```

> **Примечание**: Папка `data/` создается автоматически при запуске Docker

### Шаг 3.1: Скачивание моделей RuBERT

Скачайте модели RuBERT для `checking_terms`:

1. **[RuBERT-tiny2](https://huggingface.co/cointegrated/rubert-tiny2)** (легкая, быстрая)
2. **[RuBERT-base-cased](https://huggingface.co/DeepPavlov/rubert-base-cased)** (тяжелая, точнее)

Поместите модели в `checking_terms/models/`:

```bash
# Структура должна быть такой:
checking_terms/
└── models/
    ├── cointegrated_rubert_tiny2/
    │   ├── config.json
    │   ├── model.safetensors
    │   ├── tokenizer.json
    │   └── ...
    └── rubert-base-cased/
        ├── config.json
        ├── model.safetensors
        ├── tokenizer.json
        └── ...
```

> **Совет**: Используйте `git clone` для скачивания моделей:
> ```bash
> cd checking_terms/models
> git clone https://huggingface.co/cointegrated/rubert-tiny2 cointegrated_rubert_tiny2
> git clone https://huggingface.co/DeepPavlov/rubert-base-cased rubert-base-cased
> ```

### Шаг 4: Запуск

```bash
docker-compose up --build
```

Первый запуск займет **15-20 минут** (загрузка Docker образов и ML моделей).

---

## ✅ Проверка работы

### 1. Проверьте контейнеры

```bash
docker ps
```

Должно быть запущено **8 контейнеров**:
- `ai_publisher_telegram_api` ← Local Bot API Server (файлы до 2 ГБ)
- `ai_publisher_backend`
- `ai_publisher_orchestrator`
- `ai_publisher_silence_cutter`
- `ai_publisher_transcriber`
- `ai_publisher_checking_terms`
- `ai_publisher_text_generator`
- `ai_publisher_thumbnail_generator`

### 2. Проверьте логи

Убедитесь, что нет ошибок:

```bash
# Все сервисы
docker-compose logs -f

# Конкретный сервис
docker-compose logs -f backend
```

### 3. Тестирование бота

1. Откройте Telegram и найдите вашего бота
2. Отправьте команду `/start`
3. Нажмите **"⚙️ Настройки"** для выбора платформы и формата поста
4. Нажмите кнопку **"🎬 Обработать видео"**
5. Загрузите видео (до 2 ГБ) или отправьте ссылку
6. Дождитесь обработки (несколько минут)

---

## 🏗️ Структура проекта

```
ai_agent_publisher/
│
├── backend/                          # Telegram Bot
│   ├── main.py                       # Основной файл бота
│   ├── config.py                     # Конфигурация
│   ├── services/                     # Сервисы
│   │   └── orchestrator_client.py   # Клиент для общения с orchestrator
│   ├── models/                       # Модели данных
│   ├── utils/                        # Утилиты
│   ├── requirements.txt
│   └── Dockerfile
│
├── orchestrator/                     # Координатор сервисов
│   ├── main.py                       # Основной файл
│   ├── config.py                     # Конфигурация сервисов
│   ├── services/                     # Бизнес-логика
│   ├── models/                       # Модели данных
│   ├── requirements.txt
│   └── Dockerfile
│
├── silence_cutter/                   # Удаление пауз (FFmpeg)
│   ├── app.py                        # FastAPI приложение
│   ├── agency.py                     # Основная логика обработки
│   ├── config.py                     # Конфигурация
│   ├── routes/                       # API endpoints
│   │   └── video.py                 # Endpoint для обработки видео
│   ├── services/                     # Сервисы обнаружения пауз
│   ├── models/                       # Модели данных
│   ├── utils/                        # Утилиты
│   ├── requirements.txt
│   └── Dockerfile
│
├── transcriber/                      # Транскрибация (Whisper)
│   ├── main.py                       # Основной файл
│   ├── config.py                     # Конфигурация
│   ├── routes/                       # API endpoints
│   ├── services/                     # Сервис транскрибации
│   ├── models/                       # Модели данных
│   ├── requirements.txt
│   └── Dockerfile
│
├── checking_terms/                   # Проверка политики YouTube (RuBERT)
│   ├── main.py                       # Основной файл
│   ├── config.py                     # Конфигурация
│   ├── core/                         # Ядро системы проверки
│   ├── services/                     # Сервисы проверки
│   │   ├── base_checker.py          # Базовый класс проверки
│   │   ├── checker_registry.py      # Реестр проверок
│   │   └── platforms/               # Проверки по платформам (YouTube)
│   ├── routes/                       # API endpoints
│   ├── models/                       # Модели RuBERT (rubert-tiny2, rubert-base)
│   ├── requirements.txt
│   └── Dockerfile
│
├── text_generator/                   # Генерация текста (Qwen)
│   ├── main.py                       # Основной файл
│   ├── config.py                     # Настройки модели Qwen
│   ├── services/                     # Сервисы генерации
│   ├── models/                       # Pydantic модели
│   ├── requirements.txt
│   └── Dockerfile
│
├── thumbnail_generator/              # Генерация обложек (OpenCV)
│   ├── main.py                       # Основной файл
│   ├── config.py                     # Конфигурация
│   ├── services/                     # Сервисы выбора кадров
│   ├── models/                       # Модели данных
│   ├── requirements.txt
│   └── Dockerfile
│
├── data/                             # Shared volume (создается автоматически)
│   ├── uploads/                      # Загруженные видео
│   ├── workdir/                      # Промежуточные файлы
│   └── outputs/                      # Готовые результаты
│
├── llm_models/                       # GGUF модели для text_generator
│   └── qwen2.5-1.5b-instruct-q4_k_m.gguf
│
├── docker-compose.yml                # Конфигурация всех сервисов
├── .env                              # Переменные окружения (НЕ коммитится!)
├── .env.example                      # Шаблон конфигурации
└── README.md
```

---

## � Workflow обработки видео

1. Пользователь отправляет видео боту в Telegram
2. **Backend** загружает видео в `data/uploads/`
3. **Backend** отправляет запрос на **Orchestrator**
4. **Orchestrator** последовательно вызывает:
   - **Silence Cutter**: удаляет паузы → `data/workdir/`
   - **Transcriber**: создает транскрипцию → `data/outputs/`
   - **Checking Terms**: проверяет на нарушения политики
   - **Text Generator**: генерирует описание и хэштеги
   - **Thumbnail Generator**: создает обложки видео
5. **Orchestrator** возвращает результат в **Backend**
6. **Backend** отправляет обработанное видео пользователю

---

## 🔧 Управление сервисами

### Остановка

```bash
docker-compose down
```

### Перезапуск после изменений

```bash
docker-compose up --build
```

### Просмотр логов

```bash
# Все сервисы
docker-compose logs -f

# Конкретный сервис
docker-compose logs -f backend
```

### Войти в контейнер для отладки

```bash
docker exec -it ai_publisher_backend bash
```

---

## 🛠️ Работа без GPU

Если у вас нет NVIDIA GPU, закомментируйте секции `deploy` в `docker-compose.yml` для `transcriber` и `text_generator`:

```yaml
# deploy:
#   resources:
#     reservations:
#       devices:
#         - driver: nvidia
#           count: 1
#           capabilities: [gpu]
```

Модели Whisper и Qwen будут работать на CPU (в 10-20 раз медленнее).

---

## ⚙️ Изменение модели Whisper

В `docker-compose.yml`, секция `transcriber`:

```yaml
environment:
  - MODEL_SIZE=tiny    # tiny, base, small, medium, large
```

**Рекомендации:**
- `tiny` / `base`: быстро, низкая точность
- `small` / `medium`: баланс (по умолчанию `medium`)
- `large`: максимальная точность, медленно

---

## 📦 Потребление ресурсов

### Минимальные требования
- **RAM**: 16 GB
- **Disk**: 50 GB SSD
- **CPU**: 8 ядер

### Рекомендуемые требования
- **RAM**: 32 GB
- **GPU**: NVIDIA RTX 3060 12GB или выше
- **CPU**: 16 ядер

### Ориентировочное время обработки (видео 10 минут)

**С GPU:**
- Silence Cutter: ~2 минуты
- Transcriber: ~10 минут
- Checking Terms: ~1 минута
- Text Generator: ~5 минут
- Thumbnail Generator: ~30 секунд
- **Итого: ~18 минут**

**Без GPU (CPU):**
- Transcriber: ~1.5 часа
- Text Generator: ~30 минут
- **Итого: ~2-3 часа**

---

## 🐛 Решение проблем

### Ошибка: `Cannot connect to the Docker daemon`

**Решение**: Убедитесь, что Docker Desktop запущен.

### Ошибка: `nvidia-container-runtime not found`

**Решение**: Установите [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) или отключите GPU в `docker-compose.yml`.

### Бот не отвечает

1. Проверьте, что контейнер `backend` запущен: `docker ps`
2. Проверьте логи: `docker-compose logs backend`
3. Убедитесь, что `BOT_TOKEN` правильный в `.env`

### Долгая обработка видео

Это нормально для больших видео или работы на CPU:
- Transcriber (Whisper): ~1x скорости видео на GPU, ~10x на CPU
- Text Generator (Qwen): до 5 минут на GPU, до 30 минут на CPU

### Не хватает места на диске

Очистите старые Docker образы и volumes:

```bash
docker system prune -a
docker volume prune
```

---

## 🎯 Технологии

- **Python 3.11**
- **FastAPI** - API endpoints
- **pyTelegramBotAPI** - Telegram интеграция
- **OpenAI Whisper** - транскрибация
- **Transformers (Hugging Face)** - RuBERT модели
- **llama.cpp** - LLM inference для Qwen
- **OpenCV** - генерация обложек
- **FFmpeg** - обработка видео
- **Docker & Docker Compose**
