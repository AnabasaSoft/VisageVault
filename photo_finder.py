# photo_finder.py
from pathlib import Path
import time

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

def find_photos(directory_path: str) -> list[str]:
    """
    Busca archivos de imagen en un directorio dado (recursivamente).
    Devuelve las rutas como una lista de strings.
    """
    target_dir = Path(directory_path)
    if not target_dir.is_dir():
        return []

    photo_files = []
    count = 0

    for file_path in target_dir.rglob('*'):
        if file_path.is_file() and file_path.suffix.lower() in IMAGE_EXTENSIONS:
            photo_files.append(str(file_path))

        count += 1
        if count % 100 == 0:
             time.sleep(0.001)

    return photo_files

def find_videos(directory_path: str) -> list[str]:
    """
    Busca archivos de vídeo en un directorio dado (recursivamente).
    Devuelve las rutas como una lista de strings.
    """
    target_dir = Path(directory_path)
    if not target_dir.is_dir():
        return []

    video_files = []
    count = 0

    for file_path in target_dir.rglob('*'):
        # Comprobar si es un archivo y si su extensión es de VÍDEO
        if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS:
            video_files.append(str(file_path))

        count += 1
        if count % 100 == 0:
             time.sleep(0.001)

    return video_files

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
