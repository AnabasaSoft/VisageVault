# thumbnail_generator.py
from PIL import Image, ImageOps, UnidentifiedImageError
from pathlib import Path
import os
import hashlib
import shutil
import threading
import cv2
import rawpy
import paths

THUMBNAIL_SIZE = (128, 128)       # Tamaño de visualización por defecto (pestaña Personas)
CACHE_THUMBNAIL_SIZE = (256, 256)  # Tamaño guardado en caché: el zoom máximo, para que no se pixele

# Carpeta versionada: si cambia el formato de las miniaturas (tamaño, orientación...)
# se usa una nueva y la anterior se borra, para que todas se regeneren.
CACHE_SUBDIR = "local_snapshot_cache_v2"
OLD_CACHE_SUBDIRS = ("local_snapshot_cache",)
_old_cache_cleaned = False
_old_cache_lock = threading.Lock()

def get_cache_dir():
    """Carpeta de caché de miniaturas locales."""
    global _old_cache_cleaned
    if not _old_cache_cleaned:
        with _old_cache_lock:
            if not _old_cache_cleaned:
                for old in OLD_CACHE_SUBDIRS:
                    shutil.rmtree(os.path.join(paths.cache_dir(), old), ignore_errors=True)
                _old_cache_cleaned = True
    return Path(paths.cache_subdir(CACHE_SUBDIR))

def get_thumbnail_path(original_filepath: str) -> Path:
    """Genera la ruta donde se guardará la miniatura."""
    thumb_dir = get_cache_dir()
    file_hash = hashlib.sha256(original_filepath.encode('utf-8')).hexdigest()
    return thumb_dir / f"{file_hash}.jpg"

def generate_image_thumbnail(original_filepath: str) -> str | None:
    original_filepath = Path(original_filepath)
    if not original_filepath.is_file(): return None

    # Usamos la nueva función dinámica
    thumbnail_path = get_thumbnail_path(str(original_filepath))

    if thumbnail_path.exists():
        return str(thumbnail_path)

    try:
        img_to_process = None
        try:
            img_pil = Image.open(original_filepath)
            # JPEG: decodificar ya reducido (mucho más rápido en fotos grandes)
            img_pil.draft("RGB", (CACHE_THUMBNAIL_SIZE[0] * 2, CACHE_THUMBNAIL_SIZE[1] * 2))
            img_pil.load()
            # Aplicar la orientación EXIF (fotos hechas en vertical)
            img_to_process = ImageOps.exif_transpose(img_pil)
        except (UnidentifiedImageError, IOError):
            try:
                with rawpy.imread(str(original_filepath)) as raw:
                    rgb = raw.postprocess(use_camera_wb=True)
                    img_to_process = Image.fromarray(rgb)
            except Exception:
                return None

        if not img_to_process: return None

        if img_to_process.mode in ('RGBA', 'LA') or (img_to_process.mode == 'P' and 'transparency' in img_to_process.info):
            background = Image.new('RGB', img_to_process.size, (255, 255, 255))
            if img_to_process.mode == 'P':
                img_to_process = img_to_process.convert('RGBA')
            background.paste(img_to_process, mask=img_to_process.split()[3])
            img_to_process = background
        elif img_to_process.mode != 'RGB':
            img_to_process = img_to_process.convert('RGB')

        # Redimensionar antes de guardar para ahorrar espacio
        img_to_process.thumbnail(CACHE_THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        img_to_process.save(thumbnail_path, "JPEG", quality=85)
        img_to_process.close()

        return str(thumbnail_path)

    except Exception as e:
        print(f"Error thumbnail imagen: {e}")
        return None

def generate_video_thumbnail(original_filepath: str) -> str | None:
    original_filepath = Path(original_filepath)
    if not original_filepath.is_file(): return None

    thumbnail_path = get_thumbnail_path(str(original_filepath))

    if thumbnail_path.exists():
        return str(thumbnail_path)

    try:
        cap = cv2.VideoCapture(str(original_filepath))
        success, frame = cap.read()
        cap.release()

        if not success: return None

        h, w = frame.shape[:2]
        if h > w:
            new_h = CACHE_THUMBNAIL_SIZE[1]
            new_w = int(w * (new_h / h))
        else:
            new_w = CACHE_THUMBNAIL_SIZE[0]
            new_h = int(h * (new_w / w))

        resized_frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(thumbnail_path), resized_frame)

        return str(thumbnail_path)

    except Exception as e:
        print(f"Error thumbnail vídeo: {e}")
        return None
