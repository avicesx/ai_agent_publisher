import os

# пути к моделям
TINY2_MODEL_PATH = os.getenv("TINY2_MODEL_PATH", "./models/cointegrated_rubert_tiny2")
BASE_MODEL_PATH = os.getenv("BASE_MODEL_PATH", "./models/rubert-base-cased")

# параметры анализа
DECISION_THRESHOLD = float(os.getenv("DECISION_THRESHOLD", "0.6"))
WEIGHT_TINY2 = float(os.getenv("WEIGHT_TINY2", "0.7"))
WEIGHT_BASE = float(os.getenv("WEIGHT_BASE", "0.3"))
MAX_LENGTH = int(os.getenv("MAX_LENGTH", "512"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
