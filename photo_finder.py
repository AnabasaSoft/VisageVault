# photo_finder.py
import os
import threading
import time
from pathlib import Path

import paths

# --- CONFIGURACIÓN DE EXTENSIONES A BUSCAR ---
IMAGE_EXTENSIONS = (
    # Formatos web/estándar
    '.jpg', '.jpeg', '.png', '.tiff', '.webp', '.heic', '.heif',

    # Formatos RAW (añadidos)
    '.nef', '.cr2', '.cr3', '.crw',  # Nikon, Canon
    '.arw', '.srf',                 # Sony
    '.orf',                         # Olympus
    '.rw2',                         # Panasonic
    '.raf',                         # Fujifilm
    '.pef', '.dng',                 # Pentax, Adobe
    '.raw'                          # Genérico
)
VIDEO_EXTENSIONS = (
    '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.mpeg', '.mpg'
)

# Las fotos y los vídeos de una misma tanda de escaneo comparten un único
# recorrido del disco: el primero que llega lo hace y el segundo reutiliza
# el resultado (los dos workers corren en paralelo).
_scan_lock = threading.Lock()
_shared_scans = {}  # (carpeta, scan_id) -> (fotos, vídeos)


def _excluded_dirs():
    """Carpetas de la propia app que nunca deben indexarse (caché y caja fuerte)."""
    try:
        return {os.path.normpath(paths.cache_dir()), os.path.normpath(paths.safe_dir())}
    except OSError:
        return set()


def _walk_media(directory_path, should_stop=None):
    """
    Un solo recorrido del disco. Devuelve (fotos, vídeos, completo).
    Si should_stop() devuelve True se interrumpe y completo=False: el
    resultado no debe usarse para borrar nada.
    """
    photos, videos = [], []
    excluded = _excluded_dirs()
    count = 0

    for dirpath, dirnames, filenames in os.walk(directory_path):
        # No descender a la caché ni a la caja fuerte de la app
        dirnames[:] = [d for d in dirnames if os.path.normpath(os.path.join(dirpath, d)) not in excluded]

        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                target = photos
            elif ext in VIDEO_EXTENSIONS:
                target = videos
            else:
                continue
            full_path = os.path.join(dirpath, name)
            if os.path.isfile(full_path):  # Descarta enlaces rotos, FIFOs, etc.
                target.append(full_path)

        count += 1
        if count % 20 == 0:
            if should_stop and should_stop():
                return photos, videos, False
            time.sleep(0.001)  # Ceder la CPU a la interfaz

    return photos, videos, True


def scan_media(directory_path: str, should_stop=None, scan_id=None):
    """
    Devuelve (fotos, vídeos) de la carpeta, recursivamente.
    Con el mismo scan_id, el segundo que lo pide reutiliza el recorrido del primero.
    """
    if not os.path.isdir(directory_path):
        return [], []
    key = (os.path.normpath(directory_path), scan_id)

    with _scan_lock:
        if scan_id is not None and key in _shared_scans:
            return _shared_scans.pop(key)

        photos, videos, complete = _walk_media(directory_path, should_stop)
        if scan_id is not None and complete:
            _shared_scans.clear()  # Solo se guarda la tanda más reciente
            _shared_scans[key] = (photos, videos)
        return photos, videos


def find_photos(directory_path: str, should_stop=None, scan_id=None) -> list[str]:
    """
    Busca archivos de imagen en un directorio dado (recursivamente).
    should_stop: función opcional; si devuelve True se interrumpe la búsqueda
    (el resultado queda incompleto y no debe usarse para borrar nada).
    """
    return scan_media(directory_path, should_stop, scan_id)[0]


def find_videos(directory_path: str, should_stop=None, scan_id=None) -> list[str]:
    """Busca archivos de vídeo en un directorio dado (recursivamente). Ver find_photos."""
    return scan_media(directory_path, should_stop, scan_id)[1]

if __name__ == "__main__":
    # ... (el main no necesita cambios) ...
    # Ejemplo de prueba rápida (si tienes una carpeta de imágenes)
    test_dir = Path.home() / "Imágenes"
    print(f"Buscando en: {test_dir}")
    if test_dir.is_dir():
        results = find_photos(str(test_dir))
        print(f"Encontradas {len(results)} fotos.")
    else:
        print("No se encontró el directorio de prueba.")
