# config_manager.py
import json
import os
import shutil
import hashlib
import hmac
import paths
import safe_crypto

# Nombre del archivo de configuración
CONFIG_FILENAME = "visagevault_config.json"

def get_config_path():
    """
    Calcula la ruta del archivo de configuración (ver paths.config_dir):
    junto al programa en modo portable/desarrollo, o en la carpeta de
    configuración del usuario si está instalado.
    """
    user_home = os.path.expanduser("~")
    try:
        target_config = os.path.join(paths.config_dir(), CONFIG_FILENAME)
    except OSError:
        # Fallback extremo: volver a home si no se puede crear la carpeta
        return os.path.join(user_home, CONFIG_FILENAME)

    if paths.is_portable():
        return target_config

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
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}

def save_config(config_data):
    config_path = get_config_path()
    # Escritura atómica: si la app se cierra a mitad, no queda un JSON a medias
    tmp_path = config_path + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, config_path)
    except OSError as e:
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

def set_drive_folder_id(folder_id, folder_name=None):
    config = load_config()
    config['drive_folder_id'] = folder_id
    config['drive_folder_name'] = folder_name
    save_config(config)

def get_drive_folder_name():
    """Nombre de la carpeta de Drive elegida (para la raíz del árbol)."""
    return load_config().get('drive_folder_name') or None

# --- ACTUALIZACIONES ---

def get_check_updates():
    """Buscar versiones nuevas al arrancar (activado por defecto)."""
    return bool(load_config().get('comprobar_actualizaciones', True))

def set_check_updates(enabled):
    config = load_config()
    config['comprobar_actualizaciones'] = bool(enabled)
    save_config(config)

def get_skipped_version():
    """Versión de la que el usuario pidió no volver a avisar."""
    return load_config().get('version_omitida', "")

def set_skipped_version(tag):
    config = load_config()
    config['version_omitida'] = tag
    save_config(config)

# --- SEGURIDAD CAJA FUERTE ---
# Se guardan los parámetros scrypt (con sal) y un verificador HMAC derivado de
# la clave; nunca la contraseña ni nada que permita descifrar directamente.
# 'safe_password_hash' (sha256 sin sal) es el formato antiguo y se migra al
# primer desbloqueo correcto.

def has_safe_password():
    config = load_config()
    return bool(config.get('safe_verifier') or config.get('safe_password_hash'))

def set_safe_password(password_plain):
    """Configura la contraseña de la caja fuerte y devuelve la clave derivada."""
    kdf = safe_crypto.new_kdf_params()
    key = safe_crypto.derive_key(password_plain, kdf)

    config = load_config()
    config['safe_kdf'] = kdf
    config['safe_verifier'] = safe_crypto.make_verifier(key)
    config.pop('safe_password_hash', None)
    save_config(config)
    return key

def unlock_safe(password_plain):
    """Devuelve la clave de la caja fuerte si la contraseña es correcta, o None."""
    config = load_config()

    kdf = config.get('safe_kdf')
    verifier = config.get('safe_verifier')
    if kdf and verifier:
        key = safe_crypto.derive_key(password_plain, kdf)
        return key if safe_crypto.check_verifier(key, verifier) else None

    # Formato antiguo: comprobar el hash sin sal y migrar la configuración
    legacy_hash = config.get('safe_password_hash')
    if legacy_hash:
        input_hash = hashlib.sha256(password_plain.encode()).hexdigest()
        if hmac.compare_digest(input_hash, legacy_hash):
            return set_safe_password(password_plain)
    return None
