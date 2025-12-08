import os
import uuid
import pathlib
import subprocess
import logging
from pydub import AudioSegment, silence
import config

logger = logging.getLogger(__name__)

class AutoCutAgent:
    def __init__(self, workdir=None, silence_thresh=None, min_silence_len=None):
        """
        :param workdir: временная директория для файлов
        :param silence_thresh: порог тишины (дБ)
        :param min_silence_len: минимальная длина тишины для вырезания (мс)
        """
        self.workdir = workdir or config.WORKDIR
        os.makedirs(self.workdir, exist_ok=True)
        self.silence_thresh = silence_thresh or config.SILENCE_THRESHOLD
        self.min_silence_len = min_silence_len or config.MIN_SILENCE_LENGTH

    async def process(self, source):
        """
        Главный метод:
        принимает путь к видео или URL.
        Возвращает путь к обработанному видео без пауз.
        """
        input_path = await self._prepare_input(source)
        audio_path = self._extract_audio(input_path)
        chunks = self._find_non_silent_chunks(audio_path)
        output_video = self._cut_video(input_path, chunks)
        return output_video

    async def _prepare_input(self, source):
        """
        Проверяет существование локального файла.
        Source должен быть путём к уже скачанному файлу.
        """
        if not os.path.exists(source):
            raise FileNotFoundError(f"Source file not found: {source}")
        return source

    def _extract_audio(self, video_path):
        """Извлекает аудио из видео."""
        audio_path = video_path + ".wav"
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-ac", str(config.AUDIO_CHANNELS), "-ar", str(config.AUDIO_RATE),
            audio_path
        ]
        logger.info(f"Running ffmpeg: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except subprocess.CalledProcessError as e:
            logger.error("FFmpeg failed")
            raise RuntimeError(f"FFmpeg failed to extract audio: {e}")
            
        if not os.path.exists(audio_path):
             raise FileNotFoundError(f"FFmpeg finished but audio file not found: {audio_path}")
             
        return audio_path


    def _find_non_silent_chunks(self, audio_path):
        """Находит участки без тишины и добавляет мягкий паддинг."""

        audio = AudioSegment.from_wav(audio_path)

        silent_ranges = silence.detect_silence(
            audio,
            min_silence_len=self.min_silence_len,
            silence_thresh=self.silence_thresh
        )

        silent_ranges = [(start, end) for start, end in silent_ranges]

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

        return padded_segments

    def _cut_video(self, input_video, segments):
        input_video = pathlib.Path(input_video).resolve().as_posix()
        output_final = pathlib.Path(self.workdir, f"output_{uuid.uuid4()}.mp4").resolve().as_posix()

        temp_list = pathlib.Path(self.workdir, f"{uuid.uuid4()}.txt").resolve().as_posix()
        chunk_files = []

        # Вырезаем куски (точная нарезка, гарантированное видео)
        for i, (start, end) in enumerate(segments):
            duration = end - start

            out_file = pathlib.Path(self.workdir, f"chunk_{i}.mp4").resolve().as_posix()

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", input_video,
                "-t", str(duration),
                "-c:v", config.FFMPEG_VIDEO_CODEC,
                "-preset", config.FFMPEG_PRESET,
                "-c:a", config.FFMPEG_AUDIO_CODEC,
                out_file
            ]

            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            chunk_files.append(out_file)

        # Создаём concat list
        with open(temp_list, "w", encoding="utf-8") as f:
            for fp in chunk_files:
                f.write(f"file '{fp}'\n")

        # Склеиваем
        cmd_concat = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", temp_list,
            "-c:v", config.FFMPEG_VIDEO_CODEC,
            "-preset", config.FFMPEG_PRESET,
            "-c:a", config.FFMPEG_AUDIO_CODEC,
            output_final
        ]

        subprocess.run(cmd_concat, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return output_final
