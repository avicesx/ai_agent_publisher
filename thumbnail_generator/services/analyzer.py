import os
import cv2
import numpy as np
from PIL import Image
import logging

logger = logging.getLogger("thumbnail_generator")


def clear_output_dir(out_dir):
    if not os.path.exists(out_dir):
        return

    for file in os.listdir(out_dir):
        if file.lower().endswith((".jpg", ".png", ".jpeg")):
            try:
                os.remove(os.path.join(out_dir, file))
            except OSError:
                pass


def frame_to_rgb(frame):
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def calc_histogram(frame, resize=(320, 180), bins=(8, 8, 8)):
    small = cv2.resize(frame, resize, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, bins,
                        [0, 180, 0, 256, 0, 256])
    hist = cv2.normalize(hist, hist).flatten()
    return hist


def hist_distance(h1, h2):
    # Используем корреляцию (чем ближе к 1 — тем похожи), преобразуем в расстояние
    return 1.0 - cv2.compareHist(h1.astype('float32'), h2.astype('float32'), cv2.HISTCMP_CORREL)


def sharpness_score(gray):
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def brightness_score(gray):
    return float(np.mean(gray)) / 255.0


def contrast_score(gray):
    return float(np.std(gray)) / 128.0


def saliency_score(frame):
    try:
        saliency = cv2.saliency.StaticSaliencyFineGrained_create()
        (success, sal_map) = saliency.computeSaliency(frame)
        if success:
            return float(np.mean(sal_map))
    except Exception:
        pass
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 100, 200)
    return float(np.mean(edges) / 255.0)


def face_count(frame, face_cascade):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4,
                                          minSize=(30, 30), flags=cv2.CASCADE_SCALE_IMAGE)
    return len(faces)


