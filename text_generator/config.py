import os

# путь к модели
MODEL_PATH = os.getenv("MODEL_PATH", "/app/llm_models/qwen2.5-1.5b-instruct-q4_k_m.gguf") # более легкая
# MODEL_PATH = os.getenv("MODEL_PATH", "/app/llm_models/qwen2-7b-instruct-q4_k_m.gguf")

# параметры LLM
N_CTX = int(os.getenv("N_CTX", "4096"))
N_THREADS = int(os.getenv("N_THREADS", "6"))
N_GPU_LAYERS = int(os.getenv("N_GPU_LAYERS", "-1"))

# параметры генерации
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "512"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.4"))
TOP_P = float(os.getenv("TOP_P", "0.8"))

# логирование
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
