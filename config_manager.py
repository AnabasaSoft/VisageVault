# config_manager.py
import json
from pathlib import Path

CONFIG_FILE = Path("visagevault_config.json")

def load_config():
    """Carga la configuración desde el archivo JSON."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("Error: El archivo de configuración está corrupto. Se usarán valores por defecto.")
            return {}
    return {}

def save_config(config_data):
    """Guarda la configuración en el archivo JSON."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config_data, f, indent=4)

def get_photo_directory():
    """Obtiene la ruta de la carpeta de fotos configurada."""
    config = load_config()
    return config.get('photo_directory')

def set_photo_directory(directory_path):
    """Establece y guarda la nueva ruta de la carpeta de fotos."""
    config = load_config()
    config['photo_directory'] = directory_path
    save_config(config)

def get_thumbnail_size():
    """Obtiene el tamaño de miniatura preferido por el usuario."""
    config = load_config()
    # Devuelve el tamaño guardado, o 128 como valor por defecto
    return config.get('thumbnail_size', 128)

def set_thumbnail_size(size):
    """Guarda el tamaño de miniatura preferido por el usuario."""
    config = load_config()
    config['thumbnail_size'] = size
    save_config(config)
