# config_manager.py
import json
import hashlib
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

def get_drive_folder_id():
    """Obtiene el ID de la carpeta de Drive configurada."""
    config = load_config()
    return config.get('drive_folder_id')

def set_drive_folder_id(folder_id):
    """Guarda el ID de la carpeta de Drive."""
    config = load_config()
    config['drive_folder_id'] = folder_id
    save_config(config)

def get_safe_password_hash():
    """Obtiene el hash SHA-256 de la contraseña de la caja fuerte."""
    config = load_config()
    return config.get('safe_password_hash')

def set_safe_password_hash(password):
    """Guarda el hash de la contraseña (NO la contraseña en texto plano)."""
    config = load_config()
    hash_obj = hashlib.sha256(password.encode('utf-8'))
    config['safe_password_hash'] = hash_obj.hexdigest()
    save_config(config)

def verify_safe_password(password):
    """Verifica si la contraseña introducida coincide con la guardada."""
    stored_hash = get_safe_password_hash()
    if not stored_hash: return False

    input_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()
    return input_hash == stored_hash
