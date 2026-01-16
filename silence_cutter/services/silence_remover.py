from typing import List, Tuple
import logging
from pydub import AudioSegment, silence
import config
from utils import extract_audio, cut_video_segments, concat_videos

logger = logging.getLogger(__name__)


class SilenceCutter:
    """
    Сервис для удаления пауз из видео
    """
    
    def __init__(
        self, 
        workdir: str = None,
        silence_thresh: int = None,
        min_silence_len: int = None
    ):
        """
        Args:
            workdir: Рабочая директория
            silence_thresh: Порог тишины в дБ
            min_silence_len: Минимальная длительность тишины в мс
        """
        self.workdir = workdir or config.WORKDIR
        self.silence_thresh = silence_thresh or config.SILENCE_THRESHOLD
        self.min_silence_len = min_silence_len or config.MIN_SILENCE_LENGTH
        
        logger.info(
            f"Инициализация SilenceCutter: "
            f"workdir={self.workdir}, "
            f"silence_thresh={self.silence_thresh}dB, "
            f"min_silence_len={self.min_silence_len}ms"
        )
    
    async def process(self, input_path: str) -> str:
        """
        Главный метод удаления пауз
        Args:
            input_path: Путь к видеофайлу
        Returns:
            Путь к обработанному видео без пауз
        """
        logger.info(f"Начало удаления пауз: {input_path}")
        audio_path = extract_audio(input_path)
        
        segments = self._find_non_silent_chunks(audio_path)
        logger.info(f"Найдено {len(segments)} активных сегментов")
        
        chunk_files = cut_video_segments(input_path, segments, self.workdir)
        
        output_video = concat_videos(chunk_files, self.workdir)
        
        logger.info(f"Обработка завершена: {output_video}")
        return output_video
    
    def _find_non_silent_chunks(self, audio_path: str) -> List[Tuple[float, float]]:
        """
        Находит участки без тишины в аудио файле
        Args:
            audio_path: Путь к аудио файлу
        Returns:
            Список кортежей (start, end) в секундах для активных сегментов
        """
        logger.info("Анализ аудио для обнаружения тишины")
        
        audio = AudioSegment.from_wav(audio_path)
        
        silent_ranges = silence.detect_silence(
            audio,
            min_silence_len=self.min_silence_len,
            silence_thresh=self.silence_thresh
        )
        
        logger.info(f"Обнаружено {len(silent_ranges)} тихих участков")
        
        non_silent = []
        last_end = 0
        
        for start, end in silent_ranges:
            if last_end < start:
                non_silent.append((last_end, start))
            last_end = end
        
        if last_end < len(audio):
            non_silent.append((last_end, len(audio)))
        
        padded_segments = []
        for start_ms, end_ms in non_silent:
            start_ms = max(0, start_ms - config.START_PADDING)
            end_ms = min(len(audio), end_ms + config.END_PADDING)
            
            padded_segments.append((start_ms / 1000, end_ms / 1000))
        
        logger.info(f"Подготовлено {len(padded_segments)} сегментов с паддингами")
        return padded_segments
