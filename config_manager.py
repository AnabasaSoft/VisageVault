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
import json
import os
import shutil

# Nombre del archivo de configuración
CONFIG_FILENAME = "visagevault_config.json"

def get_config_path():
    """
    Calcula la ruta del archivo de configuración siguiendo estándares.
    Prioridad:
    1. Carpeta local (si es portable/desarrollo).
    2. ~/.config/visagevault/ (si está instalado en Linux).
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # 1. MODO PORTABLE / DESARROLLO (Windows o ejecución local)
    # Si tenemos permiso de escritura en la carpeta del script, usamos esa.
    if os.access(base_dir, os.W_OK):
        return os.path.join(base_dir, CONFIG_FILENAME)

    # 2. MODO INSTALADO (Linux / AUR / /usr/share)
    # Usamos el estándar XDG: ~/.config/visagevault/
    user_home = os.path.expanduser("~")
    config_dir = os.path.join(user_home, ".config", "visagevault")

    # Crear la carpeta si no existe
    if not os.path.exists(config_dir):
        try:
            os.makedirs(config_dir, exist_ok=True)
        except OSError:
            # Fallback extremo: volver a home si falla crear .config
            return os.path.join(user_home, CONFIG_FILENAME)

    target_config = os.path.join(config_dir, CONFIG_FILENAME)

    # --- MIGRACIÓN AUTOMÁTICA ---
    # Si existe el archivo viejo en la raíz (~/visagevault_config.json)
    # y no existe el nuevo, lo movemos para no perder datos.
    old_config_path = os.path.join(user_home, CONFIG_FILENAME)
    if os.path.exists(old_config_path) and not os.path.exists(target_config):
        try:
            shutil.move(old_config_path, target_config)
            print(f"Configuración migrada de {old_config_path} a {target_config}")
        except Exception as e:
            print(f"Error migrando configuración: {e}")

    return target_config

def load_config():
    config_path = get_config_path()
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def save_config(config_data):
    config_path = get_config_path()
    try:
        with open(config_path, 'w') as f:
            json.dump(config_data, f, indent=4)
    except IOError as e:
        print(f"Error guardando configuración en {config_path}: {e}")

# --- GETTERS Y SETTERS ESPECÍFICOS ---

def get_photo_directory():
    config = load_config()
    return config.get('photo_directory', "")

def set_photo_directory(path):
    config = load_config()
    config['photo_directory'] = path
    save_config(config)

def get_thumbnail_size():
    config = load_config()
    # Tamaño por defecto 128 si no existe
    return config.get('thumbnail_size', 128)

def set_thumbnail_size(size):
    config = load_config()
    config['thumbnail_size'] = size
    save_config(config)

def get_drive_folder_id():
    config = load_config()
    return config.get('drive_folder_id', None)

def set_drive_folder_id(folder_id):
    config = load_config()
    config['drive_folder_id'] = folder_id
    save_config(config)

# --- SEGURIDAD CAJA FUERTE ---

def get_safe_password_hash():
    config = load_config()
    return config.get('safe_password_hash', None)

def set_safe_password_hash(password_plain):
    import hashlib
    # Guardamos solo el hash SHA256, nunca la contraseña plana
    hash_object = hashlib.sha256(password_plain.encode())
    hex_dig = hash_object.hexdigest()

    config = load_config()
    config['safe_password_hash'] = hex_dig
    save_config(config)

def verify_safe_password(password_plain):
    import hashlib
    stored_hash = get_safe_password_hash()
    if not stored_hash: return False

    hash_object = hashlib.sha256(password_plain.encode())
    hex_dig = hash_object.hexdigest()

    return hex_dig == stored_hash
