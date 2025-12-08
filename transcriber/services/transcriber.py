import whisper
import logging

logger = logging.getLogger(__name__)


class WhisperTranscriber:
    def __init__(self, model_size: str = "medium"):
        self.model_size = model_size
        self.model = self.load_model()

    def load_model(self):
        logger.info(f"Загрузка модели Whisper: {self.model_size}")
        try:
            model = whisper.load_model(self.model_size)
            logger.info("Модель Whisper загружена")
            return model
        except Exception as e:
            logger.error(f"Ошибка загрузки модели: {e}")
            raise

    def transcribe(self, audio_path: str) -> str:
        """
        Транскрибирует аудио с помощью whisper
        """
        try:
            result = self.model.transcribe(audio_path, language="ru")
            text = result["text"]
            logger.info("Транскрибация завершена")
            return text
        except Exception as e:
            logger.error(f"Ошибка транскрибации: {e}")
            raise