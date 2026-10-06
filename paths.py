# paths.py
"""
Rutas de datos, configuración y caché de VisageVault.

- Modo portable/desarrollo: ejecución desde el código fuente en una carpeta
  escribible -> todo se guarda junto al programa (comportamiento histórico).
- Modo instalado: ejecutable de PyInstaller o carpeta de solo lectura
  (/usr/share, AppImage...) -> directorios de usuario estándar del sistema.

Nunca se usa el directorio de trabajo actual ni la carpeta temporal de
PyInstaller (_MEIPASS), que en modo --onefile se borra al cerrar la app.
"""
import os
import sys
from functools import lru_cache

APP_NAME = "visagevault"


def _program_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _ensure(path):
    os.makedirs(path, exist_ok=True)
    return path


@lru_cache(maxsize=None)
def is_portable():
    """True si se ejecuta desde el código fuente en una carpeta escribible."""
    if getattr(sys, "frozen", False):
        return False
    return os.access(_program_dir(), os.W_OK)


def data_dir():
    """BD, MetaDB, token de Google y caja fuerte."""
    if is_portable():
        return _program_dir()
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        return _ensure(os.path.join(base, "VisageVault"))
    if sys.platform == "darwin":
        return _ensure(os.path.join(home, "Library", "Application Support", "VisageVault"))
    return _ensure(os.path.join(home, ".local", "share", APP_NAME))


def config_dir():
    """Fichero de configuración JSON."""
    if is_portable() or sys.platform in ("win32", "darwin"):
        return data_dir()
    return _ensure(os.path.join(os.path.expanduser("~"), ".config", APP_NAME))


def cache_dir():
    """Raíz de las cachés regenerables (miniaturas, caras, descargas de Drive)."""
    if is_portable():
        return _ensure(os.path.join(_program_dir(), "visagevault_cache"))
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return _ensure(os.path.join(base, "VisageVault", "Cache"))
    if sys.platform == "darwin":
        return _ensure(os.path.join(home, "Library", "Caches", "VisageVault"))
    return _ensure(os.path.join(home, ".cache", APP_NAME))


def cache_subdir(name):
    return _ensure(os.path.join(cache_dir(), name))


def db_path():
    return os.path.join(data_dir(), "visagevault.db")


def safe_dir():
    """Carpeta de los archivos cifrados de la caja fuerte."""
    return _ensure(os.path.join(data_dir(), "visagevault_safe"))