def detect_scenes(video_path, frame_step=10, hist_thresh=0.45, max_frames=None):
    """
    Проход по видео с шагом frame_step; возвращает список индексов кадров, которые отмечают
    границы сцен (индекс кадра в исходном потоке).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("Не удалось открыть видео: " + video_path)

    hist_prev = None
    scene_boundaries = [0]  # первая сцена начинается с 0
    idx = 0
    frames_read = 0

    while True:
        ret = cap.grab()
        if not ret:
            break
        if idx % frame_step == 0:
            ret2, frame = cap.retrieve()
            if not ret2:
                break
            h = calc_histogram(frame)
            if hist_prev is not None:
                dist = hist_distance(h, hist_prev)
                if dist > hist_thresh:
                    scene_boundaries.append(idx)
            hist_prev = h
            frames_read += 1
            if max_frames and frames_read >= max_frames:
                break
        idx += 1

    cap.release()
    # также добавить конец видео в списки сцен
    return scene_boundaries


def sample_candidates(video_path, scene_boundaries, frame_step=5, per_scene_max=3):
    """Для каждой сцены берем кадры: центр сцены + несколько случайных/этапных с шагом frame_step.
    Возвращает список кортежей (frame_idx, frame_image)
    """
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    candidates = []

    # добавим конец видео индекс
    boundaries = scene_boundaries[:] + [total_frames]

    for i in range(len(boundaries)-1):
        start = boundaries[i]
        end = boundaries[i+1]
        if end <= start:
            continue
        center = (start + end) // 2
        # добавляем центр
        idxs = [center]
        # добавляем кадры с шагом внутри сцены
        length = end - start
        step = max(1, length // (per_scene_max + 1))
        p = start + step
        while p < end and len(idxs) < per_scene_max:
            idxs.append(p)
            p += step

        # читать кадры по индексам
        for fi in idxs:
            if fi < 0 or fi >= total_frames:
                continue
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ret, frame = cap.read()
            if not ret:
                continue
            candidates.append((fi, frame.copy()))
    cap.release()
    return candidates


def score_candidates(candidates, face_cascade=None, weights=None):
    if weights is None:
        weights = {
            'sharpness': 1.2,
            'brightness': 0.6,
            'contrast': 0.6,
            'saliency': 1.0,
            'faces': 1.5
        }
    scored = []
    for (fi, frame) in candidates:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharp = sharpness_score(gray)
        bright = brightness_score(gray)
        cont = contrast_score(gray)
        sal = saliency_score(frame)
        faces = 0
        if face_cascade is not None:
            try:
                faces = face_count(frame, face_cascade)
            except Exception:
                faces = 0
                
        sharp_norm = np.tanh(sharp / 100.0)
        bright_norm = bright
        cont_norm = np.tanh(cont)
        sal_norm = sal
        faces_norm = min(faces, 3) / 3.0

        score = (weights['sharpness'] * sharp_norm +
                 weights['brightness'] * bright_norm +
                 weights['contrast'] * cont_norm +
                 weights['saliency'] * sal_norm +
                 weights['faces'] * faces_norm)
        scored.append({
            'frame_idx': fi,
            'frame': frame,
            'score': float(score),
            'sharp_norm': float(sharp_norm),
            'bright_norm': float(bright_norm),
            'cont_norm': float(cont_norm),
            'sal_norm': float(sal_norm),
            'faces_norm': float(faces_norm)
        })

    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored


def filter_similar(scored, n_select=3, hist_sim_thresh=0.25):
    """
    Убирает слишком похожие кадры (по гистограмме HSV).
    Возвращает n_select лучших уникальных.
    """
    selected = []
    histograms = []
    for item in scored:
        if len(selected) >= n_select:
            break
        h = calc_histogram(item['frame'])
        duplicate = False
        for existing_h in histograms:
            if hist_distance(h, existing_h) < hist_sim_thresh:
                duplicate = True
                break
        if not duplicate:
            selected.append(item)
            histograms.append(h)
    return selected


def save_thumbnails(selected, out_dir, prefix="thumb"):
    """Сохраняет обложки и возвращает метаданные"""
    os.makedirs(out_dir, exist_ok=True)
    saved_data = []
    for i, item in enumerate(selected):
        path = os.path.join(out_dir, f"{prefix}_{i+1:02d}_frame{item['frame_idx']}.jpg")
        # сохранить в RGB через PIL, чтобы сохранить качество
        rgb = cv2.cvtColor(item['frame'], cv2.COLOR_BGR2RGB)
        Image.fromarray(rgb).save(path, quality=90)
        
        # Возвращаем метаданные
        saved_data.append({
            'path': path,
            'frame_idx': item['frame_idx'],
            'score': item['score']
        })
    return saved_data


def run_agent(video_path, out_dir='thumbs', n_thumbs=3,
              frame_step_scene=10, frame_step_sample=5,
              scene_hist_thresh=0.45, per_scene_max=3):
    """Главная функция генерации обложек"""
    # загрузка каскада лиц 
    face_cascade = None
    try:
        casc_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if os.path.exists(casc_path):
            face_cascade = cv2.CascadeClassifier(casc_path)
    except Exception:
        face_cascade = None

    logger.info("Обнаружение границ сцен...")
    scenes = detect_scenes(video_path, frame_step=frame_step_scene, hist_thresh=scene_hist_thresh)
    logger.info(f"Найдено {len(scenes)} границ сцен")

    logger.info("Выборка кандидатов...")
    candidates = sample_candidates(video_path, scenes, frame_step=frame_step_sample, per_scene_max=per_scene_max)
    logger.info(f"Собрано {len(candidates)} кандидатов")

    logger.info("Оценка кандидатов...")
    scored = score_candidates(candidates, face_cascade=face_cascade)

    logger.info("Фильтрация похожих кадров...")
    selected = filter_similar(scored, n_select=n_thumbs, hist_sim_thresh=0.22)
    
    clear_output_dir(out_dir)

    saved_data = save_thumbnails(selected, out_dir)
    logger.info(f"Сохранено {len(saved_data)} обложек")
    for item in saved_data:
        logger.info(f"  {item['path']} (frame: {item['frame_idx']}, score: {item['score']:.2f})")
    
    return saved_data