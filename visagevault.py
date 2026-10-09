# ==============================================================================
# PROYECTO: VisageVault - Gestor de Fotografías Inteligente
# DERECHOS DE AUTOR: © 2025 Daniel Serrano Armenta
# ==============================================================================
#
# Autor: Daniel Serrano Armenta
# Contacto: anabasasoft@gmail.com
# GitHub: github.com/anabasasoft
# Portafolio: https://danitxu79.github.io/
#
# ## 📜 Licencia
#
# Este proyecto se ofrece bajo un modelo de **Doble Licencia (Dual License)**:
#
# 1.  **LGPLv3:** Ideal para proyectos de código abierto. Si usas esta biblioteca (especialmente
#  si la modificas), debes cumplir con las obligaciones de la LGPLv3.
# 2.  **Comercial (Privativa):** Si los términos de la LGPLv3 no se ajustan a tus necesidades
#  (por ejemplo, para software propietario de código cerrado), por favor contacta al autor para
#  adquirir una licencia comercial.
#
# Para más detalles, consulta el archivo `LICENSE` o la cabecera de `visagevault.py`.
#
#
# ==============================================================================

import sys
import os
import time

# --- PROGRAMAS EXTERNOS CON EL ENTORNO DEL SISTEMA ---
# El ejecutable de PyInstaller arranca con LD_LIBRARY_PATH apuntando a sus
# bibliotecas. Sin esto, xdg-open (navegador del login de Google, reproductor
# de vídeo, enlaces) las heredaría y fallaría:
# "/bin/sh: symbol lookup error: ... rl_full_quoting_desired".
import updater
updater.restore_system_library_path()

# --- SPLASH TEMPRANO ---
# Las importaciones de abajo (sklearn, face_recognition, cv2...) tardan varios
# segundos. Al ejecutar la app, el splash se muestra ANTES de importarlas, con
# solo PySide6 cargado; run_visagevault() reutiliza esta QApplication y este
# splash. Importado como módulo (pruebas, otros scripts) no se hace nada.
_early_app = None
_early_splash = None
_early_splash_shown_at = None
if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication as _QApplication, QSplashScreen as _QSplashScreen
    from PySide6.QtGui import QPixmap as _QPixmap
    from PySide6.QtCore import Qt as _Qt

    _base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    _early_app = _QApplication(sys.argv)
    _splash_pixmap = _QPixmap(os.path.join(_base_dir, "AnabasaSoft.png"))
    if _splash_pixmap.isNull():
        _splash_pixmap = _QPixmap(os.path.join(_base_dir, "visagevault.png")).scaled(
            600, 400, _Qt.KeepAspectRatio, _Qt.SmoothTransformation
        )
    _early_splash = _QSplashScreen(_splash_pixmap)
    _early_splash.show()
    _early_app.processEvents()  # Pintarlo ya, antes de las importaciones lentas
    _early_splash_shown_at = time.monotonic()

def _keep_splash_alive():
    """Atiende los eventos entre importaciones lentas: si no, el sistema puede
    marcar el splash como "No responde" (Windows, a los 5 s)."""
    if _early_app is not None:
        _early_app.processEvents()

from pathlib import Path
import datetime
import locale
import warnings
import sqlite3

import threading # Necesario para evitar que la UI se congele
from drive_auth import DriveAuthenticator, DriveAuthError
import requests # Para bajar thumbnails
from drive_manager import DriveManager, thread_manager
import config_manager # Para guardar la carpeta elegida

# La versión la genera el workflow de release a partir del tag
# (visagevault_version.py, que no está en git). Ejecutando desde el código
# fuente vale "dev" y no se buscan actualizaciones.
# Nombre propio y no "_version": en openSUSE, el paquete de Pillow añade la
# carpeta PIL al sys.path y su _version.py se importaría en su lugar.
try:
    from visagevault_version import __version__ as APP_VERSION
except ImportError:
    APP_VERSION = "dev"
APP_NAME = "VisageVault (dev)" if APP_VERSION == "dev" else f"VisageVault v{APP_VERSION}"
import safe_crypto
import redeye  # Carga face_recognition (lento)
_keep_splash_alive()
from safe_crypto import CryptoManager

# --- Silenciar solo el aviso de pkg_resources ---
warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API",
    category=UserWarning,
)

import numpy as np
from sklearn.cluster import DBSCAN
_keep_splash_alive()
import rawpy # Importar rawpy para soporte RAW

from PySide6.QtWidgets import (
    QDialog, 
    QAbstractItemView, QDialogButtonBox, QTreeWidget, QTreeWidgetItem,
    QComboBox, QMenu, QListWidget, QListWidgetItem, QFrame, QMessageBox, QCheckBox
)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QStyle, QFileDialog,
    QScrollArea, QGridLayout, QLabel, QGroupBox, QSpacerItem, QSizePolicy,
    QSplitter, QTabWidget, QStackedWidget, QSplashScreen
)
from PySide6.QtCore import (
    Qt, QSize, QObject, Signal, QThread, Slot, QTimer,
    QRunnable, QThreadPool, QPropertyAnimation, QEasingCurve, QRect, QPoint, QRectF,
    QPointF, QBuffer, QIODevice, QUrl, QEvent
)
from PySide6.QtGui import (
    QPixmap, QIcon, QCursor, QPainter, QPaintEvent,
    QPainterPath, QKeyEvent, QDesktopServices, QImage, QImageReader, QColor, QPen, QBrush
)

from photo_finder import find_photos, find_videos, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, RAW_EXTENSIONS
from metadata_reader import get_photo_date, get_video_date  # Fecha por nombre o, si no, por fecha de modificación
from thumbnail_generator import (
    generate_image_thumbnail, generate_video_thumbnail, get_thumbnail_path, THUMBNAIL_SIZE
)
import paths

import piexif.helper
import re
import db_manager
from db_manager import VisageVaultDB
import fr_compat  # noqa: F401  Antes de face_recognition (ver fr_compat.py)
import face_recognition
_keep_splash_alive()
from PIL import Image, ImageOps
from send2trash import send2trash
import ast
import traceback
import types
from concurrent.futures import ThreadPoolExecutor, as_completed
import pickle
import shutil
import hashlib
from collections import OrderedDict

# =================================================================
# AGRUPACIÓN POR FECHA: VALORES DESCONOCIDOS
# =================================================================
NO_DATE_YEAR = "Sin Fecha"
NO_DATE_MONTH = "00"

def _is_known_year(year):
    return isinstance(year, str) and len(year) == 4 and year.isdigit() and year != "0000"

def _is_known_month(month):
    return isinstance(month, str) and month.isdigit() and 1 <= int(month) <= 12

def sort_years(years, reverse=True):
    """Años conocidos ordenados; 'Sin Fecha' y valores raros siempre al final."""
    years = list(years)
    known = sorted((y for y in years if _is_known_year(y)), reverse=reverse)
    unknown = sorted((y for y in years if not _is_known_year(y)), key=str)
    return known + unknown

def sort_months(months, reverse=False):
    """Meses conocidos ordenados; 'Mes desconocido' (00) siempre al final."""
    months = list(months)
    known = sorted((m for m in months if _is_known_month(m)), reverse=reverse)
    unknown = sorted((m for m in months if not _is_known_month(m)), key=str)
    return known + unknown

def year_title(year):
    return f"Año {year}" if _is_known_year(year) else "Sin fecha"

# =================================================================
# PROTECCIÓN CONTRA BORRADOS MASIVOS DE LA BIBLIOTECA
# =================================================================
def find_missing_paths(db_paths, disk_paths_set, directory):
    """
    Rutas de la BD que pertenecen a `directory` y ya no están en el disco.
    Las de otras carpetas (p. ej. una biblioteca anterior) no se tocan.
    Devuelve (conocidas_en_la_carpeta, desaparecidas).
    """
    prefix = os.path.join(os.path.normpath(directory), "")
    known = [p for p in db_paths if p.startswith(prefix)]
    missing = [p for p in known if p not in disk_paths_set]
    return known, missing

def needs_removal_confirmation(n_missing, n_known):
    """True si faltan tantos archivos que puede ser un disco desmontado."""
    if n_missing == 0:
        return False
    if n_missing == n_known:
        return True  # Ha desaparecido todo
    return n_missing >= 50 or n_missing > n_known * 0.25

# --- CACHÉ GLOBAL DE MINIATURAS EN RAM ---
# Las miniaturas se cargan en hilos secundarios (QRunnable). QPixmap solo puede
# usarse en el hilo de la interfaz, así que los workers trabajan con QImage
# (seguro entre hilos) y la conversión a QPixmap se hace al recibir la señal.
_IMAGE_CACHE_MAX_BYTES = 96 * 1024 * 1024  # ~500 miniaturas de 256 px
_image_cache = OrderedDict()
_image_cache_bytes = 0
_image_cache_lock = threading.Lock()

def get_cached_image(filepath: str) -> QImage:
    """Carga una miniatura de disco con caché LRU en RAM. No cachea fallos."""
    with _image_cache_lock:
        image = _image_cache.get(filepath)
        if image is not None:
            _image_cache.move_to_end(filepath)
            return image

    image = QImage()
    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        image.load(filepath)
    if image.isNull():
        return image

    global _image_cache_bytes
    with _image_cache_lock:
        previous = _image_cache.pop(filepath, None)
        if previous is not None:
            _image_cache_bytes -= previous.sizeInBytes()
        _image_cache[filepath] = image
        _image_cache_bytes += image.sizeInBytes()
        while _image_cache_bytes > _IMAGE_CACHE_MAX_BYTES and len(_image_cache) > 1:
            _, evicted = _image_cache.popitem(last=False)
            _image_cache_bytes -= evicted.sizeInBytes()
    return image

def resource_path(relative_path):
    """Obtiene la ruta absoluta al recurso tanto en PyInstaller como en desarrollo."""
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# --- Configuración regional para nombres de meses ---
try:
    locale.setlocale(locale.LC_TIME, '')
except locale.Error:
    print("Warning: Could not set system locale, month names may be in English.")


# Constante para el margen de precarga (en píxeles)
PRELOAD_MARGIN_PX = 500

# =================================================================
# DEFINICIÓN ÚNICA DE SEÑALES PARA EL THUMBNAILLOADER
# =================================================================
class ThumbnailLoaderSignals(QObject):
    """Contenedor de señales para la clase QRunnable."""
    thumbnail_loaded = Signal(str, QImage) # original_path, imagen (se convierte a QPixmap en la UI)
    load_failed = Signal(str)
    drive_link_refreshed = Signal(str, str)  # file_id, enlace de miniatura nuevo

# =================================================================
# CLASE PARA CARGAR MINIATURAS DE IMAGEN (QRunnable)
# =================================================================
class ThumbnailLoader(QRunnable):
    def __init__(self, original_filepath: str, signals: ThumbnailLoaderSignals):
        super().__init__()
        self.original_filepath = original_filepath
        self.signals = signals

    @Slot()
    def run(self):
        # 1. Generar si no existe (esto escribe en disco)
        thumbnail_path = generate_image_thumbnail(self.original_filepath)

        if thumbnail_path:
            try:
                # 2. Cargar usando CACHÉ DE RAM (¡Mucho más rápido!)
                image = get_cached_image(thumbnail_path)
                if not image.isNull():
                    self.signals.thumbnail_loaded.emit(self.original_filepath, image)
                else:
                    self.signals.load_failed.emit(self.original_filepath)
            except Exception:
                self.signals.load_failed.emit(self.original_filepath)
        else:
            self.signals.load_failed.emit(self.original_filepath)

# =================================================================
# CLASE PARA CARGAR MINIATURAS DE VÍDEO (QRunnable) - ¡NUEVA!
# =================================================================
class VideoThumbnailLoader(QRunnable):
    def __init__(self, original_filepath: str, signals: ThumbnailLoaderSignals):
        super().__init__()
        self.original_filepath = original_filepath
        self.signals = signals

    @Slot()
    def run(self):
        thumbnail_path = generate_video_thumbnail(self.original_filepath)
        if thumbnail_path:
            try:
                # Usar Caché RAM
                image = get_cached_image(thumbnail_path)
                if not image.isNull():
                    self.signals.thumbnail_loaded.emit(self.original_filepath, image)
                else:
                    self.signals.load_failed.emit(self.original_filepath)
            except Exception:
                self.signals.load_failed.emit(self.original_filepath)
        else:
            self.signals.load_failed.emit(self.original_filepath)

# =================================================================
# CLASE: NetworkThumbnailLoader (CON CACHÉ EN DISCO)
# =================================================================
_http_local = threading.local()

def _http_session():
    """Sesión HTTP del hilo actual: reutiliza la conexión TLS entre miniaturas."""
    session = getattr(_http_local, "session", None)
    if session is None:
        session = _http_local.session = requests.Session()
    return session


class NetworkThumbnailLoader(QRunnable):
    def __init__(self, url, file_id, signals):
        super().__init__()
        self.url = url
        self.file_id = file_id
        self.signals = signals

        self.cache_dir = paths.cache_subdir("drive_snapshot_cache")

    @Slot()
    def run(self):
        cache_path = os.path.join(self.cache_dir, f"{self.file_id}.jpg")

        # 1. INTENTO CACHÉ DISCO + RAM
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
            image = get_cached_image(cache_path)
            if not image.isNull():
                touch_cache_file(cache_path)
                self.signals.thumbnail_loaded.emit(self.file_id, image)
                return

        # 2. DESCARGA
        try:
            content = self._download(self.url) if self.url else None
            if content is None:
                # Los enlaces de miniatura guardados caducan a las pocas horas:
                # se pide uno nuevo a Drive y se reintenta una vez
                new_url = thread_manager().get_thumbnail_link(self.file_id)
                if new_url and new_url != self.url:
                    self.signals.drive_link_refreshed.emit(self.file_id, new_url)
                    content = self._download(new_url)
            if content:
                # A un temporal: una escritura a medias no debe quedar como caché
                part_path = cache_path + ".part"
                with open(part_path, 'wb') as f:
                    f.write(content)
                os.replace(part_path, cache_path)

                # Cargar en memoria y cachear
                image = get_cached_image(cache_path)
                if not image.isNull():
                    self.signals.thumbnail_loaded.emit(self.file_id, image)
                    return
        except Exception as e:
            print(f"Error descargando miniatura de Drive {self.file_id}: {e}")
        self.signals.load_failed.emit(self.file_id)

    @staticmethod
    def _download(url):
        """Contenido de la miniatura, o None si el enlace ya no vale."""
        response = _http_session().get(url, timeout=10)
        if response.status_code == 200 and response.content:
            return response.content
        return None

# =================================================================
# ACTUALIZACIONES
# =================================================================
class DriveDownloadSignals(QObject):
    """
    La vista previa de Drive se descarga en un hilo de Python. QTimer.singleShot
    desde ese hilo nunca se ejecuta (no tiene bucle de eventos de Qt); una señal
    sí llega al hilo de la interfaz.
    """
    finished = Signal(str)  # ruta local descargada
    failed = Signal(str)    # mensaje para la barra de estado


class UpdateCheckSignals(QObject):
    """La consulta a GitHub se hace en un hilo; el resultado vuelve por señal."""
    # (release {"tag", "url"} o None, error o None, automática, botón, ventana padre)
    finished = Signal(object, object, bool, object, object)


class UpdateDialog(QDialog):
    """Avisa de una versión nueva con el enlace a su release.
    Con allow_skip se ofrece no volver a avisar de esa versión."""
    def __init__(self, rel, allow_skip, parent=None):
        super().__init__(parent)
        self.rel = rel
        self.setWindowTitle("Nueva versión disponible")
        layout = QVBoxLayout(self)

        text = QLabel(f"Hay una versión nueva de VisageVault: {rel['tag']}\n(tienes la {APP_VERSION}).")
        text.setAlignment(Qt.AlignCenter)
        text.setWordWrap(True)
        text.setStyleSheet("font-size: 11pt;")
        layout.addWidget(text)

        link = QLabel("<a href='#'>Ver la versión en GitHub</a>")
        link.setAlignment(Qt.AlignCenter)
        link.linkActivated.connect(lambda _: updater.open_url(rel["url"]))
        layout.addWidget(link)

        self.skip_check = None
        if allow_skip:
            self.skip_check = QCheckBox("No volver a avisar de esta versión")
            layout.addWidget(self.skip_check, 0, Qt.AlignCenter)

        buttons = QHBoxLayout()
        btn_download = QPushButton("Descargar")
        btn_download.setDefault(True)
        btn_download.clicked.connect(lambda: self._close(True))
        btn_later = QPushButton("Más tarde")
        btn_later.clicked.connect(lambda: self._close(False))
        buttons.addWidget(btn_download)
        buttons.addWidget(btn_later)
        layout.addLayout(buttons)

    def _close(self, download):
        if self.skip_check is not None and self.skip_check.isChecked():
            config_manager.set_skipped_version(self.rel["tag"])
        if download:
            updater.open_url(self.rel["url"])
        self.accept()

    def reject(self):
        # Cerrar con Esc o la X equivale a "Más tarde" (respetando la casilla)
        self._close(False)


# =================================================================
# MINIATURAS DE LA CAJA FUERTE (descifrado en segundo plano)
# =================================================================
class SafeThumbnailSignals(QObject):
    loaded = Signal(int, str, QImage)  # generación, ruta cifrada, miniatura
    failed = Signal(int, str)


class SafeThumbnailLoader(QRunnable):
    """
    Descifra un archivo de la caja fuerte (o la miniatura .thumb de un vídeo)
    y devuelve solo una miniatura. La imagen se decodifica ya reducida, así
    que nunca se tiene la foto completa decodificada en memoria.
    """
    def __init__(self, signals, generation, encrypted_path, media_type, key, legacy_key, size):
        super().__init__()
        self.signals = signals
        self.generation = generation
        self.encrypted_path = encrypted_path
        self.media_type = media_type
        self.key = key
        self.legacy_key = legacy_key
        self.size = size

    @Slot()
    def run(self):
        image = QImage()
        try:
            source = self.encrypted_path if self.media_type == 'photo' else self.encrypted_path + ".thumb"
            data = CryptoManager.decrypt_to_bytes(source, self.key, self.legacy_key) if os.path.exists(source) else None
            if data:
                buffer = QBuffer()
                buffer.setData(data)
                buffer.open(QIODevice.OpenModeFlag.ReadOnly)
                reader = QImageReader(buffer)
                reader.setAutoTransform(True)  # Respeta la orientación EXIF
                original_size = reader.size()
                if original_size.isValid():
                    reader.setScaledSize(original_size.scaled(self.size, self.size, Qt.KeepAspectRatio))
                image = reader.read()
                buffer.close()
        except Exception as e:
            print(f"Error cargando miniatura de la caja fuerte: {e}")

        try:
            if image.isNull():
                self.signals.failed.emit(self.generation, self.encrypted_path)
            else:
                self.signals.loaded.emit(self.generation, self.encrypted_path, image)
        except RuntimeError:
            pass  # App cerrada


class DriveFolderDialog(QDialog):
    def __init__(self, drive_manager, parent=None, db=None):
        super().__init__(parent)
        self.setWindowTitle("Navegador de Google Drive")
        self.resize(600, 450)
        self.drive = drive_manager
        self.db = db  # Caché de carpetas (opcional)

        # Estado de navegación
        self.current_folder_id = None
        self.current_folder_name = None
        self.folder_history = []

        self.selected_folder_id = None
        self.selected_folder_name = None

        layout = QVBoxLayout(self)

        # 1. Cabecera con Ruta
        self.path_label = QLabel("Inicio")
        self.path_label.setStyleSheet("font-weight: bold; color: #3daee9; font-size: 14px; padding: 5px;")
        layout.addWidget(self.path_label)

        # --- AVISO INFORMATIVO ---
        info_layout = QHBoxLayout()
        info_icon = QLabel("ℹ️")
        info_text = QLabel("Esta lista <b>SOLO muestra carpetas</b>. Tus fotos no aparecerán aquí, pero se escanearán al pulsar 'Seleccionar'.")
        info_text.setWordWrap(True)
        info_text.setStyleSheet("color: gray; font-size: 11px;")
        info_layout.addWidget(info_icon)
        info_layout.addWidget(info_text, 1)
        layout.addLayout(info_layout)
        # --------------------------------

        # 2. Lista
        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(32, 32))
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget)

        # 3. Botones
        btn_layout = QHBoxLayout()
        self.btn_select = QPushButton("Seleccionar esta carpeta")
        self.btn_select.setEnabled(False)
        self.btn_select.setStyleSheet("""
            QPushButton { background-color: #3daee9; color: white; font-weight: bold; padding: 10px; border-radius: 4px;}
            QPushButton:hover { background-color: #4dbef9; }
            QPushButton:disabled { background-color: #cccccc; }
        """)
        self.btn_select.clicked.connect(self._select_current)

        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_select)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        # CARGAR MENÚ INICIAL
        self._load_home_menu()

    def _load_home_menu(self):
        self.list_widget.clear()
        self.current_folder_id = "HOME"
        self.current_folder_name = "Inicio"
        self.path_label.setText("🏠 Inicio")
        self.btn_select.setText("Selecciona una opción...")
        self.btn_select.setEnabled(False)
        self.folder_history = []

        item_drive = QListWidgetItem("Mi Unidad")
        item_drive.setData(Qt.UserRole, "root")
        item_drive.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon))
        self.list_widget.addItem(item_drive)

        item_pc = QListWidgetItem("Ordenadores")
        item_pc.setData(Qt.UserRole, "computers")
        item_pc.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.list_widget.addItem(item_pc)

    def _load_folder(self, folder_id, folder_name):
        self.list_widget.clear()
        self.current_folder_id = folder_id
        self.current_folder_name = folder_name

        path_str = " > ".join([name for _, name in self.folder_history] + [folder_name])
        self.path_label.setText(path_str)

        self.btn_select.setEnabled(True)
        self.btn_select.setText(f"Seleccionar: '{folder_name}'")

        back_item = QListWidgetItem(".. (Volver)")
        back_item.setData(Qt.UserRole, "BACK")
        back_item.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        back_item.setForeground(Qt.gray)
        self.list_widget.addItem(back_item)

        try:
            folders = None
            if self.db is not None:
                cached, fetched_at = self.db.get_drive_subfolders(folder_id)
                if cached is not None and time.time() - fetched_at < VisageVaultApp.DRIVE_FOLDER_TTL_S:
                    folders = cached
            if folders is None:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                folders = self.drive.list_folders(folder_id)
                QApplication.restoreOverrideCursor()
                if self.db is not None:
                    self.db.save_drive_subfolders({folder_id: folders}, time.time())

            # Si no hay carpetas, avisamos pero permitimos seleccionar
            if not folders:
                info_item = QListWidgetItem("(No hay subcarpetas)")
                info_item.setFlags(Qt.NoItemFlags) # No seleccionable
                self.list_widget.addItem(info_item)

            for f in folders:
                item = QListWidgetItem(f['name'])
                item.setData(Qt.UserRole, f['id'])
                item.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                self.list_widget.addItem(item)

        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Error", f"No se pudo listar: {e}")

    def _on_item_double_clicked(self, item):
        data = item.data(Qt.UserRole)
        if not data: return

        if data == "BACK":
            if self.folder_history:
                prev_id, prev_name = self.folder_history.pop()
                if prev_id == "HOME":
                    self._load_home_menu()
                else:
                    self._load_folder(prev_id, prev_name)
            else:
                self._load_home_menu()

        elif data == "root" or data == "computers":
            self.folder_history.append(("HOME", "Inicio"))
            self._load_folder(data, item.text())

        else:
            self.folder_history.append((self.current_folder_id, self.current_folder_name))
            self._load_folder(data, item.text())

    def _select_current(self):
        if self.current_folder_id == "HOME" or self.current_folder_id == "computers":
            QMessageBox.information(self, "Aviso", "Por favor, entra en una carpeta específica para seleccionarla.")
            return

        self.selected_folder_id = self.current_folder_id
        self.selected_folder_name = self.current_folder_name
        self.accept()

# =================================================================
# SEÑALES Y WORKER PARA CARGAR Y RECORTAR CARAS
# =================================================================
class FaceLoaderSignals(QObject):
    face_loaded = Signal(int, QImage, str)
    face_load_failed = Signal(int)

# =================================================================
# WORKER PARA LOGIN DE GOOGLE DRIVE
# =================================================================
class DriveLoginWorker(QObject):
    """
    Autenticación de Google Drive en segundo plano.
    silent=True (inicio de sesión automático al arrancar): solo usa la sesión
    guardada, renovándola por red si ha caducado; nunca abre el navegador.
    """
    login_success = Signal(object)  # Emite el servicio de Drive
    login_failed = Signal(str)      # Emite mensaje de error
    finished = Signal()

    def __init__(self, silent=False):
        super().__init__()
        self.silent = silent

    @Slot()
    def run(self):
        try:
            auth = DriveAuthenticator()
            service = auth.get_service(silent=self.silent)
            if service is None:
                self.login_failed.emit("La sesión de Google caducó. Por favor, conecta de nuevo.")
                return
            self.login_success.emit(service)
        except FileNotFoundError as e:
            self.login_failed.emit(str(e))
        except Exception as e:
            print(f"Error de Login con Google: {e}")
            self.login_failed.emit(str(e))
        finally:
            self.finished.emit()

class DriveFolderSignals(QObject):
    """Resultado de DriveFolderLoader: (generación del árbol, ids pedidos,
    {parent_id: [carpetas]} o None si falló)."""
    loaded = Signal(int, list, object)


class DriveFolderLoader(QRunnable):
    """
    Lista en segundo plano las subcarpetas de una o varias carpetas de Drive
    con una sola consulta. No toca la interfaz: el resultado vuelve por señal
    y el hilo de la interfaz busca los elementos del árbol por su id (pueden
    haberse borrado mientras tanto).
    """
    def __init__(self, generation, folder_ids, signals):
        super().__init__()
        self.generation = generation
        self.folder_ids = list(folder_ids)
        self.signals = signals

    @Slot()
    def run(self):
        try:
            listings = thread_manager().list_subfolders_of_many(self.folder_ids)
        except Exception as e:
            print(f"Error cargando carpetas de Drive: {e}")
            listings = None
        try:
            self.signals.loaded.emit(self.generation, self.folder_ids, listings)
        except RuntimeError:
            pass  # App cerrada

class DriveScanWorker(QObject):
    """
    Worker con capacidad de 'Modo Lento' para ceder prioridad a otras tareas.
    """
    progress = Signal(str)
    finished = Signal(int)

    def __init__(self, folder_id, db_path):
        super().__init__()
        self.folder_id = folder_id
        self.db_path = db_path
        self.is_running = True
        self.slow_mode = False

    @Slot(bool)
    def set_slow_mode(self, active):
        """Slot para activar/desactivar el modo de baja prioridad."""
        self.slow_mode = active
        if active:
            print("🐢 Worker Drive: Entrando en modo lento (Prioridad a carpetas)")
        else:
            print("🐇 Worker Drive: Volviendo a velocidad normal")

    @Slot()
    def run(self):
        local_db = VisageVaultDB.for_worker(self.db_path)

        try:
            local_manager = DriveManager()

            count = 0
            buffer = []
            BATCH_SIZE = 100
            last_update_time = time.time()

            def save_folders(folder_id, subfolders):
                try:
                    local_db.save_drive_subfolders({folder_id: subfolders}, time.time())
                except Exception as e:
                    print(f"Error guardando carpetas de Drive: {e}")

            for batch_of_images in local_manager.list_images_recursively(self.folder_id, save_folders):
                if not self.is_running: break

                buffer.extend(batch_of_images)

                # --- AQUÍ ESTÁ LA MAGIA DE LA PRIORIDAD ---
                if self.slow_mode:
                    # Si estamos en modo lento, dormimos 1.5 segundos.
                    # Esto deja la red y la CPU libres para que el Árbol de Carpetas cargue rápido.
                    time.sleep(1.5)
                # ------------------------------------------

                if len(buffer) >= BATCH_SIZE:
                    self._save_to_db(local_db, buffer)
                    count += len(buffer)
                    buffer = []

                    if time.time() - last_update_time > 1.0:
                        self.progress.emit(f"Indexando nube... {count} fotos guardadas.")
                        last_update_time = time.time()

                    time.sleep(0.05) # Pausa normal

            if buffer:
                self._save_to_db(local_db, buffer)
                count += len(buffer)

            self.progress.emit(f"Finalizado. Total: {count} fotos.")
            self.finished.emit(count)

        except DriveAuthError as e:
            self.progress.emit(str(e))
            self.finished.emit(-1)
        except Exception as e:
            print(f"❌ ERROR FATAL EN WORKER DRIVE: {e}")
            traceback.print_exc()
            self.finished.emit(0)
        finally:
            try: local_db.conn.close()
            except: pass

    def _save_to_db(self, db_instance, items):
        try:
            db_instance.bulk_upsert_drive_photos(items, root_folder_id=self.folder_id)
        except Exception as e:
            print(f"Error guardando en DB Drive: {e}")

# =================================================================
# CLASE: FaceLoader (CORREGIDA PARA RUTAS LINUX)
# =================================================================
_SAFE_DRIVE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_SAFE_EXTENSION = re.compile(r"^\.[A-Za-z0-9]{1,10}$")

def drive_cache_path(file_id, name):
    """
    Ruta local de una descarga de Drive. Se nombra por el ID (único) y no por
    el nombre: en Drive puede haber nombres repetidos o con '/' y '..'.
    Se conserva la extensión porque el visor la usa para detectar los RAW.
    """
    if not file_id or not _SAFE_DRIVE_ID.match(str(file_id)):
        raise ValueError(f"ID de Drive no válido: {file_id!r}")
    base_name = os.path.basename(str(name or "").replace("\\", "/"))
    extension = os.path.splitext(base_name)[1].lower()
    if not _SAFE_EXTENSION.match(extension):
        extension = ""
    return os.path.join(paths.cache_subdir("drive_cache"), f"{file_id}{extension}")

def send_files_to_trash(parent, file_paths):
    """
    Mueve los archivos a la papelera del sistema. Si alguno no se puede
    (p. ej. en una unidad de red o un disco sin papelera), pregunta antes de
    borrarlo definitivamente. Devuelve las rutas que ya no están en su sitio.
    """
    removed, failed = [], []
    for path in file_paths:
        if not os.path.exists(path):
            removed.append(path)
            continue
        try:
            send2trash(path)
            removed.append(path)
        except Exception as e:
            print(f"No se pudo mover a la papelera {path}: {e}")
            failed.append(path)

    if failed:
        names = "\n".join(Path(p).name for p in failed[:10]) + ("\n..." if len(failed) > 10 else "")
        answer = QMessageBox.question(
            parent,
            "Papelera no disponible",
            f"No se pudieron mover a la papelera {len(failed)} archivo(s) "
            f"(p. ej. en una unidad de red o un disco sin papelera):\n\n{names}\n\n"
            "¿Eliminarlos DEFINITIVAMENTE? Esta acción no se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if answer == QMessageBox.StandardButton.Yes:
            for path in failed:
                try:
                    os.remove(path)
                    removed.append(path)
                except OSError as e:
                    print(f"Error eliminando {path}: {e}")
    return removed

def load_full_pixmap(path) -> QPixmap:
    """Foto completa como QPixmap (también RAW, con rawpy). Solo en el hilo de la interfaz."""
    if Path(path).suffix.lower() in RAW_EXTENSIONS:
        with rawpy.imread(path) as raw:
            rgb_array = raw.postprocess()
        height, width, _ = rgb_array.shape
        image = QImage(rgb_array.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()
        return QPixmap.fromImage(image)
    return QPixmap(path)

def get_face_cache_path(face_id) -> str:
    """Ruta del recorte de una cara en la caché de disco."""
    return os.path.join(paths.cache_subdir("face_cache"), f"face_{face_id}.jpg")

def evict_cached_image(filepath: str):
    """Quita una miniatura de la caché en RAM."""
    global _image_cache_bytes
    with _image_cache_lock:
        evicted = _image_cache.pop(str(filepath), None)
        if evicted is not None:
            _image_cache_bytes -= evicted.sizeInBytes()

def purge_media_caches(conn, media_path):
    """
    Borra la miniatura (disco y RAM) y los recortes de caras de una foto o vídeo.
    Hay que llamarla ANTES de quitarlo de la BD: los recortes se localizan por sus caras.
    """
    thumb_file = get_thumbnail_path(str(media_path))
    evict_cached_image(thumb_file)
    leftovers = [str(thumb_file)]
    row = conn.execute("SELECT id FROM photos WHERE filepath = ?", (media_path,)).fetchone()
    if row:
        face_rows = conn.execute("SELECT id FROM faces WHERE photo_id = ?", (row[0],))
        leftovers += [get_face_cache_path(face_row[0]) for face_row in face_rows]
    for path in leftovers:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            print(f"No se pudo borrar {path}: {e}")


# Tamaño máximo de lo descargado de Drive: es una caché, no una copia de la nube.
# Al pasarse se borra lo usado hace más tiempo hasta quedar en el 90 %.
DRIVE_CACHE_LIMITS = {
    "drive_cache": 1024 * 1024 * 1024,           # Fotos completas (vista previa)
    "drive_snapshot_cache": 300 * 1024 * 1024,   # Miniaturas
}

def touch_cache_file(path):
    """Marca un archivo de caché como usado ahora (para trim_drive_caches)."""
    try:
        os.utime(path)
    except OSError:
        pass

def trim_drive_caches():
    """Recorta las cachés de Drive a DRIVE_CACHE_LIMITS, empezando por lo más antiguo."""
    for subdir, limit in DRIVE_CACHE_LIMITS.items():
        try:
            entries, total = [], 0
            now = time.time()
            with os.scandir(paths.cache_subdir(subdir)) as it:
                for entry in it:
                    if not entry.is_file():
                        continue
                    st = entry.stat()
                    if entry.name.endswith(".part"):
                        if now - st.st_mtime > 3600:  # Descarga interrumpida
                            os.remove(entry.path)
                        continue
                    entries.append((st.st_mtime, st.st_size, entry.path))
                    total += st.st_size
            if total <= limit:
                continue
            entries.sort()
            for _, size, path in entries:
                if total <= limit * 0.9:
                    break
                evict_cached_image(path)
                os.remove(path)
                total -= size
        except OSError as e:
            print(f"Error recortando la caché {subdir}: {e}")

def cleanup_orphan_caches(db_path):
    """
    Borra lo que ya no corresponde a nada de la BD: caras de fotos eliminadas,
    sus recortes y las miniaturas de archivos que ya no están (p. ej. borrados
    fuera de la app). Se ejecuta en segundo plano al arrancar.
    """
    try:
        # Primero se listan los ficheros y luego se consulta la BD: lo que se cree
        # entre medias ya estará en la BD y no se borra
        face_dir = paths.cache_subdir("face_cache")
        face_files = os.listdir(face_dir)
        thumb_dir = get_thumbnail_path("").parent
        thumb_files = os.listdir(thumb_dir)

        local_db = VisageVaultDB.for_worker(db_path)
        try:
            orphan_faces = local_db.delete_orphan_faces()
            face_ids = local_db.get_all_face_ids()
            valid_thumbs = {get_thumbnail_path(p).name for p in local_db.get_all_media_paths()}
        finally:
            local_db.conn.close()

        removed = 0
        for name in face_files:
            stem = name[len("face_"):-len(".jpg")] if name.startswith("face_") and name.endswith(".jpg") else None
            if stem is not None and stem.isdigit() and int(stem) not in face_ids:
                os.remove(os.path.join(face_dir, name))
                removed += 1
        for name in thumb_files:
            if name.endswith(".jpg") and name not in valid_thumbs:
                thumb_path = os.path.join(thumb_dir, name)
                evict_cached_image(thumb_path)
                os.remove(thumb_path)
                removed += 1
        if orphan_faces or removed:
            print(f"Limpieza: {orphan_faces} caras huérfanas en la BD y {removed} ficheros de caché sin uso.")
    except Exception as e:
        print(f"Error limpiando cachés huérfanas: {e}")
    trim_drive_caches()


class FaceLoader(QRunnable):
    def __init__(self, signals: FaceLoaderSignals, face_id: int, photo_path: str, location_str: str):
        super().__init__()
        self.signals = signals
        self.face_id = face_id
        self.photo_path = photo_path
        self.location_str = location_str

        self.cache_path = get_face_cache_path(self.face_id)

    @Slot()
    def run(self):
        try:
            image = QImage()  # QPixmap no puede usarse fuera del hilo de la UI

            # 1. INTENTO DE CARGA RÁPIDA (CACHÉ)
            if os.path.exists(self.cache_path):
                if image.load(self.cache_path):
                    try:
                        self.signals.face_loaded.emit(self.face_id, image, self.photo_path)
                    except RuntimeError:
                        pass # Ignorar si la app se cerró mientras cargábamos
                    return

            # 2. SI NO EXISTE CACHÉ: PROCESO LENTO (Abrir original y recortar)
            location = ast.literal_eval(self.location_str)
            (top, right, bottom, left) = location

            file_suffix = Path(self.photo_path).suffix.lower()

            img = None

            if file_suffix in RAW_EXTENSIONS:
                try:
                    with rawpy.imread(self.photo_path) as raw:
                        rgb_array = raw.postprocess()
                        img = Image.fromarray(rgb_array)
                except Exception as e:
                    # print(f"Error rawpy en FaceLoader: {e}")
                    raise e
            else:
                img = Image.open(self.photo_path)

            if img is None:
                raise Exception("No se pudo cargar la imagen base")

            # Recortar la cara
            face_image_pil = img.crop((left, top, right, bottom))

            # 3. GUARDAR EN CACHÉ
            try:
                if face_image_pil.mode != "RGB":
                    face_image_pil = face_image_pil.convert("RGB")
                face_image_pil.save(self.cache_path, "JPEG", quality=90)
            except Exception as e:
                print(f"No se pudo guardar caché para cara {self.face_id}: {e}")

            # 4. Convertir a QImage
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.ReadWrite)
            face_image_pil.save(buffer, "PNG")
            image.loadFromData(buffer.data())
            buffer.close()

            if image.isNull():
                raise Exception("Imagen nula después de la conversión.")

            # --- PROTECCIÓN CONTRA CIERRE ---
            try:
                self.signals.face_loaded.emit(self.face_id, image, self.photo_path)
            except RuntimeError:
                pass # App cerrada, no hacer nada

        except Exception:
            # Si falla, emitimos señal de fallo, pero también protegida
            try:
                self.signals.face_load_failed.emit(self.face_id)
            except RuntimeError:
                pass # App cerrada

# =================================================================
# SEÑALES Y WORKER PARA AGRUPAR CARAS (CLUSTERING)
# =================================================================
class ClusterSignals(QObject):
    clusters_found = Signal(list)
    clustering_progress = Signal(str)
    clustering_finished = Signal()

class ClusterWorker(QRunnable):
    def __init__(self, signals: ClusterSignals, db_path: str):
        super().__init__()
        self.signals = signals
        self.db_path = db_path

    @Slot()
    def run(self):
        local_db = VisageVaultDB.for_worker(self.db_path)

        try:
            self.signals.clustering_progress.emit("Cargando datos de caras...")
            face_data = local_db.get_unknown_face_encodings()

            if len(face_data) < 2:
                self.signals.clustering_progress.emit("No hay suficientes caras para comparar.")
                self.signals.clusters_found.emit([])
                self.signals.clustering_finished.emit()
                return

            # ... (Resto de lógica igual que antes) ...

            self.signals.clustering_progress.emit(f"Comparando {len(face_data)} caras...")
            face_ids = [data[0] for data in face_data]
            encodings = np.array([data[1] for data in face_data])

            clt = DBSCAN(eps=0.4, min_samples=2, metric="euclidean")
            clt.fit(encodings)

            clusters = {}
            for face_id, label in zip(face_ids, clt.labels_):
                if label == -1:
                    continue
                if label not in clusters:
                    clusters[label] = []
                clusters[label].append(face_id)

            final_clusters_list = list(clusters.values())
            self.signals.clustering_progress.emit(f"Se encontraron {len(final_clusters_list)} grupos.")
            self.signals.clusters_found.emit(final_clusters_list)

        except Exception as e:
            print(f"Error crítico en el ClusterWorker: {e}")
            self.signals.clustering_progress.emit(f"Error: {e}")
        finally:
            local_db.conn.close()
            self.signals.clustering_finished.emit()

# =================================================================
# CLASE PARA MOSTRAR CARAS RECORTADAS
# =================================================================
class CircularFaceLabel(QLabel):
    clicked = Signal()
    rightClicked = Signal(QPoint)
    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.setFixedSize(100, 100)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Cara detectada (Haz clic para etiquetar)")
        self.setAlignment(Qt.AlignCenter)
        self._pixmap = QPixmap()
        if pixmap and not pixmap.isNull():
            self.setPixmap(pixmap)
    def setPixmap(self, pixmap: QPixmap):
        if pixmap.isNull():
            self._pixmap = QPixmap()
        else:
            self._pixmap = pixmap.scaled(100, 100, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.update()
    def paintEvent(self, event: QPaintEvent):
        if self._pixmap.isNull():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addEllipse(0, 0, self.width(), self.height())
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, self._pixmap)
        painter.end()
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        elif event.button() == Qt.RightButton:
            self.rightClicked.emit(event.globalPos())
        super().mousePressEvent(event)

# =================================================================
# CLASE: ZoomableClickableLabel (Corregida)
# =================================================================
class ZoomableClickableLabel(QLabel):
    doubleClickedPath = Signal(str)

    def __init__(self, original_path=None, parent=None):
        super().__init__(parent)
        self.original_path = original_path
        self.setAlignment(Qt.AlignCenter)
        self.setMouseTracking(True)
        self._original_pixmap = QPixmap()
        self._current_scale = 1.0
        self._scale_factor = 1.15
        self._view_offset = QPointF(0.0, 0.0)
        self._panning = False
        self._last_mouse_pos = QPoint()
        self.is_thumbnail_view = False
        self.setCursor(Qt.OpenHandCursor)

    def setOriginalPixmap(self, pixmap: QPixmap):
        if pixmap.isNull():
            self._original_pixmap = QPixmap()
        else:
            self._original_pixmap = pixmap

        # Reseteamos variables
        self._current_scale = 1.0
        self._view_offset = QPointF(0.0, 0.0)

        # ¡IMPORTANTE! Calcular el ajuste inicial inmediatamente
        self.fitToWindow()

    def fitToWindow(self):
        """Ajusta la imagen para que quepa perfectamente en la ventana."""
        if self._original_pixmap.isNull():
            return

        # --- CORRECCIÓN: Obtener dimensiones reales disponibles ---
        # Si el label aún no se ha "estirado" (ancho < 100), usamos el tamaño de la ventana padre.
        # Esto soluciona que la foto salga minúscula al abrirse.
        view_width = self.width()
        view_height = self.height()

        if view_width < 100 and self.window():
            view_width = self.window().width()
            view_height = self.window().height()

        if view_width <= 0 or view_height <= 0: return

        # Calculamos ratios usando esas dimensiones corregidas
        x_ratio = view_width / self._original_pixmap.width()
        y_ratio = view_height / self._original_pixmap.height()

        # Ajustamos la escala para que ocupe el MÁXIMO posible (llenar pantalla)
        self._current_scale = min(x_ratio, y_ratio)

        # Centramos
        self._view_offset = QPointF(0, 0)

        # Aplicamos límites y actualizamos
        self._clamp_view_offset()
        self.update()

    def wheelEvent(self, event):
        if event.modifiers() == Qt.ControlModifier:
            if self.is_thumbnail_view:
                if event.angleDelta().y() < 0:
                    self._open_preview()
                else:
                    super().wheelEvent(event)
            else:
                if event.angleDelta().y() > 0:
                    # Intentar cerrar si es el visor
                    win = self.window()
                    if win.property("is_lightbox"):
                        win.close_with_animation()
            return
        if self.is_thumbnail_view:
            super().wheelEvent(event)
            return
        if self._original_pixmap.isNull():
            return
        old_scale = self._current_scale
        if event.angleDelta().y() > 0:
            self._current_scale *= self._scale_factor
        else:
            self._current_scale /= self._scale_factor
        mouse_pos_in_label = event.position()
        original_img_coords_before_zoom = QPointF(
            self._view_offset.x() + (mouse_pos_in_label.x() / old_scale),
            self._view_offset.y() + (mouse_pos_in_label.y() / old_scale)
        )
        self._view_offset = QPointF(
            original_img_coords_before_zoom.x() - (mouse_pos_in_label.x() / self._current_scale),
            original_img_coords_before_zoom.y() - (mouse_pos_in_label.y() / self._current_scale)
        )
        self._clamp_view_offset()
        self.update()

    def mousePressEvent(self, event):
        # Si estamos en modo miniatura, el comportamiento es el estándar
        if self.is_thumbnail_view:
            super().mousePressEvent(event)
            return

        # --- LÓGICA DE DETECCIÓN DE CLIC EN ZONA NEGRA ---
        if event.button() == Qt.LeftButton:
            # 1. Calcular tamaño visual real de la imagen escalada
            scaled_w = self._original_pixmap.width() * self._current_scale
            scaled_h = self._original_pixmap.height() * self._current_scale

            # 2. Calcular dónde empieza la imagen (centrado)
            # Si la imagen es más pequeña que la ventana, hay margen (x > 0).
            # Si es más grande, ocupa todo (x = 0).
            x_start = (self.width() - scaled_w) / 2 if scaled_w < self.width() else 0
            y_start = (self.height() - scaled_h) / 2 if scaled_h < self.height() else 0

            # 3. Crear el rectángulo que ocupa la imagen REALMENTE en pantalla
            # Ajuste: Si la imagen es gigante (zoom), el rect válido es toda la pantalla
            img_rect = QRectF(x_start, y_start, scaled_w, scaled_h)

            # 4. Comprobar si el clic está DENTRO de la imagen
            if not img_rect.contains(event.position()):
                # ¡CLIC EN LO NEGRO! -> Ignoramos el evento.
                # Esto hará que Qt se lo pase automáticamente al padre (ImagePreviewDialog)
                event.ignore()
                return

            # Si llegamos aquí, el clic fue DENTRO de la imagen -> Iniciamos Paneo (arrastrar)
            self._panning = True
            self._last_mouse_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept() # Marcamos que hemos usado el evento

    def mouseMoveEvent(self, event):
        if self._panning and not self.is_thumbnail_view:
            # Calculamos cuánto se ha movido el ratón
            delta = event.position().toPoint() - self._last_mouse_pos
            self._last_mouse_pos = event.position().toPoint()

            # Ajustamos el offset inversamente al movimiento y ajustado a la escala
            # (Si muevo ratón a la derecha, quiero ver la parte izquierda de la foto -> resto X)
            self._view_offset.setX(self._view_offset.x() - (delta.x() / self._current_scale))
            self._view_offset.setY(self._view_offset.y() - (delta.y() / self._current_scale))

            self._clamp_view_offset()
            self.update()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and not self.is_thumbnail_view:
            self._panning = False
            self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        # Si es miniatura, emitimos la señal para abrir el visor
        if self.is_thumbnail_view and self.original_path:
            self.doubleClickedPath.emit(self.original_path)

        # Si YA estamos en el visor (pantalla completa), el doble clic resetea el zoom
        if not self.is_thumbnail_view:
            self.fitToWindow()

        super().mouseDoubleClickEvent(event)

    def _clamp_view_offset(self):
        """Asegura que no 'nos salgamos' de la foto al arrastrar."""
        if self._original_pixmap.isNull() or self._current_scale == 0:
            return

        # Ancho y alto de la "ventana" proyectada sobre la imagen original
        viewport_width = self.width() / self._current_scale
        viewport_height = self.height() / self._current_scale

        img_width = self._original_pixmap.width()
        img_height = self._original_pixmap.height()

        # EJE X
        if img_width <= viewport_width:
            # Si la imagen cabe entera, centramos el offset (o lo dejamos a 0)
            # En realidad, si cabe entera, el paintEvent se encarga de centrar el target.
            # Aquí solo nos aseguramos de no tener offsets locos.
            self._view_offset.setX(0)
        else:
            # Si la imagen es más grande, permitimos movernos hasta el borde
            max_x = img_width - viewport_width
            # Clamp: limitamos entre 0 y el máximo posible
            new_x = max(0.0, min(self._view_offset.x(), max_x))
            self._view_offset.setX(new_x)

        # EJE Y (Misma lógica)
        if img_height <= viewport_height:
            self._view_offset.setY(0)
        else:
            max_y = img_height - viewport_height
            new_y = max(0.0, min(self._view_offset.y(), max_y))
            self._view_offset.setY(new_y)

    def paintEvent(self, event: QPaintEvent):
        if self.is_thumbnail_view:
            super().paintEvent(event)
            return

        if self._original_pixmap.isNull():
            return

        painter = QPainter(self)
        # Usamos transformación bilineal/suave para que no se pixele al hacer zoom
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.Antialiasing)

        # Dimensiones de la imagen escalada
        scaled_w = self._original_pixmap.width() * self._current_scale
        scaled_h = self._original_pixmap.height() * self._current_scale

        # 1. Calcular TARGET (Dónde pintamos en la pantalla)
        # Si la imagen es pequeña, la centramos. Si es grande, ocupamos toda la pantalla.
        target_x = (self.width() - scaled_w) / 2.0 if scaled_w < self.width() else 0.0
        target_y = (self.height() - scaled_h) / 2.0 if scaled_h < self.height() else 0.0

        # El rectángulo destino es el mínimo entre el tamaño escalado y el tamaño del widget
        target_w = min(scaled_w, float(self.width()))
        target_h = min(scaled_h, float(self.height()))

        target_rect = QRectF(target_x, target_y, target_w, target_h)

        # 2. Calcular SOURCE (Qué trozo de la imagen original cogemos)
        src_x = self._view_offset.x()
        src_y = self._view_offset.y()

        # El ancho/alto origen es el ancho/alto destino "des-escalado"
        src_w = target_w / self._current_scale
        src_h = target_h / self._current_scale

        source_rect = QRectF(src_x, src_y, src_w, src_h)

        # 3. INTERSECCIÓN DE SEGURIDAD (Evita errores de redondeo en los bordes)
        # Nos aseguramos de que no pedimos píxeles fuera de la imagen original
        img_rect = QRectF(self._original_pixmap.rect())
        source_rect = source_rect.intersected(img_rect)

        painter.drawPixmap(target_rect, self._original_pixmap, source_rect)
        painter.end()

    def resizeEvent(self, event):
        # Si estamos en el visor grande
        if not self.is_thumbnail_view:
            # Si la imagen es muy pequeña (acaba de arrancar), forzamos el ajuste
            if self.width() < 100 or self._current_scale == 1.0:
                self.fitToWindow()
            else:
                self._clamp_view_offset()
                self.update()
        super().resizeEvent(event)

    def _open_preview(self):
        # Importación local para evitar ciclos si ImagePreviewDialog está abajo
        # (Aunque en este orden ya no hace falta, es buena práctica)
        if ImagePreviewDialog.is_showing:
            return
        if not self.original_path:
            return
        full_pixmap = QPixmap(self.original_path)
        if full_pixmap.isNull():
            return
        preview_dialog = ImagePreviewDialog(full_pixmap, self)
        preview_dialog.show_with_animation()

# =================================================================
# CLASE: PreviewListWidget (Limpia)
# =================================================================
class PreviewListWidget(QListWidget):
    """
    QListWidget que auto-ajusta su altura basándose en el contenido real.
    """
    previewRequested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setUniformItemSizes(False) # Clave para que la selección se ajuste
        self.setResizeMode(QListWidget.Adjust)
        self.setViewMode(QListWidget.IconMode)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if item:
                data = item.data(Qt.UserRole)
                if data:
                    self.previewRequested.emit(data)
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Escape:
            for widget in QApplication.allWidgets():
                if widget.__class__.__name__ == "ImagePreviewDialog" and widget.isVisible():
                    if hasattr(widget, 'close_with_animation'):
                        widget.close_with_animation()
                    else:
                        widget.close()
                    event.accept()
                    return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        # Selección con Shift
        if event.button() == Qt.LeftButton and (event.modifiers() & Qt.ShiftModifier):
            item_clicked = self.itemAt(event.position().toPoint())
            current_anchor = self.currentItem()
            if item_clicked and current_anchor:
                start_row = self.row(current_anchor)
                end_row = self.row(item_clicked)
                low = min(start_row, end_row)
                high = max(start_row, end_row)
                if not (event.modifiers() & Qt.ControlModifier):
                    self.clearSelection()
                for i in range(low, high + 1):
                    self.item(i).setSelected(True)
                self.setCurrentItem(item_clicked)
                return
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        """Al redimensionar la ventana, recalculamos la altura."""
        super().resizeEvent(event)
        self.adjust_height_to_content()

    def adjust_height_to_content(self):
        """Calcula la altura exacta basándose en la posición del último ítem."""
        count = self.count()
        if count == 0: return

        # Forzar el cálculo de posición de los ítems
        self.doItemsLayout()

        # Obtener el rectángulo visual del ÚLTIMO ítem
        last_item_rect = self.visualItemRect(self.item(count - 1))

        if last_item_rect.isValid():
            # La altura necesaria es el fondo del último ítem + margen
            new_height = last_item_rect.bottom() + self.spacing() + 10

            # Solo aplicamos si hay cambio para evitar bucles
            if self.height() != new_height and new_height > 0:
                self.setFixedHeight(new_height)

# =================================================================
# CLASE PARA VISTA PREVIA CON ZOOM (ImagePreviewDialog)
# =================================================================
class ImagePreviewDialog(QDialog):
    # Solo un visor abierto a la vez. Se libera al cerrarse de CUALQUIER forma
    # (animación, Alt+F4, destrucción de la ventana padre...): si se quedara a
    # True, no se podría volver a abrir ninguna vista previa.
    is_showing = False

    @staticmethod
    def _release():
        ImagePreviewDialog.is_showing = False

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        ImagePreviewDialog.is_showing = True
        self.destroyed.connect(ImagePreviewDialog._release)
        self._closing = False

        # Identificador para que el Label sepa que es un visor
        self.setProperty("is_lightbox", True)

        # Estilo Pantalla Completa y Fondo Transparente
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 230);") # Fondo oscuro

        self._pixmap = pixmap

        self.label = ZoomableClickableLabel(parent=self)
        self.label.is_thumbnail_view = False
        self.label.setStyleSheet("background-color: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

        self.animation = QPropertyAnimation(self, b"geometry")

    def show_with_animation(self):
        screen = QApplication.screenAt(QCursor.pos())
        if not screen:
            screen = QApplication.primaryScreen()
        screen_geom = screen.availableGeometry()

        self.setGeometry(screen_geom)
        self.label.setOriginalPixmap(self._pixmap)

        # Animación de apertura
        start_rect = QRect(screen_geom.center().x(), screen_geom.center().y(), 0, 0)
        end_rect = screen_geom

        self.animation.setDuration(200)
        self.animation.setStartValue(start_rect)
        self.animation.setEndValue(end_rect)
        self.animation.setEasingCurve(QEasingCurve.OutQuad)
        self.animation.start()

        self.show()

    def close_with_animation(self):
        # Esc, perder el foco y hacer clic pueden llegar a la vez: cerrar una sola vez
        if self._closing:
            return
        self._closing = True
        end_pos = QCursor.pos()
        end_geom = QRect(end_pos.x(), end_pos.y(), 1, 1)
        start_geom = self.geometry()

        self.animation.setDuration(200)
        self.animation.setStartValue(start_geom)
        self.animation.setEndValue(end_geom)
        self.animation.setEasingCurve(QEasingCurve.InQuad)
        self.animation.finished.connect(self._handle_close_animation_finished)
        self.animation.start()

    def _handle_close_animation_finished(self):
        self.accept()

    def done(self, result):
        # Pasa por aquí cualquier cierre del diálogo (accept, reject, Alt+F4)
        ImagePreviewDialog._release()
        super().done(result)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Escape:
            self.close_with_animation()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        if self.label._current_scale == 1.0:
            self.label.fitToWindow()
        super().resizeEvent(event)

    def changeEvent(self, event):
        """Detecta si la ventana pierde el foco (clic fuera de la app)."""
        if event.type() == QEvent.ActivationChange:
            # Si la ventana deja de ser la activa, cerramos
            if not self.isActiveWindow():
                self.close_with_animation()
        super().changeEvent(event)

    def mousePressEvent(self, event):
        """
        Este evento se activa si el usuario hace clic en el fondo (zona negra),
        porque ZoomableClickableLabel habrá ignorado el evento.
        """
        if event.button() == Qt.LeftButton:
            self.close_with_animation()

# -----------------------------------------------------------------
# CLASE MODIFICADA: PhotoDetailDialog (¡CON SOPORTE RAW!)
# -----------------------------------------------------------------
class PhotoDetailDialog(QDialog):
    metadata_changed = Signal(str, str, str)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        self.main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.main_splitter)

        # Panel Izquierdo: Imagen
        self.image_label = ZoomableClickableLabel(self.original_path, self)
        self.image_label.is_thumbnail_view = False
        self.main_splitter.addWidget(self.image_label)

        # Panel Derecho: Solo fechas (SIN EXIF)
        right_panel_widget = QWidget()
        right_panel_layout = QVBoxLayout(right_panel_widget)
        right_panel_widget.setMinimumWidth(250)
        right_panel_widget.setMaximumWidth(350)

        date_group = QGroupBox("Editar Fecha")
        date_layout = QGridLayout(date_group)

        date_layout.addWidget(QLabel("Año:"), 0, 0)
        self.year_edit = QLineEdit()
        self.year_edit.setPlaceholderText("Ej: 2024")
        date_layout.addWidget(self.year_edit, 0, 1)

        date_layout.addWidget(QLabel("Mes:"), 1, 0)
        self.month_combo = QComboBox()
        self.month_combo.addItem("Mes Desconocido", "00")
        for i in range(1, 13):
            month_str = str(i).zfill(2)
            try:
                month_name = datetime.datetime.strptime(month_str, "%m").strftime("%B").capitalize()
            except ValueError:
                month_name = str(i)
            self.month_combo.addItem(month_name, month_str)
        date_layout.addWidget(self.month_combo, 1, 1)

        right_panel_layout.addWidget(date_group)
        right_panel_layout.addStretch(1) # Relleno para empujar hacia arriba

        self.main_splitter.addWidget(right_panel_widget)

        # Botones
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self._save_metadata)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

        # Ajuste de tamaños (más espacio para la foto)
        self.main_splitter.setSizes([800, 250])

    def __init__(self, original_path, db_manager: VisageVaultDB, parent=None):
        super().__init__(parent)
        self.original_path = original_path
        self.db = db_manager
        self.setWindowTitle(Path(original_path).name)
        self.resize(1000, 800)

        self._setup_ui()
        self._load_photo()
        self._load_current_date() # Renombrado de _load_metadata

    def _load_photo(self):
        try:
            self.image_label.setOriginalPixmap(load_full_pixmap(self.original_path))
        except Exception as e:
            self.image_label.setText(f"Error: {e}")

    def _load_current_date(self):
        """Carga solo la fecha actual de la BD o del archivo."""
        current_year, current_month = self.db.get_photo_date(self.original_path)

        # Si no está en BD: por el nombre del archivo o su fecha de modificación
        if current_year is None or current_month is None:
            current_year, current_month = get_photo_date(self.original_path)

        self.year_edit.setText(current_year or "Sin Fecha")
        month_index = self.month_combo.findData(current_month or "00")
        self.month_combo.setCurrentIndex(month_index if month_index != -1 else 0)

    def _save_metadata(self):
        try:
            new_year_str = self.year_edit.text()
            new_month_str = self.month_combo.currentData()

            # Validación simple
            if not (new_year_str == "Sin Fecha" or (len(new_year_str) == 4 and new_year_str.isdigit())):
                QMessageBox.warning(self, "Datos Inválidos", "Año inválido.")
                return

            # Guardar en BD
            self.db.update_photo_date(self.original_path, new_year_str, new_month_str)

            # Notificar cambio
            self.metadata_changed.emit(self.original_path, new_year_str, new_month_str)
            self.accept()
        except Exception as e:
            print(f"Error al guardar: {e}")

# =================================================================
# CLASE: DIÁLOGO DE ETIQUETADO DE GRUPOS (CLUSTERS)
# =================================================================
class FaceClusterDialog(QDialog):
    SkipRole = QDialog.Accepted + 1
    DeleteRole = QDialog.Accepted + 2
    def __init__(self, db: VisageVaultDB, threadpool: QThreadPool,
                 face_ids: list, parent=None):
        super().__init__(parent)
        self.db = db
        self.threadpool = threadpool
        self.face_ids = face_ids
        self.local_face_signals = FaceLoaderSignals()
        self.local_face_signals.face_loaded.connect(self._on_dialog_face_loaded)
        self.setWindowTitle(f"Agrupar {len(self.face_ids)} Caras")
        self.setMinimumSize(600, 400)
        self.person_id_to_save = None
        self._setup_ui()
        self._load_people_combo()
        self._load_faces_async()
    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        face_scroll_area = QScrollArea()
        face_scroll_area.setWidgetResizable(True)
        face_widget = QWidget()
        self.face_grid_layout = QGridLayout(face_widget)
        self.face_grid_layout.setSpacing(10)
        face_scroll_area.setWidget(face_widget)
        main_layout.addWidget(face_scroll_area, 1)
        assign_group = QGroupBox("Asignar Persona")
        assign_layout = QGridLayout(assign_group)
        assign_layout.addWidget(QLabel("Persona Existente:"), 0, 0)
        self.people_combo = QComboBox()
        self.people_combo.currentIndexChanged.connect(self._on_combo_changed)
        assign_layout.addWidget(self.people_combo, 0, 1)
        assign_layout.addWidget(QLabel("O Nueva Persona:"), 1, 0)
        self.new_person_edit = QLineEdit()
        self.new_person_edit.setPlaceholderText("Ej: Ana García")
        self.new_person_edit.textChanged.connect(self._on_text_changed)
        assign_layout.addWidget(self.new_person_edit, 1, 1)
        main_layout.addWidget(assign_group)
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.skip_button = self.button_box.addButton("Siguiente", QDialogButtonBox.ButtonRole.ActionRole)
        self.skip_button.clicked.connect(self._skip)
        self.delete_button = self.button_box.addButton("Eliminar caras", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.delete_button.clicked.connect(self._delete_and_reject)
        self.button_box.accepted.connect(self._save_and_accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)
    def _load_people_combo(self):
        self.people_combo.addItem("--- Seleccionar ---", -1)
        people = self.db.get_all_people()
        for person_row in people:
            person_id = person_row['id']
            person_name = person_row['name']
            self.people_combo.addItem(person_name, person_id)
    def _load_faces_async(self):
        num_cols = max(1, (self.width() - 50) // 110)
        for i, face_id in enumerate(self.face_ids):
            face_widget = CircularFaceLabel(QPixmap())
            face_widget.setText("Cargando...")
            face_widget.setProperty("face_id", face_id)
            face_widget.clicked.connect(self._show_face_preview)
            row, col = i // num_cols, i % num_cols
            self.face_grid_layout.addWidget(face_widget, row, col, Qt.AlignTop)
            face_info = self.db.get_face_info(face_id)
            if face_info:
                loader = FaceLoader(
                    self.local_face_signals,
                    face_id,
                    face_info['filepath'],
                    face_info['location']
                )
                self.threadpool.start(loader)
    @Slot()
    def _on_combo_changed(self):
        if self.people_combo.currentIndex() > 0:
            self.new_person_edit.clear()
    @Slot()
    def _on_text_changed(self, text):
        if text:
            self.people_combo.setCurrentIndex(0)
    @Slot()
    def _save_and_accept(self):
        try:
            new_name = self.new_person_edit.text().strip()
            selected_id = self.people_combo.currentData()
            if new_name:
                person_id = self.db.add_person(new_name)
                if person_id == -1:
                    existing = self.db.get_person_by_name(new_name)
                    person_id = existing['id']
                self.person_id_to_save = person_id
            elif selected_id != -1:
                self.person_id_to_save = selected_id
            else:
                QMessageBox.warning(self, "Acción Requerida",
                                    "Por favor, selecciona una persona existente o escribe un nombre nuevo.")
                return
            if self.person_id_to_save:
                for face_id in self.face_ids:
                    self.db.restore_face(face_id)
                    self.db.link_face_to_person(face_id, self.person_id_to_save)
                self.accept()
        except Exception as e:
            print(f"Error al guardar el cluster: {e}")
    @Slot(int, QImage, str)
    def _on_dialog_face_loaded(self, face_id: int, image: QImage, photo_path: str):
        pixmap = QPixmap.fromImage(image)  # Conversión en el hilo de la UI
        for i in range(self.face_grid_layout.count()):
            widget = self.face_grid_layout.itemAt(i).widget()
            if widget and hasattr(widget, 'property') and widget.property("face_id") == face_id:
                widget.setPixmap(pixmap)
                widget.setText("")
                widget.setProperty("photo_path", photo_path)
                break
    @Slot()
    @Slot()
    def _show_face_preview(self):
        sender_widget = self.sender()
        if not sender_widget:
            return

        photo_path = sender_widget.property("photo_path")
        if not photo_path:
            print("Por favor, espera a que la cara termine de cargar.")
            return

        # --- SOPORTE RAW PARA VISTA PREVIA ---
        try:
            full_pixmap = load_full_pixmap(photo_path)

            if full_pixmap.isNull():
                print(f"Error: No se pudo cargar la imagen completa de {photo_path}")
                return

            preview_dialog = ImagePreviewDialog(full_pixmap, self)
            preview_dialog.setModal(True)
            preview_dialog.show_with_animation()

        except Exception as e:
            print(f"Error al mostrar preview de cara: {e}")

    @Slot()
    def _skip(self):
        self.done(self.SkipRole)
    @Slot()
    def _delete_and_reject(self):
        if self.face_ids:
            for face_id in self.face_ids:
                self.db.soft_delete_face(face_id)
        self.done(self.DeleteRole)

# =================================================================
# CLASE: DIÁLOGO PARA CAMBIO RÁPIDO DE FECHA
# =================================================================
class DateChangeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cambiar Fecha")
        self.setFixedSize(300, 150)

        layout = QVBoxLayout(self)

        # Formulario
        form_layout = QGridLayout()

        # Año
        form_layout.addWidget(QLabel("Año (AAAA):"), 0, 0)
        self.year_edit = QLineEdit()
        self.year_edit.setPlaceholderText("Ej: 2024")
        self.year_edit.setMaxLength(4)
        form_layout.addWidget(self.year_edit, 0, 1)

        # Mes
        form_layout.addWidget(QLabel("Mes:"), 1, 0)
        self.month_combo = QComboBox()
        # Añadir meses
        self.month_combo.addItem("Enero", "01")
        self.month_combo.addItem("Febrero", "02")
        self.month_combo.addItem("Marzo", "03")
        self.month_combo.addItem("Abril", "04")
        self.month_combo.addItem("Mayo", "05")
        self.month_combo.addItem("Junio", "06")
        self.month_combo.addItem("Julio", "07")
        self.month_combo.addItem("Agosto", "08")
        self.month_combo.addItem("Septiembre", "09")
        self.month_combo.addItem("Octubre", "10")
        self.month_combo.addItem("Noviembre", "11")
        self.month_combo.addItem("Diciembre", "12")
        self.month_combo.addItem("Desconocido", "00")

        # Seleccionar el mes actual por defecto
        current_month_idx = datetime.datetime.now().month - 1
        self.month_combo.setCurrentIndex(current_month_idx)

        form_layout.addWidget(self.month_combo, 1, 1)
        layout.addLayout(form_layout)

        # Botones
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._validate_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _validate_and_accept(self):
        year = self.year_edit.text().strip()

        # Validación: Debe ser 4 dígitos numéricos
        if not year.isdigit() or len(year) != 4:
            QMessageBox.warning(self, "Año incorrecto", "Por favor, escribe un año válido de 4 cifras (ej: 2025).")
            return

        self.accept()

    def get_data(self):
        return self.year_edit.text().strip(), self.month_combo.currentData()

# =================================================================
# CLASE TRABAJADORA DEL ESCANEO DE FOTOS
# =================================================================
class PhotoFinderWorker(QObject):
    # (fechas | None si la carpeta no está disponible, rutas desaparecidas a confirmar)
    finished = Signal(object, list)
    progress = Signal(str)

    # Recibimos db_path (texto) en lugar de db_manager (objeto)
    def __init__(self, directory_path: str, db_path: str, scan_id=None):
        super().__init__()
        self.directory_path = directory_path
        self.db_path = db_path
        self.scan_id = scan_id  # Compartir el recorrido del disco con el otro escáner
        self.is_running = True

    @Slot()
    def run(self):
        # Abrimos nuestra propia conexión segura
        local_db = VisageVaultDB.for_worker(self.db_path)

        photos_by_year_month = {}
        available = True
        pending_missing = []
        try:
            self.progress.emit("Cargando fechas de fotos conocidas desde la BD...")
            db_dates = local_db.load_all_photo_dates()

            self.progress.emit("Escaneando archivos de FOTOS en el directorio...")
            if not os.path.isdir(self.directory_path):
                # Disco o unidad de red desconectado: no se modifica la biblioteca
                available = False
                self.progress.emit(f"⚠️ La carpeta {self.directory_path} no está disponible. No se ha modificado la biblioteca.")
                return
            photo_paths_on_disk = find_photos(self.directory_path, should_stop=lambda: not self.is_running, scan_id=self.scan_id)
            photo_paths_on_disk_set = set(photo_paths_on_disk)

            photos_to_upsert_in_db = []

            for path in photo_paths_on_disk:
                if not self.is_running:
                    break
                if path in db_dates:
                    year, month = db_dates[path]
                else:
                    self.progress.emit(f"Procesando nueva foto: {Path(path).name}")
                    year, month = get_photo_date(path)

                    photos_to_upsert_in_db.append((path, year, month))

                # Una fecha vacía en la BD no debe romper la ordenación de la galería
                year, month = year or NO_DATE_YEAR, month or NO_DATE_MONTH

                if year not in photos_by_year_month:
                    photos_by_year_month[year] = {}
                if month not in photos_by_year_month[year]:
                    photos_by_year_month[year][month] = []
                photos_by_year_month[year][month].append(path)

            if not self.is_running:
                # Escaneo interrumpido (cierre de la app): la lista está incompleta,
                # no se borra ni se guarda nada en la BD
                return

            self.progress.emit("Buscando fotos eliminadas...")
            known_paths, missing_paths = find_missing_paths(db_dates.keys(), photo_paths_on_disk_set, self.directory_path)

            if needs_removal_confirmation(len(missing_paths), len(known_paths)):
                # Posible disco desmontado: decide el usuario (en el hilo principal)
                pending_missing = missing_paths
            elif missing_paths:
                self.progress.emit(f"Eliminando {len(missing_paths)} fotos de la BD...")
                for path in missing_paths:
                    purge_media_caches(local_db.conn, path)
                local_db.bulk_delete_photos(missing_paths)

            if photos_to_upsert_in_db:
                self.progress.emit(f"Guardando {len(photos_to_upsert_in_db)} fotos nuevas en la BD...")
                local_db.bulk_upsert_photos(photos_to_upsert_in_db)

            self.progress.emit(f"Escaneo de fotos finalizado. Encontradas {len(photo_paths_on_disk)} fotos.")

        except Exception as e:
            print(f"Error crítico en el hilo PhotoFinderWorker: {e}")
            self.progress.emit(f"Error en escaneo de fotos: {e}")
        finally:
            # Cerramos conexión
            local_db.conn.close()
            self.finished.emit(photos_by_year_month if available else None, pending_missing)

# =================================================================
# CLASE TRABAJADORA DEL ESCANEO DE VÍDEOS
# =================================================================
class VideoFinderWorker(QObject):
    # (fechas | None si la carpeta no está disponible, rutas desaparecidas a confirmar)
    finished = Signal(object, list)
    progress = Signal(str)

    def __init__(self, directory_path: str, db_path: str, scan_id=None):
        super().__init__()
        self.directory_path = directory_path
        self.db_path = db_path
        self.scan_id = scan_id  # Compartir el recorrido del disco con el otro escáner
        self.is_running = True

    @Slot()
    def run(self):
        local_db = VisageVaultDB.for_worker(self.db_path)

        videos_by_year_month = {}
        available = True
        pending_missing = []
        try:
            self.progress.emit("Cargando fechas de vídeos conocidas desde la BD...")
            db_dates = local_db.load_all_video_dates()

            self.progress.emit("Escaneando archivos de VÍDEOS en el directorio...")
            if not os.path.isdir(self.directory_path):
                # Disco o unidad de red desconectado: no se modifica la biblioteca
                available = False
                self.progress.emit(f"⚠️ La carpeta {self.directory_path} no está disponible. No se ha modificado la biblioteca.")
                return
            video_paths_on_disk = find_videos(self.directory_path, should_stop=lambda: not self.is_running, scan_id=self.scan_id)
            video_paths_on_disk_set = set(video_paths_on_disk)

            videos_to_upsert_in_db = []

            for path in video_paths_on_disk:
                if not self.is_running:
                    break
                if path in db_dates:
                    year, month = db_dates[path]
                else:
                    self.progress.emit(f"Procesando nuevo vídeo: {Path(path).name}")
                    year, month = get_video_date(path)

                    videos_to_upsert_in_db.append((path, year, month))

                year, month = year or NO_DATE_YEAR, month or NO_DATE_MONTH

                if year not in videos_by_year_month:
                    videos_by_year_month[year] = {}
                if month not in videos_by_year_month[year]:
                    videos_by_year_month[year][month] = []
                videos_by_year_month[year][month].append(path)

            if not self.is_running:
                # Escaneo interrumpido (cierre de la app): la lista está incompleta,
                # no se borra ni se guarda nada en la BD
                return

            self.progress.emit("Buscando vídeos eliminados...")
            known_paths, missing_paths = find_missing_paths(db_dates.keys(), video_paths_on_disk_set, self.directory_path)

            if needs_removal_confirmation(len(missing_paths), len(known_paths)):
                # Posible disco desmontado: decide el usuario (en el hilo principal)
                pending_missing = missing_paths
            elif missing_paths:
                self.progress.emit(f"Eliminando {len(missing_paths)} vídeos de la BD...")
                for path in missing_paths:
                    purge_media_caches(local_db.conn, path)
                local_db.bulk_delete_videos(missing_paths)

            if videos_to_upsert_in_db:
                self.progress.emit(f"Guardando {len(videos_to_upsert_in_db)} vídeos nuevos en la BD...")
                local_db.bulk_upsert_videos(videos_to_upsert_in_db)

            self.progress.emit(f"Escaneo de vídeos finalizado. Encontrados {len(video_paths_on_disk)} vídeos.")

        except Exception as e:
            print(f"Error crítico en el hilo VideoFinderWorker: {e}")
            self.progress.emit(f"Error en escaneo de vídeos: {e}")
        finally:
            local_db.conn.close()
            self.finished.emit(videos_by_year_month if available else None, pending_missing)

# =================================================================
# CLASE TRABAJADORA DEL ESCANEO DE CARAS (CIERRE SEGURO)
# =================================================================
class FaceScanSignals(QObject):
    scan_progress = Signal(str)
    scan_percentage = Signal(int)
    face_found = Signal(int, str, str)
    scan_finished = Signal()

class FaceScanWorker(QObject):
    def __init__(self, db_path: str):
        super().__init__()
        self.db_path = db_path
        self.signals = FaceScanSignals()
        self.is_running = True
        self.executor = None # Referencia para poder matarlo desde fuera

    def stop(self):
        """Fuerza la detención inmediata de los hilos."""
        self.is_running = False
        if self.executor:
            # wait=False: No esperar a que terminen las tareas pendientes
            # cancel_futures=True: Cancelar las que están en cola (Python 3.9+)
            print("🛑 Forzando apagado del motor de IA...")
            self.executor.shutdown(wait=False, cancel_futures=True)

    @Slot()
    def run(self):
        local_db = VisageVaultDB.for_worker(self.db_path)

        try:
            self.signals.scan_progress.emit("Buscando fotos sin escanear...")
            unscanned_photos = local_db.get_unscanned_photos()
            total = len(unscanned_photos)

            if total == 0:
                self.signals.scan_progress.emit("No hay fotos nuevas.")
                self.signals.scan_percentage.emit(100)
                self.signals.scan_finished.emit()
                return

            self.signals.scan_progress.emit(f"Escaneando {total} fotos...")

            # WARMUP
            try:
                dummy = np.zeros((50, 50, 3), dtype=np.uint8)
                face_recognition.face_locations(dummy, model="hog")
            except Exception: pass

            max_workers = 1 # max_workers = min(4, os.cpu_count() or 2)
            processed_count = 0

            # Guardamos el executor en self para poder matarlo en stop()
            self.executor = ThreadPoolExecutor(max_workers=max_workers)

            with self.executor:
                future_to_photo = {}
                for row in unscanned_photos:
                    if not self.is_running: break
                    p_id = row['id']
                    p_path = row['filepath']

                    future = self.executor.submit(self._process_single_image, p_id, p_path)
                    future_to_photo[future] = (p_id, p_path)

                for future in as_completed(future_to_photo):
                    if not self.is_running:
                        # Si nos mandan parar, rompemos el bucle
                        break

                    photo_id, photo_path = future_to_photo[future]
                    try:
                        # Timeout pequeño para no bloquear eternamente si se cierra la app
                        result_data = future.result(timeout=0.1)

                        if result_data:
                            for (encoding_blob, location_str) in result_data:
                                face_db_id = local_db.add_face(photo_id, encoding_blob, location_str)
                                self.signals.face_found.emit(face_db_id, photo_path, location_str)

                        local_db.mark_photo_as_scanned(photo_id)

                    except TimeoutError:
                        # Si tarda mucho y estamos cerrando, ignorar
                        pass
                    except Exception:
                        # Foto ilegible: se marca para no reintentarla en cada escaneo
                        local_db.mark_photo_as_scanned(photo_id)

                    processed_count += 1
                    if processed_count % 5 == 0:
                        percentage = int((processed_count / total) * 100)
                        self.signals.scan_percentage.emit(percentage)
                        self.signals.scan_progress.emit(f"Analizando caras ({processed_count}/{total})...")

            self.signals.scan_finished.emit()

        except Exception as e:
            print(f"Escaneo de caras interrumpido: {e}")
            self.signals.scan_finished.emit()
        finally:
            # Asegurar limpieza final
            if self.executor:
                self.executor.shutdown(wait=False)
            try: local_db.conn.close()
            except: pass

    def _process_single_image(self, photo_id, photo_path):
        try:
            image = None
            file_suffix = Path(photo_path).suffix.lower()

            if file_suffix in RAW_EXTENSIONS:
                try:
                    with rawpy.imread(photo_path) as raw:
                        image = raw.postprocess()
                except Exception:
                    return None
            else:
                image = face_recognition.load_image_file(photo_path)

            if image is None: return None

            h, w = image.shape[:2]
            max_width = 1000
            scale_ratio = 1.0

            if w > max_width:
                scale_ratio = max_width / float(w)
                new_h = int(h * scale_ratio)
                pil_image = Image.fromarray(image)
                pil_image = pil_image.resize((max_width, new_h), Image.Resampling.LANCZOS)
                image = np.array(pil_image)

            locations = face_recognition.face_locations(image, model="hog")
            faces_found = []

            if locations:
                encodings = face_recognition.face_encodings(image, locations)
                for loc, enc in zip(locations, encodings):
                    if scale_ratio != 1.0:
                        top, right, bottom, left = loc
                        top = int(top / scale_ratio)
                        right = int(right / scale_ratio)
                        bottom = int(bottom / scale_ratio)
                        left = int(left / scale_ratio)
                        loc = (top, right, bottom, left)

                    faces_found.append((pickle.dumps(enc), str(loc)))
            return faces_found

        except Exception:
            return None

# =================================================================
# CLASE: DIÁLOGO DE AYUDA Y ACERCA DE
# =================================================================
# =================================================================
# CLASE: VIGILANTE DEL SISTEMA DE ARCHIVOS (AUTO-REFRESH)
# =================================================================
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class PhotoDirWatcher(QObject):
    """
    Vigila cambios en el directorio de fotos y emite señales para refrescar la UI.
    """
    directory_changed = Signal()

    def __init__(self, path_to_watch):
        super().__init__()
        self.path_to_watch = path_to_watch
        self.observer = Observer()
        self.handler = self.ChangeHandler(self.directory_changed)

    def start(self):
        if os.path.isdir(self.path_to_watch):
            self.observer.schedule(self.handler, self.path_to_watch, recursive=True)
            self.observer.start()
            # print(f"Vigilando cambios en: {self.path_to_watch}")

    def stop(self):
        if self.observer.is_alive():
            self.observer.stop()
            self.observer.join()

    class ChangeHandler(FileSystemEventHandler):
        # Solo cambios que alteran la biblioteca. Se ignoran "opened",
        # "closed_no_write" y "modified": leer fotos (miniaturas, caras...)
        # o retocar metadatos no debe lanzar un re-escaneo completo.
        # "closed" (cierre tras escribir) cubre el final de una copia.
        RELEVANT_EVENTS = ("created", "deleted", "moved", "closed")
        MEDIA_EXTENSIONS = tuple(IMAGE_EXTENSIONS + VIDEO_EXTENSIONS)

        def __init__(self, signal):
            self.signal = signal
            self.ignored_dirs = tuple(
                os.path.join(os.path.normpath(d), "") for d in (paths.cache_dir(), paths.safe_dir())
            )

        def _is_relevant_path(self, path, is_directory):
            if not path:
                return False
            path = os.fsdecode(path)
            if os.path.basename(path).startswith('.') or path.startswith(self.ignored_dirs):
                return False
            # Mover o borrar una carpeta entera no genera eventos de sus archivos
            return is_directory or path.lower().endswith(self.MEDIA_EXTENSIONS)

        def on_any_event(self, event):
            if event.event_type not in self.RELEVANT_EVENTS:
                return
            if event.is_directory and event.event_type == "created":
                return  # Sus archivos generarán sus propios eventos

            candidate_paths = (event.src_path, getattr(event, "dest_path", ""))
            if any(self._is_relevant_path(p, event.is_directory) for p in candidate_paths):
                # La app agrupa los eventos con un temporizador (refresh_timer)
                self.signal.emit()

# =================================================================
# DIÁLOGOS DE SEGURIDAD
# =================================================================
class CreatePasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crear Contraseña de Caja Fuerte")
        self.resize(300, 150)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Establece una contraseña para proteger tus fotos:"))
        self.pass1 = QLineEdit()
        self.pass1.setEchoMode(QLineEdit.Password)
        self.pass1.setPlaceholderText("Contraseña")
        layout.addWidget(self.pass1)

        self.pass2 = QLineEdit()
        self.pass2.setEchoMode(QLineEdit.Password)
        self.pass2.setPlaceholderText("Repetir Contraseña")
        layout.addWidget(self.pass2)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.validate)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.password = None

    def validate(self):
        p1 = self.pass1.text()
        p2 = self.pass2.text()
        if not p1:
            QMessageBox.warning(self, "Error", "La contraseña no puede estar vacía.")
            return
        if p1 != p2:
            QMessageBox.warning(self, "Error", "Las contraseñas no coinciden.")
            return
        self.password = p1
        self.accept()

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Acceso a Caja Fuerte")
        self.resize(300, 120)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Introduce tu contraseña:"))
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.pass_edit)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.validate)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.key = None
        self.legacy_key = None

    def validate(self):
        pwd = self.pass_edit.text()
        QApplication.setOverrideCursor(Qt.WaitCursor)  # scrypt tarda una fracción de segundo
        try:
            key = config_manager.unlock_safe(pwd)
        finally:
            QApplication.restoreOverrideCursor()
        if key:
            self.key = key
            # Necesaria para leer/migrar archivos de versiones antiguas
            self.legacy_key = safe_crypto.legacy_key(pwd)
            self.accept()
        else:
            QMessageBox.warning(self, "Error", "Contraseña incorrecta.")
            self.pass_edit.clear()

# =================================================================
# NUEVAS CLASES PARA BÚSQUEDA DE DUPLICADOS
# =================================================================

class DuplicateFinderWorker(QObject):
    """
    Busca fotos duplicadas en dos fases:
    1. Candidatas: misma huella visual (dHash de 64 bits). Es rápida, pero
       por sí sola agrupa imágenes distintas: fondos lisos, cielos con el
       mismo degradado o recortes de la misma escena.
    2. Confirmación de cada pareja: misma proporción y colores casi iguales
       (miniatura 16x16). Las imágenes casi sin detalle solo se consideran
       duplicadas si los archivos son idénticos byte a byte.
    Detecta la misma foto aunque tenga otra resolución o compresión.
    """
    progress = Signal(str)
    finished = Signal(dict)  # { 'clave_grupo': [ruta1, ruta2], ... }

    ASPECT_TOLERANCE = 0.02   # Diferencia relativa de proporción admitida
    MAX_COLOR_DIFF = 6.0      # Diferencia media por canal (0-255) en la miniatura 16x16
    MIN_DETAIL = 4.0          # Desviación típica (gris 32x32) por debajo = imagen "plana"

    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self.is_running = True
        self._file_hashes = {}

    def _fingerprint(self, image_path):
        """(dhash, proporción, miniatura 16x16 RGB, detalle) o None si no se puede leer."""
        try:
            with Image.open(image_path) as img:
                img.draft("RGB", (256, 256))  # JPEG: decodificar ya reducido
                img = ImageOps.exif_transpose(img).convert("RGB")
                width, height = img.size
                if not width or not height:
                    return None

                gray = img.convert("L")
                pixels = np.asarray(gray.resize((9, 8), Image.Resampling.BOX), dtype=np.int16)
                bits = (pixels[:, :-1] > pixels[:, 1:]).flatten()
                dhash = hex(int("".join("1" if b else "0" for b in bits), 2))

                small = np.asarray(img.resize((16, 16), Image.Resampling.BOX), dtype=np.float32)
                detail = float(np.asarray(gray.resize((32, 32), Image.Resampling.BOX), dtype=np.float32).std())
                return dhash, width / height, small, detail
        except Exception:
            # Si PIL falla (ej: archivo corrupto o RAW no soportado), lo ignoramos
            return None

    def _file_hash(self, path):
        if path not in self._file_hashes:
            digest = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(chunk)
            self._file_hashes[path] = digest.hexdigest()
        return self._file_hashes[path]

    def _is_same_photo(self, a, b):
        path_a, (_, aspect_a, small_a, detail_a) = a
        path_b, (_, aspect_b, small_b, detail_b) = b
        if abs(aspect_a - aspect_b) > self.ASPECT_TOLERANCE * max(aspect_a, aspect_b):
            return False  # Otra proporción: recorte, no copia
        if detail_a < self.MIN_DETAIL or detail_b < self.MIN_DETAIL:
            # Sin detalle la comparación visual no distingue nada: exigir archivo idéntico
            try:
                return self._file_hash(path_a) == self._file_hash(path_b)
            except OSError:
                return False
        return float(np.abs(small_a - small_b).mean()) <= self.MAX_COLOR_DIFF

    def _confirm_groups(self, candidates):
        """Divide un grupo de candidatas en grupos de duplicados confirmados."""
        groups = []
        for entry in candidates:
            for group in groups:
                if self._is_same_photo(group[0], entry):
                    group.append(entry)
                    break
            else:
                groups.append([entry])
        return [[path for path, _ in group] for group in groups if len(group) > 1]

    @Slot()
    def run(self):
        # Conexión DB local para el hilo
        local_db = VisageVaultDB.for_worker(self.db_path)

        try:
            self.progress.emit("Cargando lista de fotos...")
            cursor = local_db.conn.execute("SELECT filepath FROM photos WHERE is_hidden = 0")
            all_photos = [row['filepath'] for row in cursor.fetchall()]

            total = len(all_photos)
            self.progress.emit(f"Analizando {total} fotos visualmente...")

            candidates = {}
            processed = 0

            for path in all_photos:
                if not self.is_running: break
                if not os.path.exists(path): continue

                fingerprint = self._fingerprint(path)
                if fingerprint:
                    candidates.setdefault(fingerprint[0], []).append((path, fingerprint))

                processed += 1
                if processed % 20 == 0:
                    self.progress.emit(f"Analizando... ({processed}/{total})")

            # Confirmar cada grupo de candidatas (misma huella)
            duplicates = {}
            for dhash, entries in candidates.items():
                if len(entries) < 2 or not self.is_running:
                    continue
                for n, group in enumerate(self._confirm_groups(entries)):
                    duplicates[f"{dhash}-{n}"] = group

            self.finished.emit(duplicates)

        except Exception as e:
            print(f"Error en búsqueda duplicados: {e}")
            self.finished.emit({})
        finally:
            local_db.conn.close()


class DuplicateDialog(QDialog):
    """Diálogo para ver y gestionar los duplicados encontrados."""
    def __init__(self, duplicates_dict, db_manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestor de Fotos Duplicadas")
        self.resize(1000, 700)
        self.duplicates = duplicates_dict
        self.db = db_manager
        self.deleted_paths = set() # Registro de lo borrado

        self._setup_ui()
        self._load_list()

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)

        # IZQUIERDA: Lista de conflictos
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(QLabel("Grupos de Duplicados:"))
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_group_selected)
        left_layout.addWidget(self.list_widget)
        main_layout.addWidget(left_panel, 1)

        # DERECHA: Vista previa
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        info = QLabel("Comparativa (Borra la de menor calidad):")
        info.setStyleSheet("font-weight: bold; font-size: 14px; color: #3daee9;")
        right_layout.addWidget(info)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.preview_container = QWidget()
        self.preview_layout = QHBoxLayout(self.preview_container)
        self.preview_layout.setAlignment(Qt.AlignLeft)
        self.scroll_area.setWidget(self.preview_container)
        right_layout.addWidget(self.scroll_area)

        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(self.accept)
        right_layout.addWidget(btn_close, 0, Qt.AlignRight)

        main_layout.addWidget(right_panel, 3)

    def _load_list(self):
        self.list_widget.clear()
        for h, group_paths in self.duplicates.items():
            # Filtrar si ya borramos alguna
            valid_paths = [p for p in group_paths if p not in self.deleted_paths and os.path.exists(p)]
            if len(valid_paths) > 1:
                name = Path(valid_paths[0]).name
                item = QListWidgetItem(f"{name} ({len(valid_paths)} copias)")
                item.setData(Qt.UserRole, valid_paths)
                self.list_widget.addItem(item)

    def _on_group_selected(self, row):
        if row < 0: return
        # Limpiar vista previa anterior
        while self.preview_layout.count() > 0:
            item = self.preview_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        item = self.list_widget.item(row)
        paths = item.data(Qt.UserRole)
        valid_paths = [p for p in paths if p not in self.deleted_paths and os.path.exists(p)]

        if len(valid_paths) < 2:
            self.list_widget.takeItem(row) # Ya no es duplicado
            return

        for path in valid_paths:
            self._add_preview_card(path)

    def _add_preview_card(self, path):
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card.setStyleSheet("background-color: #2b2b2b; border-radius: 8px; margin: 5px;")
        layout = QVBoxLayout(card)

        # Imagen
        lbl = ZoomableClickableLabel(path)
        lbl.setFixedSize(280, 280)
        lbl.is_thumbnail_view = True # Desactivamos el zoom complejo para esta vista

        # Datos técnicos
        w, h, size_mb = 0, 0, 0
        try:
            size_mb = os.path.getsize(path) / (1024*1024)
            pix = QPixmap(path)

            if not pix.isNull():
                lbl.setOriginalPixmap(pix) # Guardamos referencia interna

                # --- CORRECCIÓN IMPORTANTE ---
                # Asignamos explícitamente el pixmap escalado para que se vea
                lbl.setPixmap(pix.scaled(lbl.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                # -----------------------------

                w, h = pix.width(), pix.height()
            else:
                lbl.setText("Sin vista previa")
        except:
            pass

        layout.addWidget(lbl)

        # Info (Resolución, Peso, Nombre)
        info_layout = QVBoxLayout()
        res_lbl = QLabel(f"📏 {w} x {h} px")
        res_lbl.setStyleSheet("color: #4dbef9; font-weight: bold;")
        res_lbl.setAlignment(Qt.AlignCenter)
        info_layout.addWidget(res_lbl)

        size_lbl = QLabel(f"💾 {size_mb:.2f} MB")
        size_lbl.setStyleSheet("color: #aaaaaa;")
        size_lbl.setAlignment(Qt.AlignCenter)
        info_layout.addWidget(size_lbl)

        name_lbl = QLabel(Path(path).name)
        name_lbl.setWordWrap(True)
        name_lbl.setAlignment(Qt.AlignCenter)
        # Limitamos el largo del nombre para que no descuadre
        name_lbl.setStyleSheet("font-size: 10px;")
        info_layout.addWidget(name_lbl)

        layout.addLayout(info_layout)

        # Botón Borrar
        btn_del = QPushButton("🗑️ A la papelera")
        btn_del.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold; padding: 5px;")
        btn_del.clicked.connect(lambda: self._delete_file(path, card))
        layout.addWidget(btn_del)

        self.preview_layout.addWidget(card)

    def _delete_file(self, path, card_widget):
        reply = QMessageBox.question(self, "Confirmar", f"¿Mover a la papelera?\n{Path(path).name}", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                # 1. Papelera (primero el disco: si falla, la BD queda intacta)
                if path not in send_files_to_trash(self, [path]):
                    return
                # 2. Quitar de la BD (y antes, su miniatura y recortes de caras)
                purge_media_caches(self.db.conn, path)
                self.db.delete_photo_permanently(path)

                self.deleted_paths.add(path)
                card_widget.deleteLater()

                # Refrescar lista automáticamente tras 200ms
                QTimer.singleShot(200, lambda: self._on_group_selected(self.list_widget.currentRow()))
            except Exception as e:
                QMessageBox.warning(self, "Error", f"No se pudo borrar: {e}")

    def get_deleted_items(self):
        return list(self.deleted_paths)

# =================================================================
# WORKER PARA MOVER A CAJA FUERTE (Evita congelamientos con vídeos)
# =================================================================
class MoveToSafeWorker(QObject):
    progress = Signal(str)
    item_finished = Signal(str, bool) # Envía (path, is_video) cuando termina uno
    finished = Signal()

    def __init__(self, db_path, items_data, key):
        """
        items_data: Lista de tuplas [(path, is_video), ...]
        """
        super().__init__()
        self.db_path = db_path
        self.items_data = items_data
        self.key = key
        self.is_running = True

    @Slot()
    def run(self):
        # Conexión DB independiente para este hilo
        local_db = VisageVaultDB.for_worker(self.db_path)

        safe_dir = Path(paths.safe_dir())

        total = len(self.items_data)

        for i, (original_path, is_video) in enumerate(self.items_data):
            if not self.is_running: break

            if not os.path.exists(original_path): continue

            try:
                filename = Path(original_path).name
                self.progress.emit(f"Encriptando ({i+1}/{total}): {filename}...")

                # 1. Calcular rutas
                safe_filename = hashlib.md5(original_path.encode()).hexdigest() + ".enc"
                encrypted_path = safe_dir / safe_filename

                # 2. Generar THUMBNAIL ENCRIPTADO (Solo Vídeos)
                if is_video:
                    # Generar miniatura temporal
                    thumb_temp_path = generate_video_thumbnail(original_path)

                    if thumb_temp_path and os.path.exists(thumb_temp_path):
                        encrypted_thumb_path = str(encrypted_path) + ".thumb"
                        # Encriptar miniatura
                        CryptoManager.encrypt_file(thumb_temp_path, encrypted_thumb_path, self.key)
                        # Borrar temporal
                        os.remove(thumb_temp_path)

                # 3. ENCRIPTAR ARCHIVO PRINCIPAL (Esto es lo que tardaba)
                CryptoManager.encrypt_file(original_path, encrypted_path, self.key)

                # 4. GUARDAR EN DB
                year, month = "0000", "00"
                if is_video:
                    # Usamos el método de la instancia local
                    cur = local_db.conn.execute("SELECT year, month FROM videos WHERE filepath = ?", (original_path,))
                    row = cur.fetchone()
                    if row: year, month = row['year'], row['month']
                else:
                    cur = local_db.conn.execute("SELECT year, month FROM photos WHERE filepath = ?", (original_path,))
                    row = cur.fetchone()
                    if row: year, month = row['year'], row['month']

                date_str = f"{year}-{month}"
                media_type = 'video' if is_video else 'photo'

                # Insertar en tabla safe_files
                local_db.conn.execute("""
                    INSERT INTO safe_files (original_path, encrypted_path, media_type, original_date)
                    VALUES (?, ?, ?, ?)
                """, (str(original_path), str(encrypted_path), media_type, date_str))
                local_db.conn.commit()

                # 5. LIMPIEZA (Borrar original y referencias)
                # Sin rastros en claro fuera de la caja fuerte: miniatura y recortes de caras
                purge_media_caches(local_db.conn, original_path)
                if is_video:
                    local_db.conn.execute("DELETE FROM videos WHERE filepath = ?", (original_path,))
                else:
                    # Borrar foto y caras asociadas
                    cur = local_db.conn.execute("SELECT id FROM photos WHERE filepath = ?", (original_path,))
                    row = cur.fetchone()
                    if row:
                        local_db.conn.execute("DELETE FROM faces WHERE photo_id = ?", (row['id'],))
                    local_db.conn.execute("DELETE FROM photos WHERE filepath = ?", (original_path,))

                local_db.conn.commit()

                # ... ni la ruta y la fecha en la MetaDB
                self._remove_meta_entry(original_path)

                # Borrar archivo original del disco
                os.remove(original_path)

                # Avisar al hilo principal para que actualice la UI
                self.item_finished.emit(original_path, is_video)

            except Exception as e:
                print(f"Error en worker safe con {original_path}: {e}")

        local_db.conn.close()
        self.finished.emit()

    def _remove_meta_entry(self, original_path):
        """Quita de la MetaDB la ruta y la fecha del archivo (quedarían en claro)."""
        try:
            meta_conn = sqlite3.connect(db_manager.meta_db_path_for(self.db_path))
            try:
                with meta_conn:
                    meta_conn.execute("DELETE FROM file_metadata WHERE filepath = ?", (original_path,))
            finally:
                meta_conn.close()
        except sqlite3.Error as e:
            print(f"No se pudo limpiar la MetaDB para {original_path}: {e}")

# =================================================================
# VENTANA PRINCIPAL DE LA APLICACIÓN (VisageVaultApp)
# =================================================================
class VisageVaultApp(QMainWindow):
    # Señales para controlar la velocidad del descargador de fotos
    set_drive_priority_low = Signal(bool)  # True = Modo Lento, False = Normal

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        icon_path = resource_path("visagevault.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            print(f"Advertencia: No se pudo encontrar el icono en {icon_path}")

        # --- RUTAS DE DATOS Y CACHÉ (ver paths.py) ---
        self.data_dir = paths.data_dir()
        self.cache_dir = paths.cache_dir()
        self.root_cache = self.cache_dir

        # Subcarpetas de caché
        for subdir in ("face_cache", "drive_cache", "drive_snapshot_cache"):
            paths.cache_subdir(subdir)

        self.db = VisageVaultDB(paths.db_path())
        self.db.relocate_safe_files(paths.safe_dir())
        # Restos de borrados anteriores (caras, recortes y miniaturas sin uso)
        threading.Thread(target=cleanup_orphan_caches, args=(self.db.db_path,), daemon=True).start()

        self.refresh_timer = QTimer()
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(2000) # Esperar 2 segundos de inactividad antes de refrescar
        self.refresh_timer.timeout.connect(self._perform_auto_refresh)

        self.file_watcher = None

        self.setMinimumSize(QSize(900, 600))
        self.current_directory = None

        # --- Configuración de Zoom de Miniaturas ---
        self.current_thumbnail_size = config_manager.get_thumbnail_size()
        self.MIN_THUMB_SIZE = 64   # Tamaño mínimo (ej: 64px)
        self.MAX_THUMB_SIZE = 256  # Tamaño máximo (ej: 256px)
        self.THUMB_SIZE_STEP = 16  # Píxeles por paso de zoom

        # --- Variables de Fotos ---
        self.photos_by_year_month = {}
        self.photo_thread = None
        self.photo_worker = None
        # REFACTOR: Diccionario para mapear path -> QListWidgetItem
        self.photo_list_widget_items = {}


        # --- Variables de Vídeos ---
        self.videos_by_year_month = {}
        self.video_thread = None
        self.video_worker = None
        # REFACTOR: Diccionario para mapear path -> QListWidgetItem
        self.video_list_widget_items = {}


        # --- Variables de Caras ---
        self.face_scan_thread = None
        self.face_scan_worker = None
        self.face_loading_label = None
        self.current_face_count = 0

        # --- Variables de Nube ---
        self.drive_photos_by_date = {}
        self.cloud_group_widgets = {}
        self.cloud_list_widget_items = {}  # file_id -> QListWidgetItem (búsqueda directa)
        self.cloud_photo_count = 0
        self.current_drive_folder_id = None
        self.drive_scan_thread = None
        self.drive_scan_worker = None
        self.drive_login_thread = None
        self.drive_login_worker = None
        # Hilos sustituidos por otros que aún pueden estar terminando (ver _retire_thread)
        self._retired_threads = []
        self.drive_loaded_ids = set()
        self.is_drive_connected = False
        # Árbol de carpetas de Drive: elementos por id de carpeta. La generación
        # cambia al vaciar el árbol, para ignorar respuestas de un árbol anterior.
        self._drive_tree_gen = 0
        self._drive_tree_items = {}
        self._drive_folders_in_flight = set()
        self.drive_folder_signals = DriveFolderSignals()
        self.drive_folder_signals.loaded.connect(self._on_drive_folders_loaded)
        self.drive_folder_pool = QThreadPool()
        self.drive_folder_pool.setMaxThreadCount(2)
        self.current_drive_folder_name = "Inicio"

        # Archivos desaparecidos que el usuario decidió conservar en esta sesión
        self.kept_missing_paths = set()

        # --- Variables para filtrado local ---
        self.current_photo_filter_path = None
        self.current_video_filter_path = None

        # --- Hilos y Señales ---
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(os.cpu_count() or 4)
        # Pool aparte para la agrupación de caras: el de miniaturas se vacía
        # con clear() al cambiar de pestaña y la cancelaría
        self.cluster_pool = QThreadPool()
        self.cluster_pool.setMaxThreadCount(1)
        # Pool aparte para descifrar la caja fuerte (no se vacía al cambiar de pestaña)
        self.safe_pool = QThreadPool()
        self.safe_pool.setMaxThreadCount(max(1, min(4, os.cpu_count() or 2)))
        self.safe_thumb_signals = SafeThumbnailSignals()
        self.safe_thumb_signals.loaded.connect(self._on_safe_thumbnail_loaded)
        self.safe_thumb_signals.failed.connect(self._on_safe_thumbnail_failed)
        self.drive_download_signals = DriveDownloadSignals()
        self.drive_download_signals.finished.connect(self._finish_cloud_preview)
        self.drive_download_signals.failed.connect(self._set_status)
        self.update_signals = UpdateCheckSignals()
        self.update_signals.finished.connect(self._on_update_check_finished)
        self.safe_generation = 0     # Descarta resultados de cargas anteriores o tras bloquear
        self.safe_list_items = {}    # ruta cifrada -> (QListWidgetItem, tipo)

        # Usamos la MISMA señal para todas las miniaturas (fotos, vídeos, caras)
        self.thumb_signals = ThumbnailLoaderSignals()
        self.thumb_signals.thumbnail_loaded.connect(self._update_thumbnail)
        self.thumb_signals.load_failed.connect(self._handle_thumbnail_failed)
        self.thumb_signals.drive_link_refreshed.connect(self._on_drive_link_refreshed)

        self.face_loader_signals = FaceLoaderSignals()
        self.face_loader_signals.face_loaded.connect(self._handle_face_loaded)
        self.face_loader_signals.face_load_failed.connect(self._handle_face_load_failed)

        self.cluster_queue = []
        self.cluster_signals = ClusterSignals()
        self.cluster_signals.clusters_found.connect(self._handle_clusters_found)
        self.cluster_signals.clustering_progress.connect(self._set_status)
        self.cluster_signals.clustering_finished.connect(self._handle_clustering_finished)

        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(200)
        self.resize_timer.timeout.connect(self._handle_resize_timeout)

        self._setup_ui()

        # --- PRECARGA INTELIGENTE ---
        # 1. Configuración inicial
        # Diálogos de arranque: se aplazan mientras se ve el splash (si no, quedan tapados)
        self._splash_open = False
        self._after_splash_callbacks = []

        QTimer.singleShot(100, self._initial_check)
        QTimer.singleShot(500, self._check_auto_login)
        # Después del splash y de los diálogos de arranque, para que no se crucen
        QTimer.singleShot(0, lambda: self._after_splash(lambda: QTimer.singleShot(2000, self.check_updates_auto)))

        # 2. 🔥 ELIMINAR RETARDO DE PESTAÑAS: Cargar datos pesados al arrancar
        # Lo lanzamos a los 800ms para no frenar la apertura de la ventana
        QTimer.singleShot(800, self._preload_heavy_tabs)

    def _preload_heavy_tabs(self):
        """Carga los datos de Personas y Nube en segundo plano al iniciar."""
        # 1. Cargar lista de nombres de personas (DB Query + TreeWidget)
        self._load_people_list()

        # 2. Cargar rejilla de caras (DB Query + Widgets)
        self._load_existing_faces_async()

        # (La Nube ya se precarga sola con _check_auto_login -> _scan_drive_content)
        self._set_status("Aplicación lista y precargada.")

    def _setup_ui(self):
        # 1. Crear el QTabWidget
        self.tab_widget = QTabWidget()

        # ==========================================================
        # 2. Pestaña "Fotos"
        # ==========================================================
        fotos_tab_widget = QWidget()
        fotos_layout = QVBoxLayout(fotos_tab_widget)
        fotos_layout.setContentsMargins(0, 0, 0, 0)

        self.main_splitter = QSplitter(Qt.Horizontal)

        # --- Panel Izquierdo (Árbol de Carpetas Local) ---
        self.photo_folder_panel = QWidget()
        self.photo_folder_panel.setMinimumWidth(200)
        photo_folder_layout = QVBoxLayout(self.photo_folder_panel)
        photo_folder_layout.setContentsMargins(0, 0, 0, 0)

        lbl_folder_photo = QLabel("Directorios:")
        lbl_folder_photo.setStyleSheet("font-weight: bold; color: #3daee9; padding: 5px;")
        photo_folder_layout.addWidget(lbl_folder_photo)

        self.photo_folder_tree = QTreeWidget()
        self.photo_folder_tree.setHeaderHidden(True)
        self.photo_folder_tree.itemExpanded.connect(self._on_local_folder_tree_expanded)
        self.photo_folder_tree.itemClicked.connect(self._on_photo_folder_tree_clicked)
        photo_folder_layout.addWidget(self.photo_folder_tree)

        self.main_splitter.addWidget(self.photo_folder_panel)
        self.photo_folder_panel.hide() # Oculto por defecto
        # ------------------------------------------------------

        # Panel Central (Fotos) - ANTES ERA IZQUIERDO
        photo_area_widget = QWidget()
        self.photo_container_layout = QVBoxLayout(photo_area_widget)
        self.photo_container_layout.setSpacing(0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(photo_area_widget)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._debounced_thumbnail_load)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_photo_scroll_changed)
        self.main_splitter.addWidget(self.scroll_area)

        # Panel Derecho (Navegación de Fotos)
        photo_right_panel_widget = QWidget()
        photo_right_panel_layout = QVBoxLayout(photo_right_panel_widget)

        # Controles superiores
        top_controls = QVBoxLayout()
        botones_layout = QHBoxLayout()

        self.select_dir_button = QPushButton("Cambiar Directorio")
        self.select_dir_button.clicked.connect(self._open_directory_dialog)
        botones_layout.addWidget(self.select_dir_button)

        self.btn_duplicates = QPushButton("Buscar Duplicados")
        self.btn_duplicates.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.btn_duplicates.clicked.connect(self._start_duplicate_search)
        botones_layout.addWidget(self.btn_duplicates)

        top_controls.addLayout(botones_layout)

        # --- Botón Ver Árbol ---
        self.btn_show_photo_tree = QPushButton("Ver árbol de directorios")
        self.btn_show_photo_tree.setCheckable(True)
        self.btn_show_photo_tree.clicked.connect(self._toggle_photo_folder_tree)
        top_controls.addWidget(self.btn_show_photo_tree)
        # ------------------------------

        self.path_label = QLabel("Ruta: No configurada")
        self.path_label.setWordWrap(True)
        top_controls.addWidget(self.path_label)
        photo_right_panel_layout.addLayout(top_controls)

        photo_year_label = QLabel("Navegación por Fecha (Fotos):")
        photo_right_panel_layout.addWidget(photo_year_label)
        self.date_tree_widget = QTreeWidget()
        self.date_tree_widget.setHeaderHidden(True)
        self.date_tree_widget.currentItemChanged.connect(self._scroll_to_item)
        photo_right_panel_layout.addWidget(self.date_tree_widget)

        self.main_splitter.addWidget(photo_right_panel_widget)
        fotos_layout.addWidget(self.main_splitter)

        # Ajustar tamaños iniciales (Árbol oculto (0), Fotos, Panel Derecho)
        self.main_splitter.setSizes([0, 800, 200])

        # ==========================================================
        # 3. Pestaña "Vídeos"
        # ==========================================================
        videos_tab_widget = QWidget()
        videos_layout = QVBoxLayout(videos_tab_widget)
        videos_layout.setContentsMargins(0, 0, 0, 0)

        self.video_splitter = QSplitter(Qt.Horizontal)

        # --- Panel Izquierdo (Árbol de Carpetas Local Vídeos) ---
        self.video_folder_panel = QWidget()
        self.video_folder_panel.setMinimumWidth(200)
        video_folder_layout = QVBoxLayout(self.video_folder_panel)
        video_folder_layout.setContentsMargins(0, 0, 0, 0)

        lbl_folder_video = QLabel("Directorios:")
        lbl_folder_video.setStyleSheet("font-weight: bold; color: #3daee9; padding: 5px;")
        video_folder_layout.addWidget(lbl_folder_video)

        self.video_folder_tree = QTreeWidget()
        self.video_folder_tree.setHeaderHidden(True)
        self.video_folder_tree.itemExpanded.connect(self._on_local_folder_tree_expanded)
        self.video_folder_tree.itemClicked.connect(self._on_video_folder_tree_clicked)
        video_folder_layout.addWidget(self.video_folder_tree)

        self.video_splitter.addWidget(self.video_folder_panel)
        self.video_folder_panel.hide()
        # -------------------------------------------------------------

        # Panel Central (Vídeos)
        video_area_widget = QWidget()
        self.video_container_layout = QVBoxLayout(video_area_widget)
        self.video_container_layout.setSpacing(0)
        self.video_scroll_area = QScrollArea()
        self.video_scroll_area.setWidgetResizable(True)
        self.video_scroll_area.setWidget(video_area_widget)
        self.video_scroll_area.verticalScrollBar().valueChanged.connect(self._load_visible_video_thumbnails)
        self.video_scroll_area.verticalScrollBar().valueChanged.connect(self._on_video_scroll_changed)
        self.video_splitter.addWidget(self.video_scroll_area)

        # Panel Derecho (Navegación de Vídeos)
        video_right_panel_widget = QWidget()
        video_right_panel_layout = QVBoxLayout(video_right_panel_widget)

        # --- Botonera superior para Vídeos ---
        video_top_controls = QVBoxLayout()
        self.btn_show_video_tree = QPushButton("Ver árbol de directorios")
        self.btn_show_video_tree.setCheckable(True)
        self.btn_show_video_tree.clicked.connect(self._toggle_video_folder_tree)
        video_top_controls.addWidget(self.btn_show_video_tree)
        video_right_panel_layout.addLayout(video_top_controls)
        # --------------------------------------------

        video_year_label = QLabel("Navegación por Fecha (Vídeos):")
        video_right_panel_layout.addWidget(video_year_label)
        self.video_date_tree_widget = QTreeWidget()
        self.video_date_tree_widget.setHeaderHidden(True)
        self.video_date_tree_widget.currentItemChanged.connect(self._scroll_to_video_item)
        video_right_panel_layout.addWidget(self.video_date_tree_widget)

        video_right_panel_layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        self.video_splitter.addWidget(video_right_panel_widget)
        videos_layout.addWidget(self.video_splitter)

        # Ajustar tamaños iniciales
        self.video_splitter.setSizes([0, 800, 200])


        # ==========================================================
        # 4. Pestaña "Personas"
        # ==========================================================
        self.personas_tab_widget = QWidget()
        personas_layout = QVBoxLayout(self.personas_tab_widget)
        personas_layout.setContentsMargins(0, 0, 0, 0)
        self.people_splitter = QSplitter(Qt.Horizontal)
        self.left_people_stack = QStackedWidget()

        # Pagina 0: Cuadrícula de Caras
        face_area_widget = QWidget()
        self.face_container_layout = QVBoxLayout(face_area_widget)
        self.unknown_faces_group = QGroupBox("Caras Sin Asignar")
        self.unknown_faces_layout = QGridLayout(self.unknown_faces_group)
        self.unknown_faces_layout.setSpacing(10)
        self.face_container_layout.addWidget(self.unknown_faces_group)
        self.face_container_layout.addStretch(1)
        self.face_scroll_area = QScrollArea()
        self.face_scroll_area.setWidgetResizable(True)
        self.face_scroll_area.setWidget(face_area_widget)
        self.left_people_stack.addWidget(self.face_scroll_area)

        # Pagina 1: Cuadrícula de Fotos de Persona
        self.person_photo_scroll_area = QScrollArea()
        self.person_photo_scroll_area.setWidgetResizable(True)
        person_photo_widget = QWidget()
        self.person_photo_layout = QVBoxLayout(person_photo_widget)
        self.person_photo_scroll_area.setWidget(person_photo_widget)
        self.person_photo_scroll_area.verticalScrollBar().valueChanged.connect(self._load_person_visible_thumbnails)
        self.left_people_stack.addWidget(self.person_photo_scroll_area)
        self.people_splitter.addWidget(self.left_people_stack)

        # Panel Derecho (Personas)
        people_panel_widget = QWidget()
        people_panel_layout = QVBoxLayout(people_panel_widget)
        people_panel_widget.setMinimumWidth(180)
        people_panel_widget.setMaximumWidth(450)
        people_label = QLabel("Navegación por Personas:")
        people_panel_layout.addWidget(people_label)
        self.people_tree_widget = QTreeWidget()
        self.people_tree_widget.setHeaderHidden(True)
        self.people_tree_widget.currentItemChanged.connect(self._on_person_selected)
        people_panel_layout.addWidget(self.people_tree_widget)
        self.show_deleted_faces_button = QPushButton("Ver caras eliminadas")
        self.show_deleted_faces_button.clicked.connect(self._show_deleted_faces)
        people_panel_layout.addWidget(self.show_deleted_faces_button)
        self.cluster_faces_button = QPushButton("Agrupar caras parecidas")
        self.cluster_faces_button.clicked.connect(self._start_clustering)
        people_panel_layout.addWidget(self.cluster_faces_button)
        self.people_splitter.addWidget(people_panel_widget)
        personas_layout.addWidget(self.people_splitter)
        default_width = self.width()
        min_right_width = 180
        left_width = default_width - min_right_width
        if left_width < 100: left_width = 100
        self.people_splitter.setSizes([left_width, min_right_width])

        # ==========================================================
        # 5. Pestaña "Ayuda"
        # ==========================================================
        help_tab_widget = self._build_help_tab()

        # ==========================================================
        # PESTAÑA NUBE (Google Drive) - MODIFICADA
        # ==========================================================
        self.cloud_tab = QWidget()
        cloud_layout = QVBoxLayout(self.cloud_tab)

        # 1. Cabecera (Botón Login, Cambiar Carpeta y Ver Árbol)
        header_layout = QHBoxLayout()
        self.btn_gdrive = QPushButton("Iniciar sesión con Google")
        self.btn_gdrive.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon))
        self.btn_gdrive.clicked.connect(self._on_gdrive_login_click)
        header_layout.addWidget(self.btn_gdrive)

        self.btn_change_folder = QPushButton("Cambiar Carpeta")
        self.btn_change_folder.setVisible(False)
        self.btn_change_folder.clicked.connect(self._select_drive_folder)
        header_layout.addWidget(self.btn_change_folder)

        # --- NUEVO BOTÓN: VER ÁRBOL ---
        self.btn_show_tree = QPushButton("Ver árbol de directorios")
        self.btn_show_tree.setCheckable(True) # Funciona como interruptor On/Off
        self.btn_show_tree.setVisible(False)  # Oculto hasta iniciar sesión
        self.btn_show_tree.clicked.connect(self._toggle_drive_folder_tree)
        header_layout.addWidget(self.btn_show_tree)
        # ------------------------------

        header_layout.addStretch() # Empujar botones a la izquierda
        cloud_layout.addLayout(header_layout)

        # 2. Splitter Principal (Árbol Carpetas | Fotos | Árbol Fechas)
        self.cloud_splitter = QSplitter(Qt.Horizontal)

        # --- PANEL IZQUIERDO: ÁRBOL DE DIRECTORIOS ---
        self.cloud_folder_panel = QWidget()
        folder_panel_layout = QVBoxLayout(self.cloud_folder_panel)
        folder_panel_layout.setContentsMargins(0, 0, 0, 0)

        folder_label = QLabel("Subcarpetas:")
        folder_label.setStyleSheet("font-weight: bold; color: #3daee9; padding: 5px;")
        folder_panel_layout.addWidget(folder_label)

        self.cloud_folder_tree = QTreeWidget()
        self.cloud_folder_tree.setHeaderHidden(True)
        # Conectamos la expansión para carga perezosa (lazy loading)
        self.cloud_folder_tree.itemExpanded.connect(self._on_folder_tree_item_expanded)

        self.cloud_folder_tree.itemClicked.connect(self._on_folder_tree_item_clicked)

        folder_panel_layout.addWidget(self.cloud_folder_tree)

        # Lo añadimos al splitter y lo ocultamos por defecto (se activa con el botón)
        self.cloud_splitter.addWidget(self.cloud_folder_panel)
        self.cloud_folder_panel.hide()
        # ---------------------------------------------------

        # --- PANEL CENTRAL: Área de Scroll para las Fotos ---
        cloud_area_widget = QWidget()
        self.cloud_container_layout = QVBoxLayout(cloud_area_widget)
        self.cloud_container_layout.setSpacing(0)

        self.cloud_scroll_area = QScrollArea()
        self.cloud_scroll_area.setWidgetResizable(True)
        self.cloud_scroll_area.setWidget(cloud_area_widget)

        # Conectamos el scroll para cargar miniaturas bajo demanda (Lazy Loading)
        self.cloud_scroll_area.verticalScrollBar().valueChanged.connect(self._load_visible_cloud_thumbnails)
        self.cloud_scroll_area.verticalScrollBar().valueChanged.connect(self._on_cloud_scroll_changed)

        self.cloud_splitter.addWidget(self.cloud_scroll_area)

        # --- PANEL DERECHO: Árbol de Fechas ---
        cloud_right_panel = QWidget()
        cloud_right_layout = QVBoxLayout(cloud_right_panel)

        cloud_right_layout.addWidget(QLabel("Navegación Nube:"))
        self.cloud_date_tree = QTreeWidget()
        self.cloud_date_tree.setHeaderHidden(True)
        self.cloud_date_tree.currentItemChanged.connect(self._scroll_to_cloud_item)
        cloud_right_layout.addWidget(self.cloud_date_tree)

        self.cloud_splitter.addWidget(cloud_right_panel)

        # Ajustar tamaños iniciales (20% árbol, 60% fotos, 20% fechas)
        self.cloud_splitter.setSizes([200, 600, 200])

        cloud_layout.addWidget(self.cloud_splitter)

        # Variables de memoria para la nube
        self.drive_photos_by_date = {} # Estructura: { '2023': { '01': [datos_foto, ...] } }
        self.cloud_group_widgets = {}  # Para el scroll automático
        self.cloud_photo_count = 0

        # ==========================================================
        # 6. Añadir pestañas al Widget Central (MODIFICADO)
        # ==========================================================
        self.tab_widget.addTab(fotos_tab_widget, "Fotos")
        self.tab_widget.addTab(videos_tab_widget, "Vídeos")
        self.tab_widget.addTab(self.personas_tab_widget, "Personas")
        self.safe_tab = QWidget()
        self._setup_safe_tab() # Función auxiliar que crearemos abajo
        self.tab_widget.addTab(self.safe_tab, "Caja Fuerte")
        self.tab_widget.addTab(self.cloud_tab, "Nube")
        self.tab_widget.addTab(help_tab_widget, "Ayuda")

        self.setCentralWidget(self.tab_widget)

        # ==========================================================
        # 7. Cargar estado de los splitters
        # ==========================================================
        photo_right_panel_widget.setMinimumWidth(180)
        # self.main_splitter.splitterMoved.connect(self._save_photo_splitter_state)
        self._load_photo_splitter_state()

        video_right_panel_widget.setMinimumWidth(180)
        # self.video_splitter.splitterMoved.connect(self._save_video_splitter_state)
        self._load_video_splitter_state()

        self.tab_widget.currentChanged.connect(self._on_tab_changed)

    # ----------------------------------------------------
    # Lógica de Inicio y Configuración
    # ----------------------------------------------------

    # ==========================================================
    # ACTUALIZACIONES
    # ==========================================================

    def check_updates_auto(self):
        """Busca una versión nueva al arrancar, en segundo plano. Los errores (sin red,
        límite de la API de GitHub...) solo se registran en consola."""
        if APP_VERSION == "dev":
            print("Compilación de desarrollo: no se buscan actualizaciones")
            return
        if not config_manager.get_check_updates():
            return
        self._start_update_check(automatic=True)

    def check_updates_manual(self, button, parent):
        """Botón de la Ayuda: avisa aunque esa versión se hubiera omitido."""
        if APP_VERSION == "dev":
            QMessageBox.information(parent, "Actualizaciones",
                                    "Esta es una compilación de desarrollo:\nno se buscan actualizaciones.")
            return
        button.setEnabled(False)
        button.setText("🔄 Buscando...")
        self._start_update_check(automatic=False, button=button, parent=parent)

    def _start_update_check(self, automatic, button=None, parent=None):
        signals = self.update_signals

        def worker():
            try:
                rel, error = updater.check_latest(APP_VERSION), None
            except Exception as e:
                rel, error = None, e
            try:
                signals.finished.emit(rel, error, automatic, button, parent)
            except RuntimeError:
                pass  # App cerrada mientras se consultaba
        threading.Thread(target=worker, daemon=True).start()

    @Slot(object, object, bool, object, object)
    def _on_update_check_finished(self, rel, error, automatic, button, parent):
        if automatic:
            if error:
                print(f"No se pudo comprobar si hay actualizaciones: {error}")
            elif rel and rel["tag"] != config_manager.get_skipped_version():
                print(f"Nueva versión disponible: {rel['tag']}")
                UpdateDialog(rel, True, self).exec()
            return

        # Búsqueda manual desde la Ayuda
        try:
            button.setEnabled(True)
            button.setText("🔄 Buscar actualizaciones")
            if not parent.isVisible():
                return  # Se cerró la ventana mientras se buscaba
        except RuntimeError:
            return
        if error:
            QMessageBox.warning(parent, "Actualizaciones", f"No se pudo comprobar si hay actualizaciones:\n{error}")
        elif rel is None:
            QMessageBox.information(parent, "Actualizaciones", f"Ya tienes la última versión ({APP_VERSION}).")
        else:
            UpdateDialog(rel, False, parent).exec()

    def _after_splash(self, callback):
        """Ejecuta callback cuando se haya cerrado el splash (o ya, si no hay)."""
        if self._splash_open:
            self._after_splash_callbacks.append(callback)
        else:
            callback()

    def on_splash_closed(self):
        self._splash_open = False
        callbacks, self._after_splash_callbacks = self._after_splash_callbacks, []
        for callback in callbacks:
            callback()

    def _initial_check(self):
        """Comprueba la configuración al arrancar la app."""

        # --- COMPROBACIÓN DE AUTOREPARACIÓN ---
        if self.db.was_reset:
            self._after_splash(lambda: QMessageBox.warning(
                self,
                "Autoreparación Realizada",
                "Se detectó un problema en la base de datos y ha sido reiniciada.\n\n"
                "✅ TUS DATOS ESTÁN A SALVO: Hemos restaurado tus fechas personalizadas y archivos ocultos.\n"
                "ℹ️ El escáner de caras y miniaturas se ejecutará de nuevo para reconstruir el caché."
            ))
        # --------------------------------------------

        directory = config_manager.get_photo_directory()
        if directory and Path(directory).is_dir():
            self.current_directory = directory
            self.path_label.setText(f"Ruta: {Path(directory).name}")
            self._start_media_scan(directory)
        else:
            self._set_status("No se encontró un directorio válido. Por favor, selecciona uno.")
            self._after_splash(lambda: self._open_directory_dialog(force_select=True))

    def _open_directory_dialog(self, force_select=False):
        """Abre el selector de directorios y gestiona la carga."""

        # 1. Definir la variable 'directory' abriendo el diálogo
        directory = QFileDialog.getExistingDirectory(
            self,
            "Seleccionar Carpeta de Fotos",
            self.current_directory or ""
        )

        if directory:
            self.current_directory = directory
            config_manager.set_photo_directory(directory)
            self.path_label.setText(f"Ruta: {Path(directory).name}")

            # Resetear filtros
            self.current_photo_filter_path = None
            self.current_video_filter_path = None

            # Recargar árboles si están visibles
            if self.btn_show_photo_tree.isChecked():
                self._load_local_tree_root(self.photo_folder_tree, directory)
            else:
                self.photo_folder_tree.clear()

            if self.btn_show_video_tree.isChecked():
                self._load_local_tree_root(self.video_folder_tree, directory)
            else:
                self.video_folder_tree.clear()

            # Limpiar y escanear
            self.date_tree_widget.clear()
            self.video_date_tree_widget.clear()
            self._start_media_scan(directory)

        elif force_select:
             self._set_status("¡Debes seleccionar un directorio para comenzar!")

    # ----------------------------------------------------
    # Lógica de Hilos y Resultados
    # ----------------------------------------------------

    def _start_media_scan(self, directory):
        """Inicia los escaneos de fotos y vídeos."""
        if not directory:
            return

        if self.file_watcher:
            self.file_watcher.stop()

        self.file_watcher = PhotoDirWatcher(directory)
        self.file_watcher.directory_changed.connect(self._on_directory_changed)
        self.file_watcher.start()

        scan_id = self._next_scan_id()
        self._start_photo_search(directory, scan_id)
        self._start_video_search(directory, scan_id)

    @Slot()
    def _on_directory_changed(self):
        """Se llama cuando watchdog detecta un cambio. Reinicia el temporizador."""
        # Cada vez que hay un cambio, reiniciamos la cuenta atrás.
        # Solo se ejecutará _perform_auto_refresh cuando pasen 2 segundos SIN cambios.
        self.refresh_timer.start()

    @Slot()
    def _perform_auto_refresh(self):
        """Ejecuta el re-escaneo real tras el periodo de calma."""
        # print("Detectados cambios en el disco. Actualizando galería...")
        self._set_status("Detectados cambios externos. Actualizando...")

        if self.current_directory:
            # Relanzamos los escaneos.
            # Nota: Tus workers actuales son inteligentes (usan fechas de la BD),
            # pero para detectar archivos NUEVOS o BORRADOS necesitan recorrer el disco.
            scan_id = self._next_scan_id()
            self._start_photo_search(self.current_directory, scan_id)
            self._start_video_search(self.current_directory, scan_id)
            # El escaneo de caras se lanzará solo al terminar el de fotos

    def _next_scan_id(self):
        """Identificador de una tanda de escaneo (fotos + vídeos comparten recorrido)."""
        self._scan_counter = getattr(self, "_scan_counter", 0) + 1
        return self._scan_counter

    def _start_photo_search(self, directory, scan_id=None):
        """Configura y lanza el trabajador de escaneo de FOTOS."""
        if self.photo_thread and self.photo_thread.isRunning():
            self._set_status("El escaneo de fotos anterior sigue en curso.")
            return

        self.photo_thread = QThread()
        self.photo_worker = PhotoFinderWorker(directory, self.db.db_path, scan_id)
        self.photo_worker.moveToThread(self.photo_thread)

        self.photo_thread.started.connect(self.photo_worker.run)
        self.photo_worker.finished.connect(self._handle_search_finished)
        self.photo_worker.progress.connect(self._set_status)

        self.photo_worker.finished.connect(self.photo_thread.quit)
        self.photo_worker.finished.connect(self.photo_worker.deleteLater)
        self.photo_thread.finished.connect(self._on_scan_thread_finished)

        self.select_dir_button.setEnabled(False)
        self.photo_thread.start()

    def _start_video_search(self, directory, scan_id=None):
        """Configura y lanza el trabajador de escaneo de VÍDEOS."""
        if self.video_thread and self.video_thread.isRunning():
            self._set_status("El escaneo de vídeos anterior sigue en curso.")
            return

        self.video_thread = QThread()
        self.video_worker = VideoFinderWorker(directory, self.db.db_path, scan_id)
        self.video_worker.moveToThread(self.video_thread)

        self.video_thread.started.connect(self.video_worker.run)
        self.video_worker.finished.connect(self._handle_video_search_finished)
        self.video_worker.progress.connect(self._set_status) # Ambos workers reportan al mismo status_label

        self.video_worker.finished.connect(self.video_thread.quit)
        self.video_worker.finished.connect(self.video_worker.deleteLater)
        self.video_thread.finished.connect(self._on_video_scan_thread_finished)

        self.select_dir_button.setEnabled(False) # Compartido
        self.video_thread.start()

    # ----------------------------------------------------
    # Escaneo de caras
    # ----------------------------------------------------
    def _start_face_scan(self):
        """Configura y lanza el trabajador de escaneo de caras."""
        if self.face_scan_thread and self.face_scan_thread.isRunning():
            self._set_status("El escaneo de caras ya está en curso.")
            return
        self.face_scan_thread = QThread()
        self.face_scan_worker = FaceScanWorker(self.db.db_path)
        self.face_scan_worker.moveToThread(self.face_scan_thread)
        self.face_scan_worker.signals.scan_progress.connect(self._set_status)
        self.face_scan_worker.signals.scan_percentage.connect(self._update_face_scan_percentage)
        self.face_scan_worker.signals.face_found.connect(self._handle_face_found)
        self.face_scan_worker.signals.scan_finished.connect(self._handle_scan_finished)
        self.face_scan_thread.started.connect(self.face_scan_worker.run)
        self.face_scan_worker.signals.scan_finished.connect(self.face_scan_thread.quit)
        self.face_scan_worker.signals.scan_finished.connect(self.face_scan_worker.deleteLater)
        self.face_scan_thread.finished.connect(self._on_face_scan_thread_finished)
        self._set_status("Iniciando escaneo de caras...")
        self.face_scan_thread.start()

    # ----------------------------------------------------
    # Lógica de Visualización y Miniaturas
    # ----------------------------------------------------

    def _gallery(self, is_video):
        """Piezas de la galería de Fotos o de Vídeos (comparten toda la lógica)."""
        if is_video:
            return types.SimpleNamespace(
                kind="vídeos", data=self.videos_by_year_month, items=self.video_list_widget_items,
                groups_attr="video_group_widgets", container=self.video_container_layout,
                scroll=self.video_scroll_area, tree=self._date_tree(True),
                filter_path=self.current_video_filter_path, get_hidden=self.db.get_hidden_videos,
                hidden_label="Ocultos", hidden_title="Vídeos Ocultos", hidden_kind="vídeos ocultos",
                spacing=20, padding=8,
                loader=VideoThumbnailLoader, open_item=self._open_video_player,
                splitter=self.video_splitter, splitter_key="video_splitter_sizes",
                folder_panel=self.video_folder_panel, folder_tree=self.video_folder_tree,
                tree_button=self.btn_show_video_tree)
        return types.SimpleNamespace(
            kind="fotos", data=self.photos_by_year_month, items=self.photo_list_widget_items,
            groups_attr="photo_group_widgets", container=self.photo_container_layout,
            scroll=self.scroll_area, tree=self._date_tree(False),
            filter_path=self.current_photo_filter_path, get_hidden=self.db.get_hidden_photos,
            hidden_label="Ocultas", hidden_title="Fotos Ocultas", hidden_kind="fotos ocultas",
            spacing=10, padding=10,
            loader=ThumbnailLoader, open_item=self._open_preview_dialog,
            splitter=self.main_splitter, splitter_key="photo_splitter_sizes",
            folder_panel=self.photo_folder_panel, folder_tree=self.photo_folder_tree,
            tree_button=self.btn_show_photo_tree)

    def _date_tree(self, is_video):
        return self.video_date_tree_widget if is_video else self.date_tree_widget

    def _new_gallery_list(self, is_video, hidden_view=False):
        """QListWidget de miniaturas configurado para Fotos o Vídeos."""
        g = self._gallery(is_video)
        list_widget = PreviewListWidget()
        list_widget.setMovement(QListWidget.Static)
        list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        list_widget.setViewMode(QListWidget.IconMode)
        list_widget.setResizeMode(QListWidget.Adjust)
        list_widget.setSpacing(20 if hidden_view else g.spacing)
        list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        list_widget.customContextMenuRequested.connect(
            lambda pos, lw=list_widget: self._on_context_menu(pos, lw, is_video=is_video, is_hidden_view=hidden_view)
        )
        # Doble clic: PreviewListWidget lo convierte en previewRequested (no emite itemDoubleClicked)
        list_widget.previewRequested.connect(g.open_item)
        list_widget.setIconSize(QSize(self.current_thumbnail_size, self.current_thumbnail_size))
        list_widget.setProperty("thumb_padding", 8 if hidden_view else g.padding)
        if not hidden_view:
            list_widget.itemPressed.connect(self._handle_global_selection)
            list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            list_widget.setFrameShape(QFrame.NoFrame)
            list_widget.setToolTip("Ctrl + (+/-): Zoom\n\nHaz clic para seleccionar.")
        return list_widget

    def _add_gallery_item(self, list_widget, path, items_index):
        cell = self.current_thumbnail_size + (list_widget.property("thumb_padding") or 10)
        item = QListWidgetItem("Cargando...")
        item.setToolTip(Path(path).name)
        # Tamaño de la celda fijo: la selección se ajusta a él
        item.setSizeHint(QSize(cell, cell))
        item.setData(Qt.UserRole, path)
        item.setData(Qt.UserRole + 1, "not_loaded")
        list_widget.addItem(item)
        items_index[path] = item

    def _display_photos(self):
        self._display_media(is_video=False)

    def _display_videos(self):
        self._display_media(is_video=True)

    def _display_media(self, is_video):
        """Galería de Fotos o Vídeos agrupada por año y mes, sin los ocultos."""
        g = self._gallery(is_video)
        while g.container.count() > 0:
            item = g.container.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        g.tree.clear()
        g.items.clear()
        group_widgets = {}
        setattr(self, g.groups_attr, group_widgets)

        hidden_paths = set(g.get_hidden())
        hidden_item = QTreeWidgetItem(g.tree, [g.hidden_label])
        hidden_item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning))
        hidden_item.setData(0, Qt.UserRole, "HIDDEN_SECTION")

        # Filtro por carpeta (árbol de directorios): con separador final para que
        # ".../fotos" no incluya también ".../fotos2"
        folder_prefix = os.path.join(g.filter_path, "") if g.filter_path else None

        for year in sort_years(g.data.keys()):
            year_item = QTreeWidgetItem(g.tree, [str(year)])
            year_label = QLabel(year_title(year))
            year_label.setStyleSheet("font-size: 16pt; font-weight: bold; margin-top: 20px; margin-bottom: 5px;")
            widgets_for_year = []

            for month in sort_months(g.data[year].keys()):
                visible = [p for p in g.data[year][month]
                           if p not in hidden_paths and (folder_prefix is None or p.startswith(folder_prefix))]
                if not visible:
                    continue

                try:
                    month_name = datetime.datetime.strptime(month, "%m").strftime("%B").capitalize()
                except ValueError:
                    month_name = "Mes Desconocido"

                month_item = QTreeWidgetItem(year_item, [f"{month_name} ({len(visible)})"])
                month_item.setData(0, Qt.UserRole, (year, month))

                month_label = QLabel(month_name)
                month_label.setStyleSheet("font-size: 14pt; font-weight: bold; margin-top: 10px;")
                widgets_for_year.append(month_label)
                group_widgets[f"{year}-{month}"] = month_label

                list_widget = self._new_gallery_list(is_video)
                for path in visible:
                    self._add_gallery_item(list_widget, path, g.items)
                # Altura fija para mostrar todas las filas sin "huecos" (se recalcula al redimensionar)
                list_widget.setProperty("fixed_grid", True)
                self._fit_grid_height(list_widget, g.scroll)
                widgets_for_year.append(list_widget)

            if widgets_for_year:
                g.container.addWidget(year_label)
                group_widgets[year] = year_label
                for w in widgets_for_year:
                    g.container.addWidget(w)
                year_item.setExpanded(True)
            else:
                year_item.setHidden(True)

        g.container.addStretch(1)
        QTimer.singleShot(100, lambda: self._load_visible_gallery_thumbnails(is_video))

    # ----------------------------------------------------------------
    # MENÚ CONTEXTUAL ESPECÍFICO PARA DRIVE
    # ----------------------------------------------------------------
    def _on_drive_context_menu(self, pos, list_widget):
        """
        Menú clic derecho para elementos de la Nube.
        MODIFICADO: Busca selecciones en TODOS los meses.
        """
        # 1. BÚSQUEDA GLOBAL DE SELECCIÓN EN LA NUBE
        container = list_widget.parent()
        selected_items = []

        if container:
            for lw in container.findChildren(PreviewListWidget):
                selected_items.extend(lw.selectedItems())
        else:
            selected_items = list_widget.selectedItems()

        if not selected_items:
            return

        menu = QMenu(self)

        # Informativo
        count = len(selected_items)
        header = menu.addAction(f"{count} foto(s) seleccionada(s)")
        header.setEnabled(False)
        menu.addSeparator()

        # Opción: Cambiar Fecha
        action_date = menu.addAction("Cambiar Fecha (Localmente)")
        action_date.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))

        action = menu.exec(list_widget.mapToGlobal(pos))

        if action == action_date:
            # Pasamos la lista acumulada de todos los meses
            self._change_date_for_drive_items(selected_items)

    def _change_date_for_drive_items(self, items):
        """
        Abre el diálogo UNA sola vez y aplica la fecha a TODAS las fotos seleccionadas de Drive.
        """
        if not items: return

        # 1. Abrir diálogo (Solo una vez para todo el grupo)
        dialog = DateChangeDialog(self)
        if dialog.exec() == QDialog.Accepted:
            new_year, new_month = dialog.get_data()

            # Fecha ISO ficticia para ordenar: YYYY-MM-01T12:00...
            new_iso_date = f"{new_year}-{new_month}-01T12:00:00.000Z"

            count = 0
            total = len(items)

            self._set_status(f"Actualizando fecha de {total} elementos en la nube (localmente)...")

            # 2. Iterar sobre TODOS los elementos seleccionados
            for i, item in enumerate(items):
                try:
                    data = item.data(Qt.UserRole)
                    if not data: continue

                    file_id = data['id']

                    # Actualizar DB
                    self.db.update_drive_photo_date(file_id, new_iso_date)

                    # Actualizar estructura en Memoria (RAM) para que el cambio sea instantáneo
                    # Buscamos y eliminamos la foto de su fecha antigua
                    found = False
                    for y, months in self.drive_photos_by_date.items():
                        for m, photos in months.items():
                            # photos es una lista de diccionarios
                            for p in photos:
                                if p['id'] == file_id:
                                    # Actualizamos la fecha en el objeto en memoria
                                    p['createdTime'] = new_iso_date

                                    # La quitamos de la lista vieja
                                    photos.remove(p)

                                    # La añadimos a la lista nueva (creando claves si faltan)
                                    if new_year not in self.drive_photos_by_date:
                                        self.drive_photos_by_date[new_year] = {}
                                    if new_month not in self.drive_photos_by_date[new_year]:
                                        self.drive_photos_by_date[new_year][new_month] = []

                                    self.drive_photos_by_date[new_year][new_month].append(p)
                                    found = True
                                    break
                            if found: break
                        if found: break

                    count += 1

                except Exception as e:
                    print(f"Error actualizando item {i}: {e}")

            self._set_status(f"Fecha actualizada para {count} fotos. Reorganizando vista...")

            # 3. Recargar la vista completa para reflejar los movimientos
            # Forzamos la limpieza visual y el redibujado
            self.cloud_scroll_area.setUpdatesEnabled(False)
            self._display_cloud_photos()
            self.cloud_scroll_area.setUpdatesEnabled(True)

    # ----------------------------------------------------------------
    # LÓGICA DE MENÚ CONTEXTUAL Y GESTIÓN DE ARCHIVOS
    # ----------------------------------------------------------------

    def _on_context_menu(self, pos, list_widget, is_video, is_hidden_view=False):
        """
        Muestra el menú contextual con opciones para fotos/vídeos.
        INCLUYE: Soporte para Caja Fuerte.
        """
        # 1. BÚSQUEDA GLOBAL DE SELECCIÓN
        # Obtenemos el contenedor padre (el área de scroll) para ver si hay selección múltiple entre meses
        container = list_widget.parent()
        selected_items = []

        if container:
            # Buscamos en todas las listas de meses que haya en el panel
            for lw in container.findChildren(PreviewListWidget):
                selected_items.extend(lw.selectedItems())
        else:
            # Fallback por si algo falla
            selected_items = list_widget.selectedItems()

        if not selected_items:
            return

        menu = QMenu(self)

        if is_hidden_view:
            # --- OPCIONES PARA VISTA DE OCULTOS ---
            action_restore = menu.addAction("Restaurar a la galería")
            action_restore.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))

            action_delete = menu.addAction("Mover a la papelera")
            action_delete.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))

            action = menu.exec(list_widget.mapToGlobal(pos))

            if action == action_restore:
                self._restore_selected_media(selected_items, is_video)
            elif action == action_delete:
                self._delete_selected_media(selected_items, is_video, from_hidden_view=True)

        else:
            # --- OPCIONES PARA VISTA NORMAL ---

            # Cabecera informativa
            count = len(selected_items)
            header = menu.addAction(f"{count} elemento(s) seleccionado(s)")
            header.setEnabled(False)
            menu.addSeparator()

            # 1. Cambiar Fecha
            action_date = menu.addAction("Cambiar Fecha (Mover)")
            action_date.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))

            # 2. Corregir Ojos Rojos (SOLO PARA FOTOS)
            action_redeye = None
            if not is_video:
                action_redeye = menu.addAction("Corregir Ojos Rojos (Auto)")
                action_redeye.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))

            # 3. Caja Fuerte
            action_safe = menu.addAction("🔒 Añadir a Caja Fuerte")

            menu.addSeparator()

            # 4. Ocultar y Eliminar
            action_hide = menu.addAction("Ocultar de la vista")

            action_delete = menu.addAction("Mover a la papelera")
            action_delete.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))

            # Ejecutar menú
            action = menu.exec(list_widget.mapToGlobal(pos))

            # --- MANEJO DE ACCIONES ---
            if action == action_hide:
                self._hide_selected_media(selected_items, is_video)

            elif action == action_delete:
                self._delete_selected_media(selected_items, is_video, from_hidden_view=False)

            elif action == action_date:
                self._change_date_for_selected(selected_items, is_video)

            elif action_redeye and action == action_redeye:
                self._remove_red_eyes_for_selected(selected_items)

            elif action == action_safe:
                self._move_to_safe_box(selected_items, is_video)

    def _remove_red_eye_from_image(self, image_path):
        """Corrige los ojos rojos (ver redeye.py). True si se ha modificado la foto."""
        try:
            return redeye.remove_red_eyes(image_path)
        except Exception as e:
            print(f"Error corrigiendo ojos rojos en {image_path}: {e}")
            return False

    def _invalidate_photo_caches(self, photo_path):
        """Borra la miniatura (disco y RAM) y los recortes de caras de una foto modificada."""
        purge_media_caches(self.db.conn, photo_path)

    def _restore_selected_media(self, items, is_video):
        """Restaura los elementos seleccionados a la vista principal."""
        paths_to_restore = [item.data(Qt.UserRole) for item in items]
        restored_count = 0

        for path in paths_to_restore:
            try:
                year, month = None, None
                target_dict = None

                if is_video:
                    self.db.unhide_video(path)
                    year, month = self.db.get_video_date(path)
                    target_dict = self.videos_by_year_month
                else:
                    self.db.unhide_photo(path)
                    year, month = self.db.get_photo_date(path)
                    target_dict = self.photos_by_year_month

                # Volver a añadir a la estructura de memoria (Diccionario)
                if year and month and target_dict is not None:
                    if year not in target_dict: target_dict[year] = {}
                    if month not in target_dict[year]: target_dict[year][month] = []

                    if path not in target_dict[year][month]:
                        target_dict[year][month].append(path)
                        restored_count += 1

            except Exception as e:
                print(f"Error restaurando {path}: {e}")

        self._set_status(f"{restored_count} elementos restaurados.")

        # Refrescar la vista actual (Ocultos) para que desaparezcan de aquí
        if is_video:
            self._show_hidden_videos_view()
        else:
            self._show_hidden_photos_view()

    def _hide_selected_media(self, items, is_video):
        """Oculta los elementos seleccionados."""
        paths_to_hide = [item.data(Qt.UserRole) for item in items]

        for path in paths_to_hide:
            try:
                if is_video:
                    self.db.hide_video(path)
                    self._remove_from_memory_struct(path, self.videos_by_year_month)
                else:
                    self.db.hide_photo(path)
                    self._remove_from_memory_struct(path, self.photos_by_year_month)
            except Exception as e:
                print(f"Error ocultando {path}: {e}")

        self._set_status(f"{len(items)} elementos ocultados.")
        # Refrescar la vista actual
        if is_video:
            self._display_videos()
        else:
            self._display_photos()

    def _update_file_metadata_on_disk(self, filepath, year_str, month_str):
        """
        Intenta escribir la fecha en los metadatos del archivo.
        1. Para JPG: Escribe en EXIF (DateTimeOriginal).
        2. Para TODO (Videos/RAW/JPG): Cambia la fecha de modificación del archivo.
        """
        try:
            # 1. Preparar la fecha
            # Si el mes es '00' o inválido, ponemos Enero
            m = int(month_str) if month_str.isdigit() and 1 <= int(month_str) <= 12 else 1
            y = int(year_str)

            # Creamos una fecha arbitraria (día 1 a las 12:00)
            new_date = datetime.datetime(y, m, 1, 12, 0, 0)

            # Convertir a timestamp para el sistema de archivos
            timestamp = new_date.timestamp()

            # 2. INTENTAR ESCRIBIR EXIF (Solo JPG/JPEG/TIFF)
            ext = os.path.splitext(filepath)[1].lower()
            if ext in ['.jpg', '.jpeg', '.tiff', '.tif']:
                try:
                    # Formato EXIF: "YYYY:MM:DD HH:MM:SS"
                    exif_date_str = new_date.strftime("%Y:%m:%d %H:%M:%S")

                    # Cargar datos existentes o crear nuevos
                    exif_dict = piexif.load(filepath)

                    # Actualizar DateTimeOriginal, DateTimeDigitized y DateTime
                    exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal] = exif_date_str
                    exif_dict['Exif'][piexif.ExifIFD.DateTimeDigitized] = exif_date_str
                    exif_dict['0th'][piexif.ImageIFD.DateTime] = exif_date_str

                    exif_bytes = piexif.dump(exif_dict)
                    piexif.insert(exif_bytes, filepath)
                    print(f"EXIF actualizado para: {filepath}")
                except Exception as e_exif:
                    print(f"No se pudo escribir EXIF en {filepath} (posiblemente corrupto o sin cabecera): {e_exif}")

            # 3. CAMBIAR FECHA DEL SISTEMA DE ARCHIVOS (Para Vídeos, RAWs y respaldo de JPG)
            # Al indexar, get_photo_date/get_video_date usan esta fecha si el nombre
            # del archivo no contiene una (el EXIF no se lee al indexar).
            os.utime(filepath, (timestamp, timestamp))

        except Exception as e:
            print(f"Error general actualizando fichero físico {filepath}: {e}")

    def _change_date_for_selected(self, items, is_video):
        """
        Cambia la fecha de TODOS los elementos locales seleccionados (Disco + DB).
        """
        if not items: return

        # 1. Abrir diálogo UNA vez
        dialog = DateChangeDialog(self)
        if dialog.exec() == QDialog.Accepted:
            new_year, new_month = dialog.get_data()

            count = 0
            total = len(items)
            paths_to_update = [item.data(Qt.UserRole) for item in items]

            self._set_status(f"Procesando cambio de fecha para {total} archivos...")

            # 2. Iterar y aplicar cambios
            for i, path in enumerate(paths_to_update):
                try:
                    # A) Actualizar archivo FÍSICO (Metadatos + Fecha Modificación)
                    self._update_file_metadata_on_disk(path, new_year, new_month)

                    # B) Actualizar Base de Datos y Memoria
                    if is_video:
                        self.db.update_video_date(path, new_year, new_month)

                        # Mover en memoria (Vídeos)
                        self._remove_from_memory_struct(path, self.videos_by_year_month)
                        if new_year not in self.videos_by_year_month:
                            self.videos_by_year_month[new_year] = {}
                        if new_month not in self.videos_by_year_month[new_year]:
                            self.videos_by_year_month[new_year][new_month] = []
                        self.videos_by_year_month[new_year][new_month].append(path)

                    else:
                        self.db.update_photo_date(path, new_year, new_month)

                        # Mover en memoria (Fotos)
                        self._remove_from_memory_struct(path, self.photos_by_year_month)
                        if new_year not in self.photos_by_year_month:
                            self.photos_by_year_month[new_year] = {}
                        if new_month not in self.photos_by_year_month[new_year]:
                            self.photos_by_year_month[new_year][new_month] = []
                        self.photos_by_year_month[new_year][new_month].append(path)

                    count += 1

                    # Actualizar estado cada 10 fotos para no saturar
                    if i % 10 == 0:
                        self._set_status(f"Actualizando fecha ({i+1}/{total})...")

                except Exception as e:
                    print(f"Error actualizando fecha de {path}: {e}")

            self._set_status(f"Fecha cambiada correctamente en {count} archivos. Refrescando...")

            # 3. Refrescar la vista correspondiente
            if is_video:
                self.video_scroll_area.setUpdatesEnabled(False)
                self._display_videos()
                self.video_scroll_area.setUpdatesEnabled(True)
            else:
                self.scroll_area.setUpdatesEnabled(False)
                self._display_photos()
                self.scroll_area.setUpdatesEnabled(True)

    def _delete_selected_media(self, items, is_video, from_hidden_view=False):
        """Mueve los archivos a la papelera del sistema y los quita de la BD."""
        count = len(items)
        confirm = QMessageBox.question(
            self,
            "Mover a la papelera",
            f"¿Mover {count} archivo(s) a la papelera?\nPodrás recuperarlos desde la papelera del sistema.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if confirm != QMessageBox.StandardButton.Yes:
            return

        paths_to_delete = [item.data(Qt.UserRole) for item in items]
        deleted_count = 0

        # 1. Papelera (los que no se puedan mover ni el usuario quiera borrar se quedan)
        for path in send_files_to_trash(self, paths_to_delete):
            try:
                # 2. Quitar de la BD
                purge_media_caches(self.db.conn, path)
                if is_video:
                    self.db.delete_video_permanently(path)
                    # Solo borrar de memoria si NO estaba oculta (si estaba oculta, ya no estaba en memoria)
                    if not from_hidden_view:
                        self._remove_from_memory_struct(path, self.videos_by_year_month)
                else:
                    self.db.delete_photo_permanently(path)
                    if not from_hidden_view:
                        self._remove_from_memory_struct(path, self.photos_by_year_month)

                deleted_count += 1
            except Exception as e:
                print(f"Error eliminando {path}: {e}")
                self._set_status(f"Error eliminando: {Path(path).name}")

        self._set_status(f"{deleted_count} archivo(s) movido(s) a la papelera.")

        # Refrescar la vista correspondiente
        if from_hidden_view:
            if is_video: self._show_hidden_videos_view()
            else: self._show_hidden_photos_view()
        else:
            if is_video: self._display_videos()
            else: self._display_photos()

    def _remove_from_memory_struct(self, path, struct):
        """Ayuda a eliminar un path del diccionario year/month."""
        for year, months in struct.items():
            for month, files in months.items():
                if path in files:
                    files.remove(path)
                    # Limpieza si quedan vacíos
                    if not files:
                        del struct[year][month]
                    if not struct[year]:
                        del struct[year]
                    return

    # ------------------------------------------------------------------
    # NUEVA LÓGICA DE SINCRONIZACIÓN SCROLL -> ÁRBOL
    # ------------------------------------------------------------------

    def _on_photo_scroll_changed(self):
        """Sincroniza el árbol de fechas de fotos al hacer scroll."""
        self._sync_tree_from_scroll(
            self.scroll_area,
            self.photo_group_widgets,
            self.date_tree_widget
        )

    def _on_video_scroll_changed(self):
        """Sincroniza el árbol de fechas de vídeos al hacer scroll."""
        self._sync_tree_from_scroll(
            self.video_scroll_area,
            self.video_group_widgets,
            self.video_date_tree_widget
        )

    def _on_cloud_scroll_changed(self):
        """Sincroniza el árbol de fechas de la Nube al hacer scroll."""
        self._sync_tree_from_scroll(
            self.cloud_scroll_area,
            self.cloud_group_widgets,
            self.cloud_date_tree
        )

    def _sync_tree_from_scroll(self, scroll_area, group_widgets_dict, tree_widget):
        """
        Calcula qué etiqueta (Año/Mes) está visible en la parte superior
        y selecciona el item correspondiente en el árbol.
        """
        if not group_widgets_dict: return

        # Obtenemos la posición vertical actual del scroll
        viewport_top = scroll_area.verticalScrollBar().value()

        best_key = None
        best_y = -1

        # Buscamos el widget (etiqueta de año o mes) que esté más abajo
        # pero que aún esté por encima (o rozando) la línea superior de la vista.
        # Le damos un margen de 50px para que la selección cambie justo cuando el título llega arriba.

        container_widget = scroll_area.widget()
        if not container_widget: return

        # Iteramos sobre los widgets registrados (etiquetas de texto Año/Mes)
        for key, widget in group_widgets_dict.items():
            try:
                if not widget.isVisible(): continue

                # Posición Y del widget dentro del área total
                y = widget.y()

                # Si el widget está por encima de mi vista actual (+ margen)
                if y <= viewport_top + 80:
                    # Me quedo con el que tenga la Y más alta (el que está más cerca de mi vista actual)
                    if y > best_y:
                        best_y = y
                        best_key = key
            except RuntimeError:
                pass # El widget pudo haber sido borrado

        if best_key:
            # Ahora buscamos ese item en el árbol para seleccionarlo
            # Las claves son "YYYY" o "YYYY-MM"
            self._select_tree_item_by_key(tree_widget, best_key)

    def _select_tree_item_by_key(self, tree_widget, key):
        """Selecciona un item en el árbol de forma inteligente (soporta Texto y Tuplas)."""
        tree_widget.blockSignals(True)

        try:
            # Descomponemos la clave (Ej: "2023-05")
            parts = key.split('-')
            year = parts[0]
            month = parts[1] if len(parts) > 1 else None

            # 1. Buscar el AÑO (Primer nivel)
            year_item = None
            for i in range(tree_widget.topLevelItemCount()):
                item = tree_widget.topLevelItem(i)
                # Comparamos como string por seguridad
                if str(item.text(0)) == str(year):
                    year_item = item
                    break

            target_item = None

            if year_item:
                if month:
                    # 2. Buscar el MES (Hijo)
                    # Aquí está la mejora: comprobamos el dato de forma flexible
                    for i in range(year_item.childCount()):
                        child = year_item.child(i)
                        data = child.data(0, Qt.UserRole)

                        is_match = False

                        # CASO A: El dato es una Tupla o Lista ['2023', '05'] (Fotos/Videos/Nube nueva)
                        if isinstance(data, (list, tuple)) and len(data) > 1:
                            if str(data[1]) == str(month):
                                is_match = True

                        # CASO B: El dato es Texto "2023-05" (Nube antigua)
                        elif isinstance(data, str):
                            # Comprobamos si termina en "-05" o es igual a "05"
                            if data == month or data.endswith(f"-{month}"):
                                is_match = True

                        if is_match:
                            target_item = child
                            break

                    # Si buscábamos un mes y no lo encontramos, nos quedamos en el año
                    if not target_item:
                        target_item = year_item
                else:
                    # Si la clave solo era el año
                    target_item = year_item

            if target_item:
                tree_widget.setCurrentItem(target_item)
                tree_widget.scrollToItem(target_item)

        finally:
            tree_widget.blockSignals(False)

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _scroll_to_item(self, current_item: QTreeWidgetItem, previous_item: QTreeWidgetItem):
        self._scroll_to_group(current_item, is_video=False)

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _scroll_to_video_item(self, current_item: QTreeWidgetItem, previous_item: QTreeWidgetItem):
        self._scroll_to_group(current_item, is_video=True)

    def _scroll_to_group(self, current_item, is_video):
        """Desplaza la galería al año/mes elegido en el árbol de fechas."""
        if not current_item: return
        user_data = current_item.data(0, Qt.UserRole)
        if user_data == "HIDDEN_SECTION":
            self._show_hidden_view(is_video)
            return

        if current_item.parent():
            year, month = user_data
            target_key = f"{year}-{month}"
        else:
            target_key = current_item.text(0)

        g = self._gallery(is_video)
        target_widget = getattr(self, g.groups_attr, {}).get(target_key)
        alive = False
        if target_widget is not None:
            try:
                target_widget.isVisible()
                alive = True
            except RuntimeError:
                pass  # Widget ya destruido (p. ej. tras ver los ocultos)

        if not alive:
            self._display_media(is_video)
            target_widget = getattr(self, g.groups_attr, {}).get(target_key)

        if target_widget:
            try:
                g.scroll.ensureWidgetVisible(target_widget, 50, 50)
                QTimer.singleShot(200, lambda: self._load_visible_gallery_thumbnails(is_video))
            except RuntimeError:
                print(f"Aviso: no se pudo desplazar la galería de {g.kind}.")

    @Slot(object, list)
    def _handle_search_finished(self, new_photos_by_year_month, missing_paths):
        """Se llama cuando el PhotoFinderWorker termina."""
        self.select_dir_button.setEnabled(True)

        # Carpeta no disponible: no se toca ni la galería ni la BD
        if new_photos_by_year_month is None:
            self._set_status("La carpeta de fotos no está disponible (¿disco desconectado?). Biblioteca sin cambios.")
            return

        if missing_paths:
            QTimer.singleShot(0, lambda: self._confirm_missing_removal(missing_paths, is_video=False))

        # 1. OPTIMIZACIÓN: Si los datos no han cambiado, NO redibujamos nada.
        # Esto evita parpadeos por falsas alarmas del vigilante.
        if self.photos_by_year_month == new_photos_by_year_month:
            # print("Escaneo completado: Sin cambios detectados.")
            # Aún así lanzamos el escáner de caras por si acaso
            self._start_face_scan()
            return

        # Si hay cambios reales, procedemos:
        self.photos_by_year_month = new_photos_by_year_month

        num_fotos = sum(len(photos) for months in self.photos_by_year_month.values() for photos in months.values())
        self._set_status(f"Actualizando biblioteca... {num_fotos} fotos.")

        # 2. TRUCO VISUAL: Congelar la interfaz para evitar el parpadeo blanco
        self.scroll_area.setUpdatesEnabled(False)

        # 3. Guardar posición del scroll
        current_scroll = self.scroll_area.verticalScrollBar().value()

        # Redibujar
        self._display_photos()

        # 4. Restaurar scroll y descongelar
        self.scroll_area.verticalScrollBar().setValue(current_scroll)
        self.scroll_area.setUpdatesEnabled(True)

        self._start_face_scan()

    @Slot(object, list)
    def _handle_video_search_finished(self, new_videos_by_year_month, missing_paths):
        """Se llama cuando el VideoFinderWorker termina."""
        self.select_dir_button.setEnabled(True)

        if new_videos_by_year_month is None:
            self._set_status("La carpeta de vídeos no está disponible (¿disco desconectado?). Biblioteca sin cambios.")
            return

        if missing_paths:
            QTimer.singleShot(0, lambda: self._confirm_missing_removal(missing_paths, is_video=True))

        # 1. Verificar cambios
        if self.videos_by_year_month == new_videos_by_year_month:
            # print("Escaneo de vídeos completado: Sin cambios.")
            return

        self.videos_by_year_month = new_videos_by_year_month

        num_videos = sum(len(videos) for months in self.videos_by_year_month.values() for videos in months.values())
        self._set_status(f"Actualizando biblioteca... {num_videos} vídeos.")

        # 2. Congelar
        self.video_scroll_area.setUpdatesEnabled(False)

        # 3. Guardar Scroll
        current_scroll = self.video_scroll_area.verticalScrollBar().value()

        # Redibujar
        self._display_videos()

        # 4. Restaurar y Descongelar
        self.video_scroll_area.verticalScrollBar().setValue(current_scroll)
        self.video_scroll_area.setUpdatesEnabled(True)

    def _confirm_missing_removal(self, missing_paths, is_video):
        """
        Pregunta antes de quitar de la BD muchos archivos desaparecidos de golpe
        (p. ej. un disco externo o NAS desmontado), para no perder fechas,
        caras ni personas por error.
        """
        # No volver a preguntar en esta sesión por archivos que ya decidió conservar
        pending = [p for p in missing_paths if p not in self.kept_missing_paths]
        if not pending:
            return

        kind = "vídeos" if is_video else "fotos"
        answer = QMessageBox.question(
            self,
            "Archivos no encontrados",
            f"{len(pending)} {kind} de la biblioteca ya no están en la carpeta:\n"
            f"{self.current_directory}\n\n"
            "Si el disco o la unidad de red está desconectado, responde «No»: "
            "se conservarán sus fechas, caras y personas hasta que vuelva a estar disponible.\n\n"
            f"¿Quitar esos {kind} de la biblioteca definitivamente?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if answer == QMessageBox.StandardButton.Yes:
            for path in pending:
                purge_media_caches(self.db.conn, path)
            if is_video:
                self.db.bulk_delete_videos(pending)
            else:
                self.db.bulk_delete_photos(pending)
            self._set_status(f"{len(pending)} {kind} quitados de la biblioteca.")
        else:
            self.kept_missing_paths.update(pending)
            self._set_status(f"Se conservan en la biblioteca {len(pending)} {kind} no encontrados.")

    def _set_status(self, message):
        # Usamos la barra de estado nativa de la ventana (visible en todas las pestañas)
        self.statusBar().showMessage(f"Estado: {message}")

    def _debounced_thumbnail_load(self):
        """Espera a que el usuario deje de hacer scroll antes de cargar imágenes."""
        if hasattr(self, '_thumb_timer') and self._thumb_timer.isActive():
            self._thumb_timer.stop()

        self._thumb_timer = QTimer()
        self._thumb_timer.setSingleShot(True)
        # Esperar 150ms de quietud antes de cargar. Ajusta si lo notas lento.
        self._thumb_timer.setInterval(150)
        self._thumb_timer.timeout.connect(self._load_main_visible_thumbnails)
        self._thumb_timer.start()

    def _load_main_visible_thumbnails(self):
        self._load_visible_gallery_thumbnails(is_video=False)

    def _load_visible_video_thumbnails(self):
        self._load_visible_gallery_thumbnails(is_video=True)

    def _load_visible_gallery_thumbnails(self, is_video):
        """Lanza la carga de las miniaturas visibles (y un margen) de Fotos o Vídeos."""
        g = self._gallery(is_video)
        viewport = g.scroll.viewport()
        preload_rect = viewport.rect().adjusted(0, -PRELOAD_MARGIN_PX, 0, PRELOAD_MARGIN_PX)
        container = g.scroll.widget()
        if not container:
            return
        for list_widget in container.findChildren(PreviewListWidget):
            pos = list_widget.mapTo(viewport, list_widget.rect().topLeft())
            if not preload_rect.intersects(list_widget.rect().translated(pos)):
                continue
            for i in range(list_widget.count()):
                item = list_widget.item(i)
                original_path = item.data(Qt.UserRole)
                if item.data(Qt.UserRole + 1) == "not_loaded" and original_path:
                    item.setData(Qt.UserRole + 1, "loading")
                    item.setText("Cargando...")
                    self.threadpool.start(g.loader(original_path, self.thumb_signals))

    @Slot()
    def _load_person_visible_thumbnails(self):
        # Esta función (Pestaña Personas) no ha sido refactorizada,
        # así que su lógica original de "findChildren(ZoomableClickableLabel)"
        # sigue siendo correcta.
        viewport = self.person_photo_scroll_area.viewport()
        preload_rect = viewport.rect().adjusted(0, -PRELOAD_MARGIN_PX, 0, PRELOAD_MARGIN_PX)
        person_photo_widget = self.person_photo_scroll_area.widget()
        if not person_photo_widget:
            return
        for photo_label in person_photo_widget.findChildren(ZoomableClickableLabel):
            original_path = photo_label.property("original_path")
            is_loaded = photo_label.property("loaded")
            if original_path and is_loaded is False:
                label_pos = photo_label.mapTo(viewport, photo_label.rect().topLeft())
                label_rect_in_viewport = photo_label.rect().translated(label_pos)
                if preload_rect.intersects(label_rect_in_viewport):
                    photo_label.setProperty("loaded", None)
                    loader = ThumbnailLoader(original_path, self.thumb_signals)
                    self.threadpool.start(loader)

    @Slot(str, QImage)
    def _update_thumbnail(self, original_path, image):
        pixmap = QPixmap.fromImage(image)  # Conversión en el hilo de la UI
        # ---------------------------------------------------------
        # 1. BLOQUE PARA FOTOS LOCALES
        # ---------------------------------------------------------
        if original_path in self.photo_list_widget_items:
            item = self.photo_list_widget_items[original_path]
            scaled_pixmap = pixmap.scaled(
                self.current_thumbnail_size,
                self.current_thumbnail_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            item.setIcon(QIcon(scaled_pixmap))
            item.setSizeHint(scaled_pixmap.size())
            item.setText("")
            item.setData(Qt.UserRole + 1, "loaded")
            return

        # ---------------------------------------------------------
        # 2. BLOQUE PARA VÍDEOS
        # ---------------------------------------------------------
        if original_path in self.video_list_widget_items:
            item = self.video_list_widget_items[original_path]
            scaled_pixmap = pixmap.scaled(
                self.current_thumbnail_size,
                self.current_thumbnail_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            item.setIcon(QIcon(scaled_pixmap))
            item.setSizeHint(scaled_pixmap.size())
            item.setText("")
            item.setData(Qt.UserRole + 1, "loaded")
            return

        # ---------------------------------------------------------
        # 3. BLOQUE PARA DRIVE
        # ---------------------------------------------------------
        item = self.cloud_list_widget_items.get(original_path)
        if item is not None:
            try:
                scaled = pixmap.scaled(
                    self.current_thumbnail_size, self.current_thumbnail_size,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                item.setIcon(QIcon(scaled))
                # Ajusta la celda al tamaño real de la imagen (ej: 128x90)
                item.setSizeHint(scaled.size())
                item.setText("")
                item.setData(Qt.UserRole + 1, "loaded")
            except RuntimeError:
                pass  # La lista se destruyó mientras se descargaba
            return

        # ---------------------------------------------------------
        # 4. BLOQUE PARA PERSONAS
        # ---------------------------------------------------------
        def update_in_container(container_widget):
            if not container_widget: return
            for label in container_widget.findChildren(ZoomableClickableLabel):
                if label.property("original_path") == original_path and label.property("loaded") is not True:
                    label.setPixmap(pixmap.scaled(THUMBNAIL_SIZE[0], THUMBNAIL_SIZE[1], Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    label.setText("")
                    label.setProperty("loaded", True)

        update_in_container(self.person_photo_scroll_area.widget())

    # -------------------------------------------------------------------------
    # GESTIÓN DE VISTA PREVIA EN LA NUBE
    # -------------------------------------------------------------------------

    @Slot(object)
    def _on_drive_preview_requested(self, file_data):
        """
        Maneja la solicitud de vista previa desde la nube.
        """
        if not isinstance(file_data, dict): return
        file_id = file_data.get('id')
        name = file_data.get('name')
        if not file_id or not name: return

        try:
            local_path = drive_cache_path(file_id, name)
        except ValueError as e:
            print(e)
            return

        self._set_status(f"Vista previa: Bajando {name}...")

        # Comprobar Caché
        if os.path.exists(local_path):
            if os.path.getsize(local_path) == 0:
                try: os.remove(local_path)
                except: pass
            else:
                touch_cache_file(local_path)
                self._open_preview_dialog(local_path)
                self._set_status("Vista previa (desde caché).")
                return

        # Descarga en hilo seguro
        threading.Thread(target=self._download_thread_safe, args=(file_id, local_path), daemon=True).start()

    def _download_thread_safe(self, file_id, local_path):
        """Descarga el archivo sin bloquear la interfaz."""
        # Se descarga a un temporal: si se corta, no queda un archivo a medias
        # que la siguiente vez se tomaría como caché válida
        part_path = local_path + ".part"
        try:
            manager = DriveManager()
            manager.download_file(file_id, part_path)
            os.replace(part_path, local_path)

            # Volver al hilo principal para abrir la ventana
            self.drive_download_signals.finished.emit(local_path)
            trim_drive_caches()
        except DriveAuthError as e:
            self.drive_download_signals.failed.emit(str(e))
        except Exception as e:
            print(f"Error descarga preview: {e}")
            self.drive_download_signals.failed.emit("Error al descargar imagen.")
        finally:
            if os.path.exists(part_path):
                try: os.remove(part_path)
                except OSError: pass

    @Slot(str)
    def _finish_cloud_preview(self, local_path):
        """Se ejecuta en el hilo principal cuando la descarga termina."""
        self._set_status("Imagen descargada. Abriendo visor...")
        self._open_preview_dialog(local_path)

    @Slot(str)
    def _handle_thumbnail_failed(self, original_path: str):

        # REFACTOR: Comprobar si es un item de QListWidget de FOTOS
        if original_path in self.photo_list_widget_items:
            item = self.photo_list_widget_items[original_path]
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon) # Icono genérico
            item.setIcon(icon)
            item.setText("") # Quitar "Cargando..."
            item.setData(Qt.UserRole + 1, "failed") # Marcar como fallido
            return

        # REFACTOR: Comprobar si es un item de QListWidget de VÍDEOS
        if original_path in self.video_list_widget_items:
            item = self.video_list_widget_items[original_path]
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon) # Icono genérico
            item.setIcon(icon)
            item.setText("") # Quitar "Cargando..."
            item.setData(Qt.UserRole + 1, "failed") # Marcar como fallido
            return

        # Nube
        item = self.cloud_list_widget_items.get(original_path)
        if item is not None:
            try:
                item.setData(Qt.UserRole + 1, "failed")
            except RuntimeError:
                pass
            return

        # Lógica original (para la pestaña Personas)
        def fail_in_container(container_widget):
            if not container_widget:
                return
            for label in container_widget.findChildren(ZoomableClickableLabel):
                if label.property("original_path") == original_path and label.property("loaded") is not True:
                    label.setText("Error al cargar.")
                    label.setProperty("loaded", True)

        fail_in_container(self.person_photo_scroll_area.widget())


    @Slot()
    def _save_photo_splitter_state(self):
        self._save_splitter_state(is_video=False)

    @Slot()
    def _save_video_splitter_state(self):
        self._save_splitter_state(is_video=True)

    def _save_splitter_state(self, is_video):
        """Guarda las posiciones del splitter de Fotos o Vídeos en la configuración."""
        g = self._gallery(is_video)
        config_data = config_manager.load_config()
        config_data[g.splitter_key] = g.splitter.sizes()
        config_manager.save_config(config_data)

    def _load_photo_splitter_state(self):
        self._load_splitter_state(is_video=False)

    def _load_video_splitter_state(self):
        self._load_splitter_state(is_video=True)

    def _load_splitter_state(self, is_video):
        """Carga posiciones y prioridades de estiramiento: árbol | galería | fechas."""
        g = self._gallery(is_video)
        g.splitter.setStretchFactor(0, 0)  # Árbol de carpetas
        g.splitter.setStretchFactor(1, 1)  # Galería (se estira)
        g.splitter.setStretchFactor(2, 0)  # Árbol de fechas

        sizes = config_manager.load_config().get(g.splitter_key)
        min_right_width = 180

        # Migración de config antigua (sin árbol de carpetas)
        if sizes and len(sizes) == 2:
            sizes.insert(0, 0)
        if not sizes or len(sizes) != 3:
            w = self.width()
            sizes = [0, int(w * 0.8), int(w * 0.2)]

        # Proteger el ancho mínimo del panel derecho
        if sizes[2] < min_right_width:
            diff = min_right_width - sizes[2]
            sizes[2] = min_right_width
            if sizes[1] > diff:
                sizes[1] -= diff

        g.splitter.setSizes(sizes)

    def resizeEvent(self, event):
        self.resize_timer.start()
        super().resizeEvent(event)

    @Slot()
    def _handle_resize_timeout(self):
        """Recoloca las galerías al nuevo ancho sin reconstruirlas."""
        self._relayout_galleries()
        self._reflow_faces()
        # Con más ancho pueden quedar a la vista miniaturas aún sin cargar
        QTimer.singleShot(0, self._load_main_visible_thumbnails)
        QTimer.singleShot(0, self._load_visible_video_thumbnails)

    def _gallery_lists(self, include_cloud=False):
        """(lista, área de scroll) de las listas de miniaturas de Fotos y Vídeos (y Nube)."""
        areas = [self.scroll_area, self.video_scroll_area]
        if include_cloud:
            areas.append(self.cloud_scroll_area)
        for area in areas:
            container = area.widget()
            if not container:
                continue
            for list_widget in container.findChildren(PreviewListWidget):
                yield list_widget, area

    def _fit_grid_height(self, list_widget, scroll_area):
        """Altura fija para que la lista muestre todas sus filas sin scroll propio."""
        item_size = self.current_thumbnail_size + (list_widget.property("thumb_padding") or 10)
        spacing = list_widget.spacing()
        viewport_width = scroll_area.viewport().width() - 30
        if viewport_width < 100:
            viewport_width = 800  # Pestaña aún oculta: se recalcula al redimensionar
        num_cols = max(1, viewport_width // (item_size + spacing))
        rows = (list_widget.count() + num_cols - 1) // num_cols
        list_widget.setFixedHeight(rows * item_size + (rows + 1) * spacing)

    def _relayout_galleries(self):
        for list_widget, area in self._gallery_lists():
            if list_widget.property("fixed_grid"):
                self._fit_grid_height(list_widget, area)

    def _apply_thumbnail_size(self):
        """Aplica el zoom a las listas existentes sin reconstruir la galería."""
        size = self.current_thumbnail_size
        for list_widget, _area in self._gallery_lists(include_cloud=True):
            list_widget.setIconSize(QSize(size, size))
            cell = size + (list_widget.property("thumb_padding") or 10)
            for i in range(list_widget.count()):
                item = list_widget.item(i)
                item.setSizeHint(QSize(cell, cell))
                # Las ya cargadas se reescalan al volver a pedirlas (salen de la caché en RAM)
                if item.data(Qt.UserRole + 1) == "loaded":
                    item.setData(Qt.UserRole + 1, "not_loaded")
        self._relayout_galleries()
        # La Nube ajusta su altura al contenido real (miniaturas de proporciones variables)
        cloud_widget = self.cloud_scroll_area.widget()
        if cloud_widget:
            for list_widget in cloud_widget.findChildren(PreviewListWidget):
                QTimer.singleShot(0, list_widget.adjust_height_to_content)
        QTimer.singleShot(0, self._load_main_visible_thumbnails)
        QTimer.singleShot(0, self._load_visible_video_thumbnails)
        # Las de la Nube salen de la caché en disco/RAM: no se vuelven a descargar
        QTimer.singleShot(0, self._load_visible_cloud_thumbnails)

    @Slot(str)
    def _open_photo_detail(self, original_path):
        """Abre la ventana de detalle de la foto."""
        self._set_status(f"Abriendo detalle para: {Path(original_path).name}")
        dialog = PhotoDetailDialog(original_path, self.db, self)
        dialog.metadata_changed.connect(self._handle_photo_date_changed)
        dialog.exec()
        self._set_status("Detalle cerrado.")



    @Slot(str)
    def _open_preview_dialog(self, original_path: str):
        """
        Abre la vista previa (ImagePreviewDialog) para una imagen,
        manejando formatos estándar y RAW.
        """
        if ImagePreviewDialog.is_showing:
            return
        if not original_path:
            return

        try:
            pixmap = load_full_pixmap(original_path)

            if pixmap.isNull():
                print(f"Error cargando pixmap para vista previa: {original_path}")
                return

            # Lanzar el diálogo
            preview_dialog = ImagePreviewDialog(pixmap, self)
            preview_dialog.show_with_animation()

        except Exception as e:
            print(f"Error al cargar vista previa (Doble Clic): {e}")

    @Slot()
    def _handle_photo_date_changed(self, photo_path: str, new_year: str, new_month: str):
        self._set_status("Metadatos de foto cambiados. Reconstruyendo vista...")
        path_found_and_removed = False
        for year, months in self.photos_by_year_month.items():
            for month, photos in months.items():
                if photo_path in photos:
                    photos.remove(photo_path)
                    path_found_and_removed = True
                    if not photos:
                        del self.photos_by_year_month[year][month]
                    if not self.photos_by_year_month[year]:
                        del self.photos_by_year_month[year]
                    break
            if path_found_and_removed:
                break
        if new_year not in self.photos_by_year_month:
            self.photos_by_year_month[new_year] = {}
        if new_month not in self.photos_by_year_month[new_year]:
            self.photos_by_year_month[new_year][new_month] = []
        self.photos_by_year_month[new_year][new_month].append(photo_path)
        self._display_photos()

    @Slot(str)
    def _open_video_player(self, video_path):
        """
        Abre el archivo de vídeo dado con el reproductor por defecto del sistema.
        """
        try:
            file_url = QUrl.fromLocalFile(video_path)
            if not QDesktopServices.openUrl(file_url):
                self._set_status(f"Error: No se pudo abrir {video_path}. ¿Hay un reproductor de vídeo configurado?")
            else:
                self._set_status(f"Abriendo {Path(video_path).name}...")
        except Exception as e:
            print(f"Error al intentar abrir el vídeo: {e}")
            self._set_status(f"Error: {e}")

    def _reflow_faces(self):
        """
        Reorganiza visualmente todas las caras para ajustarse al ancho actual de la ventana.
        Corrige la 'columna vertical' creada durante la precarga oculta.
        """
        # 1. Calcular cuántas columnas caben REALMENTE ahora
        viewport_width = self.face_scroll_area.viewport().width() - 30
        if viewport_width <= 0: return

        new_num_cols = max(1, viewport_width // 110)

        # 2. Extraer todos los widgets de caras existentes
        faces = []
        # Usamos un bucle para sacar todo del layout limpiamente
        while self.unknown_faces_layout.count() > 0:
            item = self.unknown_faces_layout.takeAt(0)
            w = item.widget()
            if w:
                # Solo guardamos si es una cara válida (evitamos etiquetas de error antiguas)
                if isinstance(w, CircularFaceLabel) or w.property("face_id"):
                    faces.append(w)
                else:
                    w.deleteLater() # Borrar mensajes viejos tipo "Cargando..."

        # 3. Volver a insertarlos en el orden correcto (Izquierda -> Derecha)
        for i, face_widget in enumerate(faces):
            row = i // new_num_cols
            col = i % new_num_cols
            self.unknown_faces_layout.addWidget(face_widget, row, col, Qt.AlignTop)

        # 4. Actualizar el contador global para que las NUEVAS caras sigan desde aquí
        self.current_face_count = len(faces)

    @Slot(int)
    def _on_tab_changed(self, index):
        # Prioridad a la pestaña nueva: se descartan las cargas pendientes de la anterior
        self._cancel_pending_loads()
        tab_name = self.tab_widget.tabText(index)

        if tab_name == "Fotos":
            QTimer.singleShot(0, self._load_main_visible_thumbnails)

        elif tab_name == "Vídeos":
            QTimer.singleShot(0, self._load_visible_video_thumbnails)

        elif tab_name == "Personas":
            self._set_status("Mostrando caras...")

            if self.face_loading_label:
                self.face_loading_label.deleteLater()
                self.face_loading_label = None

            # --- CORRECCIÓN: REORGANIZAR REJILLA ---
            # Arregla el desorden causado por la precarga en segundo plano
            self._reflow_faces()
            # ---------------------------------------

            current_item = self.people_tree_widget.currentItem()
            if current_item and current_item.data(0, Qt.UserRole) == -2:
                 pass
            else:
                 self._load_existing_faces_async()

            # Reintentar lo que se canceló al salir de la pestaña
            if self.left_people_stack.currentIndex() == 1:
                QTimer.singleShot(0, self._load_person_visible_thumbnails)
            else:
                self._reload_pending_faces()

            if self.face_scan_thread and self.face_scan_thread.isRunning():
                 self._set_status("Mostrando caras. Escaneo sigue en segundo plano...")

        elif tab_name == "Caja Fuerte":
            if hasattr(self, 'unlocked_widget') and self.unlocked_widget.isVisible():
                self._load_safe_content()

        elif tab_name == "Nube":
            QTimer.singleShot(100, self._load_visible_cloud_thumbnails)

    def _cancel_pending_loads(self):
        """
        Vacía la cola de cargas en segundo plano y deja lo cancelado marcado
        para reintentarlo. Las cargas que ya estaban en marcha terminan igual;
        si alguna se repite, el resultado es el mismo.
        """
        self.threadpool.clear()

        list_items = (list(self.photo_list_widget_items.values())
                      + list(self.video_list_widget_items.values())
                      + list(self.cloud_list_widget_items.values()))
        for item in list_items:
            try:
                if item.data(Qt.UserRole + 1) == "loading":
                    item.setData(Qt.UserRole + 1, "not_loaded")
            except RuntimeError:
                pass  # Item ya destruido al redibujar

        person_widget = self.person_photo_scroll_area.widget()
        if person_widget:
            for label in person_widget.findChildren(ZoomableClickableLabel):
                if label.property("original_path") and label.property("loaded") is None:
                    label.setProperty("loaded", False)

    def _reload_pending_faces(self):
        """Vuelve a lanzar la carga de las caras que se quedaron sin imagen."""
        for i in range(self.unknown_faces_layout.count()):
            widget = self.unknown_faces_layout.itemAt(i).widget()
            if not widget or widget.property("face_id") is None:
                continue
            if widget.property("face_loaded") or widget.property("face_failed"):
                continue
            source_path = widget.property("source_path")
            location = widget.property("location")
            if source_path and location:
                self.threadpool.start(FaceLoader(
                    self.face_loader_signals, widget.property("face_id"), source_path, location))

    def _load_people_list(self):
        self.people_tree_widget.clear()
        unknown_item = QTreeWidgetItem(self.people_tree_widget, ["Caras Sin Asignar"])
        unknown_item.setData(0, Qt.UserRole, -1)
        deleted_item = QTreeWidgetItem(self.people_tree_widget, ["Caras Eliminadas"])
        deleted_item.setData(0, Qt.UserRole, -2)
        people = self.db.get_all_people()
        if people:
            people_root_item = QTreeWidgetItem(self.people_tree_widget, ["Personas"])
            for person_row in people:
                person_id = person_row['id']
                person_name = person_row['name']
                person_item = QTreeWidgetItem(people_root_item, [person_name])
                person_item.setData(0, Qt.UserRole, person_id)
            people_root_item.setExpanded(True)
        self.people_tree_widget.setCurrentItem(unknown_item)

    def _populate_face_grid_async(self, face_list: list, is_deleted_view: bool = False, append: bool = False):
        """Rellena la rejilla de caras de forma robusta e incremental."""

        if not append:
            while self.unknown_faces_layout.count() > 0:
                item = self.unknown_faces_layout.takeAt(0)
                if item.widget(): item.widget().deleteLater()
            self.current_face_count = 0

            if not face_list:
                placeholder = QLabel("No se han encontrado caras.")
                placeholder.setAlignment(Qt.AlignCenter)
                self.unknown_faces_layout.addWidget(placeholder, 0, 0, Qt.AlignCenter)
                return

        if append and not face_list:
            return

        if self.unknown_faces_layout.count() == 1:
            item = self.unknown_faces_layout.itemAt(0)
            widget = item.widget()
            if isinstance(widget, QLabel) and not isinstance(widget, CircularFaceLabel):
                 widget.deleteLater()
                 self.current_face_count = 0

        # --- CORRECCIÓN DE GEOMETRÍA DE PRECARGA ---
        # Obtenemos el ancho real del área de scroll
        viewport_width = self.left_people_stack.width() - 30

        # Si la pestaña está oculta (precarga), el ancho suele ser irrelevante (ej: 100px).
        # En ese caso, usamos el ancho de la ventana principal menos el panel lateral (aprox 280px)
        if viewport_width < 300:
            viewport_width = max(400, self.width() - 350)
        # -------------------------------------------

        num_cols = max(1, viewport_width // 110)
        start_index = self.unknown_faces_layout.count()

        for i, face_row in enumerate(face_list):
            face_id = face_row['id']

            face_widget = CircularFaceLabel(QPixmap())
            face_widget.setText("Cargando...")
            face_widget.setStyleSheet("color: gray; font-size: 10px;")

            face_widget.setProperty("face_id", face_id)
            face_widget.setProperty("is_deleted_view", is_deleted_view)
            face_widget.setProperty("source_path", face_row['filepath'])
            face_widget.setProperty("location", face_row['location'])
            face_widget.rightClicked.connect(self._on_face_right_clicked)
            face_widget.clicked.connect(self._on_face_clicked)

            current_idx = start_index + i
            row = current_idx // num_cols
            col = current_idx % num_cols

            self.unknown_faces_layout.addWidget(face_widget, row, col, Qt.AlignTop)

            loader = FaceLoader(
                self.face_loader_signals,
                face_id,
                face_row['filepath'],
                face_row['location']
            )
            self.threadpool.start(loader)

        self.current_face_count = start_index + len(face_list)

    def _load_existing_faces_async(self):
        """Carga caras nuevas Y limpia las que ya no deben estar (Sincronización)."""
        self.unknown_faces_group.setTitle("Caras Sin Asignar")
        self.cluster_faces_button.setEnabled(True)
        self.show_deleted_faces_button.setEnabled(True)

        # 1. Obtener de la DB qué caras deberían estar realmente aquí
        all_unknown_faces = self.db.get_unknown_faces()
        # Creamos un set de IDs válidos para búsqueda rápida
        valid_db_ids = {f['id'] for f in all_unknown_faces}

        # 2. LIMPIEZA: Revisar qué hay en pantalla y borrar lo que sobra
        # (Esto elimina las caras que acabas de borrar o las de la vista anterior)
        existing_ids_on_ui = set()
        count_widgets = self.unknown_faces_layout.count()

        # Iteramos hacia atrás para poder borrar sin romper el índice
        for i in range(count_widgets - 1, -1, -1):
            item = self.unknown_faces_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()

                # ¿Es un widget de cara?
                fid = widget.property("face_id")

                if fid is not None:
                    # Si la cara en pantalla NO está en la lista válida de la DB
                    if fid not in valid_db_ids:
                        widget.hide()          # Ocultar visualmente ya
                        widget.setParent(None) # Desvincular del layout
                        widget.deleteLater()   # Borrar de memoria
                    else:
                        # Si es válida, la guardamos para no volver a cargarla
                        existing_ids_on_ui.add(fid)

                # Limpiar mensajes antiguos de "No se han encontrado caras" si ahora hay datos
                elif isinstance(widget, QLabel) and valid_db_ids and "No se han encontrado" in widget.text():
                     widget.deleteLater()

        # 3. AÑADIR: Cargar solo las que faltan
        new_faces_to_add = [f for f in all_unknown_faces if f['id'] not in existing_ids_on_ui]

        # Si hay nuevas, las añadimos (append=True porque ya limpiamos nosotros)
        if new_faces_to_add:
            self._populate_face_grid_async(new_faces_to_add, is_deleted_view=False, append=True)

        # Si la DB está vacía y la UI también, mostrar mensaje de vacío
        elif not valid_db_ids and self.unknown_faces_layout.count() == 0:
             self._populate_face_grid_async([], is_deleted_view=False, append=False)

    @Slot()
    def _on_face_clicked(self):
        sender_widget = self.sender()
        if not sender_widget:
            return
        is_deleted_view = sender_widget.property("is_deleted_view")
        face_id = sender_widget.property("face_id")
        photo_path = sender_widget.property("photo_path")
        if not face_id or not photo_path:
            print("Clic en una cara que aún no tiene datos (cargando).")
            return
        self._set_status(f"Etiquetando Cara ID: {face_id}...")
        dialog = FaceClusterDialog(
            self.db,
            self.threadpool,
            [face_id],
            self
        )
        result = dialog.exec()
        if result == QDialog.Accepted:
            self._set_status("Cara etiquetada. Refrescando...")
            self._load_people_list()
            if is_deleted_view:
                self._show_deleted_faces()
            else:
                self._load_existing_faces_async()
        elif result == FaceClusterDialog.DeleteRole:
            self._set_status("Cara eliminada. Refrescando...")
            if is_deleted_view:
                self._show_deleted_faces()
            else:
                self._load_existing_faces_async()
        else:
            self._set_status("Etiquetado cancelado.")

    @Slot(QPoint)
    def _on_face_right_clicked(self, pos):
        sender_widget = self.sender()
        if not sender_widget:
            return
        face_id = sender_widget.property("face_id")
        is_deleted_view = sender_widget.property("is_deleted_view")
        menu = QMenu(self)
        if is_deleted_view:
            restore_action = menu.addAction("Restaurar cara")
            restore_action.triggered.connect(lambda: self._restore_face(face_id, sender_widget))
        else:
            delete_action = menu.addAction("Eliminar cara reconocida")
            delete_action.triggered.connect(lambda: self._delete_face(face_id, sender_widget))
        menu.exec(pos)

    def _delete_face(self, face_id: int, widget: QWidget):
        # 1. Borrar en DB
        self.db.soft_delete_face(face_id)

        # 2. Borrar visualmente INMEDIATAMENTE
        widget.hide()          # Ocultar
        widget.setParent(None) # Sacar del layout
        widget.deleteLater()   # Programar destrucción memoria

        self._set_status(f"Cara ID {face_id} eliminada.")

        # 3. Recargar (la cara borrada ya no se vuelve a pintar)
        self._load_existing_faces_async()

    def _restore_face(self, face_id: int, widget: QWidget):
        self.db.restore_face(face_id)
        widget.deleteLater()
        self._set_status(f"Cara ID {face_id} restaurada.")
        self._show_deleted_faces()

    @Slot()
    def _show_deleted_faces(self):
        self.left_people_stack.setCurrentIndex(0)
        self.unknown_faces_group.setTitle("Caras Eliminadas")
        self.cluster_faces_button.setEnabled(False)
        self.show_deleted_faces_button.setEnabled(False)
        deleted_faces = self.db.get_deleted_faces()
        self._populate_face_grid_async(deleted_faces, is_deleted_view=True)
        self._set_status(f"Mostrando {len(deleted_faces)} caras eliminadas.")

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _on_person_selected(self, current_item: QTreeWidgetItem, previous_item: QTreeWidgetItem):
        if not current_item:
            return
        person_id = current_item.data(0, Qt.UserRole)
        if person_id == -1:
            self.left_people_stack.setCurrentIndex(0)
            self._load_existing_faces_async()
        elif person_id == -2:
            self.left_people_stack.setCurrentIndex(0)
            self._show_deleted_faces()
        elif person_id >= 0:
            self.left_people_stack.setCurrentIndex(1)
            person_name = current_item.text(0)
            self._load_photos_for_person(person_id, person_name)

    @Slot(int)
    def _update_face_scan_percentage(self, percentage):
        if not self.face_loading_label:
            self.face_loading_label = QLabel(f"Buscando caras de personas... {percentage}%")
            self.face_loading_label.setAlignment(Qt.AlignCenter)
            self.face_loading_label.setStyleSheet("font-size: 14pt;")
            self.face_container_layout.insertWidget(1, self.face_loading_label, 0, Qt.AlignCenter)
        else:
            self.face_loading_label.setText(f"Buscando caras de personas... {percentage}%")

    @Slot(int, str, str)
    def _handle_face_found(self, face_id: int, photo_path: str, location_str: str):
        """
        Se llama cada vez que el escáner encuentra una cara nueva.
        CORRECCIÓN: Filtra por la vista activa para no "ensuciar" la vista de Eliminadas.
        """
        # 1. Filtro de Pestaña: Si no estamos en Personas, no hacer nada (ahorra CPU)
        if self.tab_widget.currentWidget() != self.personas_tab_widget:
            return

        # --- 2. NUEVO FILTRO DE VISTA ---
        # Verificar qué opción del árbol está seleccionada.
        # ID -1 = Caras Sin Asignar.
        # ID -2 = Caras Eliminadas.
        # ID >= 0 = Persona Específica.
        current_item = self.people_tree_widget.currentItem()

        # Si no hay selección o NO estamos en "Caras Sin Asignar", ignoramos el evento visual.
        # La cara se guarda en la BD igualmente, y aparecerá cuando vuelvas a la sección correcta.
        if not current_item or current_item.data(0, Qt.UserRole) != -1:
            return

        face_widget = CircularFaceLabel(QPixmap())
        face_widget.setText("...")
        face_widget.setStyleSheet("background-color: #333333; border-radius: 50px; color: white;")

        face_widget.setProperty("face_id", face_id)
        face_widget.setProperty("photo_path", photo_path)
        face_widget.setProperty("is_deleted_view", False)
        face_widget.setProperty("source_path", photo_path)
        face_widget.setProperty("location", location_str)

        face_widget.clicked.connect(self._on_face_clicked)
        face_widget.rightClicked.connect(self._on_face_right_clicked)

        # Corrección de Geometría (fallback de ancho)
        viewport_width = self.face_scroll_area.viewport().width() - 30
        if viewport_width < 300:
             viewport_width = max(400, self.width() - 350)

        num_cols = max(1, viewport_width // 110)

        row = self.current_face_count // num_cols
        col = self.current_face_count % num_cols

        self.unknown_faces_layout.addWidget(face_widget, row, col, Qt.AlignTop)

        self.current_face_count += 1

        loader = FaceLoader(
            self.face_loader_signals,
            face_id,
            photo_path,
            location_str
        )
        self.threadpool.start(loader)

    @Slot()
    def _handle_scan_finished(self):
        if self.face_loading_label:
            self.face_loading_label.deleteLater()
            self.face_loading_label = None
        if self.current_face_count == 0:
            placeholder = QLabel("No se han encontrado caras.")
            placeholder.setAlignment(Qt.AlignCenter)
            self.unknown_faces_layout.addWidget(placeholder, 0, 0, Qt.AlignCenter)

    @Slot()
    def _on_scan_thread_finished(self):
        """Slot de limpieza para el hilo de FOTOS."""
        if self.photo_thread:
            self.photo_thread.deleteLater()
        self.photo_thread = None
        self.photo_worker = None

    @Slot()
    def _on_video_scan_thread_finished(self):
        """Slot de limpieza para el hilo de VÍDEOS."""
        if self.video_thread:
            self.video_thread.deleteLater()
        self.video_thread = None
        self.video_worker = None

    @Slot()
    def _on_face_scan_thread_finished(self):
        self.face_scan_thread = None
        self.face_scan_worker = None

    @Slot(int, QImage, str)
    def _handle_face_loaded(self, face_id: int, image: QImage, photo_path: str):
        pixmap = QPixmap.fromImage(image)  # Conversión en el hilo de la UI
        placeholder = None
        for i in range(self.unknown_faces_layout.count()):
            widget = self.unknown_faces_layout.itemAt(i).widget()
            if widget and widget.property("face_id") == face_id:
                placeholder = widget
                break
        if placeholder:
            placeholder.setPixmap(pixmap)
            placeholder.setText("")
            placeholder.setProperty("photo_path", photo_path)
            placeholder.setProperty("face_loaded", True)
        else:
            if self.unknown_faces_group.title() != "Caras Sin Asignar":
                return
            face_widget = CircularFaceLabel(pixmap)
            face_widget.setProperty("face_id", face_id)
            face_widget.setProperty("photo_path", photo_path)
            face_widget.setProperty("face_loaded", True)
            face_widget.setProperty("is_deleted_view", False)
            face_widget.clicked.connect(self._on_face_clicked)
            face_widget.rightClicked.connect(self._on_face_right_clicked)
            num_cols = max(1, (self.face_scroll_area.viewport().width() - 30) // 110)
            row = self.current_face_count // num_cols
            col = self.current_face_count % num_cols
            self.unknown_faces_layout.addWidget(face_widget, row, col, Qt.AlignTop)
            self.current_face_count += 1

    @Slot(int)
    def _handle_face_load_failed(self, face_id: int):
        placeholder = None
        for i in range(self.unknown_faces_layout.count()):
            widget = self.unknown_faces_layout.itemAt(i).widget()
            if widget and widget.property("face_id") == face_id:
                placeholder = widget
                break
        if placeholder:
            placeholder.setText("Error")
            placeholder.setProperty("face_failed", True)

    # Tiempo máximo de espera al cerrar para que las tareas en curso terminen
    SHUTDOWN_TIMEOUT_S = 15

    def _retire_thread(self, thread, worker=None):
        """
        Guarda la referencia de un hilo sustituido que aún puede estar en marcha.
        Si Python la soltara, Qt destruiría el QThread mientras se ejecuta y la
        app abortaría ("QThread: Destroyed while thread is still running").
        """
        self._retired_threads = [(t, w) for t, w in self._retired_threads if self._is_thread_running(t)]
        if self._is_thread_running(thread):
            self._retired_threads.append((thread, worker))

    def _background_tasks(self):
        """Pares (hilo, worker) de las tareas en segundo plano que pueden estar activas."""
        tasks = [
            (self.photo_thread, self.photo_worker),
            (self.video_thread, self.video_worker),
            (self.face_scan_thread, self.face_scan_worker),
            (self.drive_scan_thread, self.drive_scan_worker),
            (getattr(self, 'safe_thread', None), getattr(self, 'safe_worker', None)),
            (getattr(self, 'dup_thread', None), getattr(self, 'dup_worker', None)),
            (getattr(self, 'drive_login_thread', None), None),
        ]
        return tasks + list(self._retired_threads)

    @staticmethod
    def _is_thread_running(thread):
        try:
            return thread is not None and thread.isRunning()
        except RuntimeError:
            return False  # El objeto C++ ya fue destruido (deleteLater)

    def closeEvent(self, event):
        """
        Cierra de forma segura: pide a cada tarea que se detenga y espera a que
        lo haga. Nunca usa QThread.terminate(), que puede matar un hilo a mitad
        de una escritura en SQLite o con el GIL de Python tomado.
        """
        print("Cerrando aplicación... Por favor, espere.")
        self._set_status("Cerrando: esperando a que terminen las tareas en curso...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()

        # 1. Guardar configuración
        try:
            self._save_photo_splitter_state()
            self._save_video_splitter_state()
            config_manager.set_thumbnail_size(self.current_thumbnail_size)
        except Exception as e:
            print(f"Error guardando configuración al cerrar: {e}")

        # 2. Parar vigilante y descartar miniaturas pendientes
        if self.file_watcher:
            self.file_watcher.stop()
        self.threadpool.clear()
        self.drive_folder_pool.clear()

        # 3. Pedir a todas las tareas que se detengan (parada cooperativa)
        running = []
        for thread, worker in self._background_tasks():
            if not self._is_thread_running(thread):
                continue
            try:
                if hasattr(worker, 'stop'):
                    worker.stop()           # Escáner de caras: cancela la cola de IA
                elif worker is not None:
                    worker.is_running = False
            except RuntimeError:
                pass
            thread.quit()  # Sale del bucle de eventos del hilo en cuanto termine run()
            running.append(thread)

        # 4. Esperar a que terminen (como mucho SHUTDOWN_TIMEOUT_S en total)
        deadline = time.monotonic() + self.SHUTDOWN_TIMEOUT_S
        stuck = []
        login_thread = getattr(self, 'drive_login_thread', None)
        for thread in running:
            if thread is login_thread:
                # Bloqueado esperando al navegador: no se puede detener, no esperamos
                stuck.append(thread)
                continue
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            try:
                if not thread.wait(remaining_ms):
                    stuck.append(thread)
            except RuntimeError:
                pass
        pool_done = True
        for pool in (self.threadpool, self.cluster_pool, self.safe_pool, self.drive_folder_pool):
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            pool_done = pool.waitForDone(remaining_ms) and pool_done

        QApplication.restoreOverrideCursor()

        if stuck or not pool_done:
            # Una tarea sigue bloqueada (p. ej. un disco de red colgado o el
            # navegador del login de Google abierto). Matar solo ese hilo puede
            # dejar el proceso en un estado inconsistente; terminar el proceso
            # entero es seguro para SQLite: las transacciones son atómicas.
            print(f"⚠️ {len(stuck)} tarea(s) no respondieron a tiempo. Saliendo igualmente.")
            for conn in (self.db.conn, self.db.meta_conn):
                try:
                    if conn: conn.close()
                except Exception:
                    pass
            sys.stdout.flush()
            os._exit(0)

        print("Limpieza finalizada. Adiós.")
        event.accept()

    def keyPressEvent(self, event: QKeyEvent):
        """Maneja los atajos de teclado para el zoom."""

        # 1. Comprobar si Ctrl está presionado
        if event.modifiers() == Qt.ControlModifier:
            new_size = self.current_thumbnail_size

            # 2. Comprobar Ctrl + '+' (o '=')
            if event.key() == Qt.Key_Plus or event.key() == Qt.Key_Equal:
                new_size = min(self.MAX_THUMB_SIZE, self.current_thumbnail_size + self.THUMB_SIZE_STEP)

            # 3. Comprobar Ctrl + '-'
            elif event.key() == Qt.Key_Minus:
                new_size = max(self.MIN_THUMB_SIZE, self.current_thumbnail_size - self.THUMB_SIZE_STEP)

            else:
                super().keyPressEvent(event)
                return

            # 4. Si el tamaño ha cambiado, aplicarlo y guardarlo
            if new_size != self.current_thumbnail_size:
                self.current_thumbnail_size = new_size
                config_manager.set_thumbnail_size(new_size)

                # 5. Aplicar a las listas existentes (sin reconstruir la galería)
                self._apply_thumbnail_size()

            event.accept() # Marcar el evento como manejado

        else:
            # Si no es Ctrl, pasar el evento
            super().keyPressEvent(event)

    @Slot()
    def _start_clustering(self):
        self.cluster_faces_button.setText("Agrupando...")
        self.cluster_faces_button.setEnabled(False)
        self._set_status("Agrupando caras parecidas...")
        worker = ClusterWorker(self.cluster_signals, self.db.db_path)
        self.cluster_pool.start(worker)

    @Slot(list)
    def _handle_clusters_found(self, clusters: list):
        if not clusters:
            self._set_status("No se encontraron grupos de caras parecidas.")
            return
        self.cluster_queue = clusters
        self._set_status(f"¡Encontrados {len(self.cluster_queue)} grupos de caras parecidas!")
        self._process_cluster_queue()

    @Slot()
    def _handle_clustering_finished(self):
        self.cluster_faces_button.setText("Agrupar caras parecidas")
        self.cluster_faces_button.setEnabled(True)
        if not self.cluster_queue:
             self._set_status("Agrupación terminada. No se encontraron grupos de caras parecidas.")

    @Slot()
    def _process_cluster_queue(self):
        if not self.cluster_queue:
            self._set_status("¡Etiquetado de grupos completado!")
            self._load_existing_faces_async()
            return
        next_cluster_ids = self.cluster_queue.pop(0)
        self._set_status(f"Etiquetando grupo de caras... quedan {len(self.cluster_queue)} grupos.")
        dialog = FaceClusterDialog(
            self.db,
            self.threadpool,
            next_cluster_ids,
            self
        )
        result = dialog.exec()
        if result == QDialog.Accepted:
            print(f"Grupo guardado. Quedan {len(self.cluster_queue)}.")
            self._load_people_list()
        elif result == FaceClusterDialog.SkipRole:
            print(f"Grupo omitido. Quedan {len(self.cluster_queue)}.")
        elif result == FaceClusterDialog.DeleteRole:
            print(f"Grupo eliminado. Quedan {len(self.cluster_queue)}.")
        else:
            print("Cancelado el etiquetado de grupos.")
            self.cluster_queue = []
            self._set_status("Etiquetado cancelado.")
            self._load_existing_faces_async()
            return
        QTimer.singleShot(100, self._process_cluster_queue)

    def _load_photos_for_person(self, person_id: int, person_name: str):
        self._set_status(f"Mostrando caras de {person_name}.")
        self.cluster_faces_button.setEnabled(False)
        self.show_deleted_faces_button.setEnabled(True)
        person_photos = self.db.get_faces_for_person(person_id)
        self._display_person_photos(person_photos, person_name)


    def _display_person_photos(self, photos_list: list, person_name: str):
        while self.person_photo_layout.count() > 0:
            item = self.person_photo_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        if not photos_list:
            placeholder = QLabel(f"No se encontraron fotos para {person_name}.")
            placeholder.setAlignment(Qt.AlignCenter)
            self.person_photo_layout.addWidget(placeholder)
            return
        photos_by_year_month = {}
        for row in photos_list:
            path, year, month = row['filepath'], row['year'], row['month']
            if year not in photos_by_year_month:
                photos_by_year_month[year] = {}
            if month not in photos_by_year_month[year]:
                photos_by_year_month[year][month] = []
            if path not in photos_by_year_month[year][month]:
                photos_by_year_month[year][month].append(path)
        viewport_width = self.left_people_stack.width() - 30

        # --- Modificación de Zoom para Pestaña Personas ---
        # Usar el zoom, pero no cambiar el TAMAÑO del label
        thumb_width = THUMBNAIL_SIZE[0] + 10
        num_cols = max(1, viewport_width // thumb_width)

        sorted_years = sort_years(photos_by_year_month.keys())
        for year in sorted_years:
            sorted_months = sort_months(photos_by_year_month[year].keys(), reverse=True)
            for month in sorted_months:
                photos = photos_by_year_month[year][month]
                if not photos: continue
                try:
                    month_name = datetime.datetime.strptime(month, "%m").strftime("%B").capitalize()
                except ValueError:
                    month_name = "Mes Desconocido"
                group_label = QLabel(f"{month_name} {year}" if _is_known_year(year) else f"{month_name} (sin fecha)")
                group_label.setStyleSheet("font-size: 14pt; font-weight: bold; margin-top: 10px;")
                self.person_photo_layout.addWidget(group_label)
                photo_grid_widget = QWidget()
                photo_grid_layout = QGridLayout(photo_grid_widget)
                photo_grid_layout.setSpacing(5)
                for i, photo_path in enumerate(photos):
                    photo_label = ZoomableClickableLabel(photo_path)
                    photo_label.is_thumbnail_view = True
                    photo_label.setFixedSize(THUMBNAIL_SIZE[0] + 10, THUMBNAIL_SIZE[1] + 25)
                    photo_label.setToolTip(photo_path)
                    photo_label.setAlignment(Qt.AlignCenter)
                    photo_label.setText(Path(photo_path).name.split('.')[0] + "\nCargando...")
                    photo_label.setProperty("original_path", photo_path)
                    photo_label.setProperty("loaded", False)
                    photo_label.doubleClickedPath.connect(self._open_photo_detail)
                    row, col = i // num_cols, i % num_cols
                    photo_grid_layout.addWidget(photo_label, row, col)
                self.person_photo_layout.addWidget(photo_grid_widget)
        self.person_photo_layout.addStretch(1)
        QTimer.singleShot(100, self._load_person_visible_thumbnails)

    def _show_hidden_photos_view(self):
        self._show_hidden_view(is_video=False)

    def _show_hidden_videos_view(self):
        self._show_hidden_view(is_video=True)

    def _show_hidden_view(self, is_video):
        """Muestra solo las fotos o los vídeos ocultos en el panel principal."""
        g = self._gallery(is_video)
        self._set_status(f"Cargando {g.hidden_kind}...")

        while g.container.count() > 0:
            item = g.container.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        # Limpiar referencias a los widgets antiguos (evita RuntimeError al hacer scroll)
        setattr(self, g.groups_attr, {})
        g.items.clear()

        title = QLabel(g.hidden_title)
        title.setStyleSheet("font-size: 18pt; color: red; font-weight: bold; margin: 20px;")
        g.container.addWidget(title)

        hidden_paths = [p for p in g.get_hidden() if os.path.exists(p)]
        if not hidden_paths:
            g.container.addWidget(QLabel(f"No hay {g.hidden_kind}."))
            g.container.addStretch(1)
            return

        list_widget = self._new_gallery_list(is_video, hidden_view=True)
        for path in hidden_paths:
            self._add_gallery_item(list_widget, path, g.items)
        g.container.addWidget(list_widget)
        g.container.addStretch(1)
        QTimer.singleShot(100, lambda: self._load_visible_gallery_thumbnails(is_video))

    # ==========================================================
    # PESTAÑA AYUDA
    # ==========================================================

    HELP_ACCENT = "#3daee9"

    # (icono, pestaña, descripción en HTML)
    HELP_TABS = [
        ("📷", "Fotos",
         "Tu biblioteca ordenada por <b>años y meses</b>; el árbol de la derecha salta a cada fecha. "
         "<b>Ver árbol de directorios</b> filtra por carpeta y <b>Buscar Duplicados</b> encuentra las "
         "copias repetidas para que te quedes con la mejor. Las fotos nuevas que copies a tu carpeta "
         "aparecen solas a los pocos segundos."),
        ("🎥", "Vídeos",
         "Igual que Fotos, pero para tus vídeos, con su miniatura. Con <b>doble clic</b> se "
         "reproducen en el reproductor de tu sistema."),
        ("👥", "Personas",
         "Las caras se detectan solas en segundo plano. <b>Haz clic en una cara</b> para asignarla a "
         "una persona o crear una nueva, y usa <b>Agrupar caras parecidas</b> para etiquetar muchas de "
         "una vez. Las caras mal detectadas se eliminan con clic derecho y se recuperan desde "
         "<b>Caras Eliminadas</b>."),
        ("🔒", "Caja Fuerte",
         "Guarda fotos y vídeos <b>cifrados con AES-256</b> y los quita de la galería. Añádelos con "
         "clic derecho → <b>Añadir a Caja Fuerte</b>; para verlos, <b>Desbloquear</b>. "
         "<b>La contraseña no se puede recuperar</b>: si la olvidas, su contenido se pierde."),
        ("☁️", "Nube",
         "Explora las fotos de tu <b>Google Drive</b> por fechas y por carpetas sin descargarlas: "
         "solo se bajan las miniaturas que ves y la foto que abres. VisageVault solo tiene "
         "<b>permiso de lectura</b>: nunca modifica ni borra nada de tu Drive."),
    ]

    HELP_SHORTCUTS = [
        ("Ver una foto o reproducir un vídeo", "Doble clic"),
        ("Opciones de los elementos seleccionados", "Clic derecho"),
        ("Tamaño de las miniaturas", "Ctrl + / Ctrl −"),
        ("Zoom en el visor", "Rueda del ratón · doble clic para ajustar"),
        ("Mover la foto ampliada", "Arrastrar"),
        ("Cerrar el visor", "Esc · clic fuera de la foto"),
        ("Selección múltiple", "Ctrl + clic"),
        ("Selección de un rango", "Mayús + clic"),
        ("Selección por arrastre", "Arrastrar sobre el fondo"),
    ]

    HELP_CONTEXT_MENU = [
        ("Cambiar Fecha", "Reasigna la fecha; actualiza la biblioteca y los metadatos del archivo."),
        ("Corregir Ojos Rojos", "Los detecta y corrige en las fotos seleccionadas (modifica el original)."),
        ("Añadir a Caja Fuerte", "Cifra los archivos y los quita de la galería."),
        ("Ocultar de la vista", "Los archiva en «Ocultas» sin borrarlos del disco."),
        ("Mover a la papelera", "Los envía a la papelera del sistema, desde donde se pueden recuperar."),
    ]

    def _help_label(self, html, selectable=False):
        """Texto enriquecido de la Ayuda; los enlaces se abren con el navegador del sistema."""
        label = QLabel(html)
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        label.setOpenExternalLinks(False)
        label.linkActivated.connect(updater.open_url)
        flags = Qt.LinksAccessibleByMouse
        if selectable:
            flags |= Qt.TextSelectableByMouse
        label.setTextInteractionFlags(flags)
        return label

    def _help_section_title(self, text):
        label = QLabel(text)
        label.setStyleSheet(f"font-size: 14pt; font-weight: bold; color: {self.HELP_ACCENT};"
                            " padding-top: 14px;")
        return label

    def _help_card(self):
        """Recuadro con el color de fondo alternativo del tema (claro u oscuro)."""
        card = QFrame()
        card.setObjectName("helpCard")
        card.setStyleSheet("#helpCard { background: palette(alternate-base);"
                           " border: 1px solid palette(mid); border-radius: 8px; }")
        return card

    def _help_table(self, rows):
        """Tabla de dos columnas (acción, descripción) en HTML."""
        html = "<table width='100%' cellspacing='0' cellpadding='5'>"
        for i, (left, right) in enumerate(rows):
            border = "" if i == len(rows) - 1 else "border-bottom: 1px solid palette(mid);"
            html += (f"<tr><td width='34%' style='{border}'><b>{left}</b></td>"
                     f"<td style='{border}'>{right}</td></tr>")
        return html + "</table>"

    def _build_help_tab(self):
        """Pestaña Ayuda: qué hace cada pestaña, controles, datos, autor y versión."""
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(24, 20, 24, 24)
        column = QWidget()
        column.setMaximumWidth(920)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        outer.addStretch(1)
        outer.addWidget(column, 100)
        outer.addStretch(1)

        # --- Cabecera: logo, nombre, versión y actualizaciones ---
        header = QHBoxLayout()
        header.setSpacing(18)
        logo = QLabel()
        logo_path = resource_path("visagevault.png")
        if os.path.exists(logo_path):
            logo.setPixmap(QPixmap(logo_path).scaled(88, 88, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        header.addWidget(logo, 0, Qt.AlignTop)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("VisageVault")
        title.setStyleSheet("font-size: 24pt; font-weight: bold;")
        title_box.addWidget(title)
        version_text = "Compilación de desarrollo" if APP_VERSION == "dev" else f"Versión {APP_VERSION}"
        subtitle = QLabel(f"Tu gestor de recuerdos inteligente, privado y local · {version_text}")
        subtitle.setStyleSheet("color: gray;")
        subtitle.setWordWrap(True)
        title_box.addWidget(subtitle)

        updates_row = QHBoxLayout()
        updates_row.setContentsMargins(0, 8, 0, 0)
        btn_updates = QPushButton("🔄 Buscar actualizaciones")
        btn_updates.setCursor(Qt.PointingHandCursor)
        btn_updates.clicked.connect(lambda: self.check_updates_manual(btn_updates, self))
        updates_row.addWidget(btn_updates)
        auto_check = QCheckBox("Buscar al iniciar")
        auto_check.setChecked(config_manager.get_check_updates())
        auto_check.toggled.connect(config_manager.set_check_updates)
        updates_row.addWidget(auto_check)
        updates_row.addStretch(1)
        title_box.addLayout(updates_row)
        header.addLayout(title_box, 1)
        layout.addLayout(header)

        privacy = self._help_label(
            "🛡️ <b>Todo se procesa en tu ordenador.</b> El reconocimiento facial, las fechas y la caja "
            "fuerte no envían nada a internet. Solo la pestaña Nube se conecta, y únicamente a tu "
            "propio Google Drive.")
        privacy.setStyleSheet(f"padding: 10px; border-left: 4px solid {self.HELP_ACCENT};"
                              " background: palette(alternate-base);")
        layout.addSpacing(6)
        layout.addWidget(privacy)

        # --- Qué hay en cada pestaña ---
        layout.addWidget(self._help_section_title("Qué hay en cada pestaña"))
        grid = QGridLayout()
        grid.setSpacing(10)
        for i, (icon, name, text) in enumerate(self.HELP_TABS):
            card = self._help_card()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            heading = QLabel(f"{icon}  {name}")
            heading.setStyleSheet("font-size: 12pt; font-weight: bold; background: transparent;")
            card_layout.addWidget(heading)
            body = self._help_label(text)
            body.setStyleSheet("background: transparent;")
            card_layout.addWidget(body)
            card_layout.addStretch(1)
            # La última, si queda sola en su fila, ocupa todo el ancho
            span = 2 if i == len(self.HELP_TABS) - 1 and i % 2 == 0 else 1
            grid.addWidget(card, i // 2, i % 2, 1, span)
        layout.addLayout(grid)

        # --- Menú contextual y controles ---
        layout.addWidget(self._help_section_title("Clic derecho sobre fotos y vídeos"))
        layout.addWidget(self._help_label(self._help_table(self.HELP_CONTEXT_MENU)))
        layout.addWidget(self._help_section_title("Controles"))
        layout.addWidget(self._help_label(self._help_table(self.HELP_SHORTCUTS)))

        # --- Tus datos ---
        layout.addWidget(self._help_section_title("Tus datos"))
        data_html = (
            "Haz copia de seguridad de la carpeta de <b>datos</b>: contiene tus fechas, personas y la "
            "caja fuerte. Las demás se pueden borrar sin perder nada.<br>"
            + self._help_table([
                ("Datos", paths.data_dir()),
                ("Configuración", paths.config_dir()),
                ("Caché (miniaturas y caras)", paths.cache_dir()),
            ]))
        layout.addWidget(self._help_label(data_html, selectable=True))
        btn_data = QPushButton("📂 Abrir la carpeta de datos")
        btn_data.setCursor(Qt.PointingHandCursor)
        btn_data.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(paths.data_dir())))
        data_row = QHBoxLayout()
        data_row.addWidget(btn_data)
        data_row.addStretch(1)
        layout.addLayout(data_row)

        # --- Autor y contacto ---
        layout.addWidget(self._help_section_title("Autor y contacto"))
        author_card = self._help_card()
        author_layout = QHBoxLayout(author_card)
        author_layout.setContentsMargins(16, 14, 16, 14)
        author_layout.setSpacing(16)
        brand = QLabel()
        brand_path = resource_path("AnabasaSoft.png")
        if os.path.exists(brand_path):
            brand.setPixmap(QPixmap(brand_path).scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand.setStyleSheet("background: transparent;")
        author_layout.addWidget(brand, 0, Qt.AlignTop)
        a = f"style='color: {self.HELP_ACCENT}; text-decoration: none;'"
        author = self._help_label(
            "Desarrollado con ❤️ y mucho café por<br>"
            "<span style='font-size: 13pt;'><b>Daniel Serrano Armenta</b> (AnabasaSoft)</span><br><br>"
            f"📧 <a {a} href='mailto:anabasasoft@gmail.com'>anabasasoft@gmail.com</a><br>"
            f"🐙 <a {a} href='https://github.com/AnabasaSoft/VisageVault'>github.com/AnabasaSoft/VisageVault</a><br>"
            f"🌐 <a {a} href='https://danitxu79.github.io/'>danitxu79.github.io</a><br>"
            f"🐛 <a {a} href='https://github.com/AnabasaSoft/VisageVault/issues'>Informar de un error o "
            "proponer una mejora</a><br><br>"
            f"Si VisageVault te resulta útil, puedes darle una ⭐ en GitHub o "
            f"<a {a} href='https://www.buymeacoffee.com/danitxu'>invitarme a un café</a> ☕")
        author.setStyleSheet("background: transparent;")
        author_layout.addWidget(author, 1)
        layout.addWidget(author_card)

        # --- Licencia ---
        license_label = self._help_label(
            "VisageVault se distribuye con <b>doble licencia</b>: LGPLv3 para proyectos de código "
            "abierto y licencia comercial para software privativo (consulta al autor).")
        license_label.setStyleSheet("color: gray; font-size: 9pt; padding-top: 12px;")
        layout.addWidget(license_label)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        return scroll

    def _remove_red_eyes_for_selected(self, items):
        """Aplica la corrección de ojos rojos a los elementos seleccionados."""
        count = len(items)
        # Confirmación de seguridad
        confirm = QMessageBox.question(
            self,
            "Corrección de Ojos Rojos",
            f"Se intentarán corregir los ojos rojos en {count} foto(s).\n\n"
            "⚠️ Esto modificará el archivo original permanentemente.\n"
            "¿Deseas continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if confirm != QMessageBox.StandardButton.Yes:
            return

        processed = 0
        successes = 0

        paths_to_update = [item.data(Qt.UserRole) for item in items]
        total = len(paths_to_update)

        for i, path in enumerate(paths_to_update):
            self._set_status(f"Corrigiendo ojos rojos ({i+1}/{total}): {Path(path).name}...")
            QApplication.processEvents() # Para que la UI no se congele

            if self._remove_red_eye_from_image(path):
                successes += 1
                # La caché va por ruta: hay que borrarla para que se regenere
                self._invalidate_photo_caches(path)

            processed += 1

        self._set_status(f"Proceso finalizado. {successes} fotos corregidas de {processed}.")

        if successes > 0:
            # Redibujar para regenerar las miniaturas invalidadas
            self._display_photos()

    @Slot()
    def _on_gdrive_login_click(self):
        """Gestiona tanto Conectar como Desconectar."""

        # CASO 1: DESCONECTAR (LOGOUT)
        if self.is_drive_connected:
            self._perform_logout()
            return

        # CASO 2: CONECTAR (LOGIN)
        self.btn_gdrive.setEnabled(False)
        self.btn_gdrive.setText("Esperando navegador...")
        self._set_status("Abriendo navegador para inicio de sesión...")

        self._start_drive_login(silent=False)

    def _start_drive_login(self, silent):
        """Lanza la autenticación en un hilo (con o sin navegador)."""
        # Un reintento justo después de un fallo llega cuando el hilo anterior aún termina
        if self.drive_login_thread is not None:
            self._retire_thread(self.drive_login_thread, self.drive_login_worker)
        self.drive_login_thread = QThread()
        self.drive_login_worker = DriveLoginWorker(silent=silent)
        self.drive_login_worker.moveToThread(self.drive_login_thread)

        self.drive_login_thread.started.connect(self.drive_login_worker.run)
        self.drive_login_worker.login_success.connect(self._on_login_success_with_service)
        if silent:
            self.drive_login_worker.login_failed.connect(self._on_auto_login_failure)
        else:
            self.drive_login_worker.login_failed.connect(self._on_login_failure)

        self.drive_login_worker.finished.connect(self.drive_login_thread.quit)
        self.drive_login_worker.finished.connect(self.drive_login_worker.deleteLater)
        # Antes: lambda que ponía drive_login_thread a None. Si ya había un reintento en
        # marcha, borraba la referencia del hilo NUEVO, Python lo destruía y la app abortaba.
        self.drive_login_thread.finished.connect(self.drive_login_thread.deleteLater)

        self.drive_login_thread.start()

    def _perform_logout(self):
        """
        Cierra sesión y realiza un BORRADO TOTAL de datos locales, caché e interfaz.
        """
        # 1. LOGOUT LÓGICO (Token)
        auth = DriveAuthenticator()
        if auth.logout():
            self._set_status("Sesión cerrada. Iniciando limpieza profunda...")
        else:
            self._set_status("Desconectado. Limpiando datos...")

        # 2. PARAR CUALQUIER PROCESO DE FONDO
        self._stop_cloud_operations()

        # 3. BORRADO DE BASE DE DATOS
        try:
            # Intentamos usar el método dedicado si existe
            if hasattr(self.db, 'clear_drive_data'):
                self.db.clear_drive_data()
            else:
                # Fallback manual
                with self.db.conn:
                    self.db.conn.execute("DELETE FROM drive_photos")
            print("Base de datos de Drive vaciada.")
        except Exception as e:
            print(f"Error limpiando DB: {e}")

        # 4. BORRADO FÍSICO (CACHÉ DE DISCO)
        # Definimos las rutas exactas
        cache_snapshot = os.path.join(self.root_cache, "drive_snapshot_cache")
        cache_full = os.path.join(self.root_cache, "drive_cache")

        for folder_path in [cache_snapshot, cache_full]:
            if os.path.exists(folder_path):
                try:
                    # Borramos la carpeta ENTERA y su contenido
                    shutil.rmtree(folder_path)
                    # La volvemos a crear vacía inmediatamente para evitar errores futuros
                    os.makedirs(folder_path)
                    print(f"Caché purgado y regenerado: {folder_path}")
                except Exception as e:
                    print(f"Error purgado caché {folder_path}: {e}")

        # 5. LIMPIEZA DE MEMORIA (RAM)
        self.is_drive_connected = False
        self.drive_service = None
        self.drive_manager = None
        self.current_drive_folder_id = None
        self.drive_photos_by_date = {} # ¡VITAL! Vaciar el diccionario de fotos
        self.drive_loaded_ids = set()
        self.cloud_photo_count = 0

        # 6. LIMPIEZA VISUAL (INTERFAZ) - ELIMINACIÓN AGRESIVA

        # A) Limpiar el árbol de fechas lateral
        self.cloud_date_tree.clear()

        # B) Limpiar el panel de fotos (Layout)
        # Usamos un bucle while para asegurar que no queda NADA
        self.cloud_list_widget_items = {}
        while self.cloud_container_layout.count() > 0:
            item = self.cloud_container_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None) # Desvincular totalmente
                widget.deleteLater()   # Programar destrucción

        # C) Forzar repintado de la zona
        self.cloud_scroll_area.update()
        self.btn_show_tree.setVisible(False)
        self.btn_show_tree.setChecked(False)
        self.cloud_folder_panel.hide()
        self._reset_drive_tree()

        # 7. RESTAURAR ESTADO INICIAL DEL BOTÓN
        self.btn_gdrive.setText("Iniciar sesión con Google")
        self.btn_gdrive.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon))
        self.btn_gdrive.setStyleSheet("") # Quitar estilo verde
        self.btn_gdrive.setEnabled(True)

        self.btn_change_folder.setVisible(False)

        self._set_status("Desconectado. Todos los datos locales han sido eliminados.")

        # (Opcional) Mensaje emergente
        QMessageBox.information(self, "Desconectado", "Sesión cerrada y caché eliminado.")

    @Slot(object)
    def _on_login_success_with_service(self, service):
        """
        Recibe el objeto de conexión (service) desde el hilo de login
        y pasa el control a la función de éxito principal.
        """
        self.drive_service = service
        # Ahora llamamos a la función que activa la interfaz y cambia el botón
        self._on_login_success()
        # Mostrar el botón del árbol
        self.btn_show_tree.setVisible(True)

    @Slot()
    def _on_login_success(self):
        self._set_status("¡Conectado a Google Drive!")
        self.is_drive_connected = True

        # Actualizar botón para que ahora sirva para desconectar
        self.btn_gdrive.setText("Desconectar de Google")
        self.btn_gdrive.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton))
        self.btn_gdrive.setEnabled(True)
        self.btn_gdrive.setStyleSheet("background-color: #34a853; color: white; padding: 12px; font-weight: bold;")

        self.btn_change_folder.setVisible(True)
        self.btn_show_tree.setVisible(True)

        try:
            self.drive_manager = DriveManager()
            if getattr(self, 'drive_service', None):
                # Servicio ya obtenido en el hilo de login: no volver a leer el token aquí
                self.drive_manager.service = self.drive_service
            else:
                self.drive_manager.authenticate()

            folder_id = config_manager.get_drive_folder_id()

            if folder_id:
                self._set_status("Sincronizando carpeta guardada automáticamente...")
                # Lanzamos escaneo directo (ya optimizado)
                self._scan_drive_content(folder_id)
            else:
                self._after_splash(self._select_drive_folder)

        except Exception as e:
            print(f"Error post-login: {e}")
            self._set_status(f"Error inicializando Drive: {e}")
            # Si falla la inicialización, forzamos logout visual
            self._perform_logout()

    @Slot(str)
    def _on_login_failure(self, error_message=None):
        """Maneja el fallo en el login."""
        self.btn_gdrive.setEnabled(True)
        self.btn_gdrive.setText("Reintentar conexión")
        if error_message:
            self._set_status(f"Conexión fallida: {error_message}")
        else:
            self._set_status("Conexión fallida. Verifique sus credenciales.")

    def _select_drive_folder(self):
        """Abre el navegador de carpetas de Drive."""
        try:
            dialog = DriveFolderDialog(self.drive_manager, self, db=self.db)
            result = dialog.exec()

            if result == QDialog.Accepted:
                folder_id = dialog.selected_folder_id
                folder_name = dialog.selected_folder_name

                # 1. PARADA TOTAL: Frenar descargas antiguas
                self._stop_cloud_operations()

                # 2. LIMPIEZA VISUAL Y DE MEMORIA
                self.drive_photos_by_date = {}
                self.cloud_photo_count = 0
                self.cloud_date_tree.clear()
                # Limpiar widgets de fotos anteriores
                self.cloud_list_widget_items = {}
                while self.cloud_container_layout.count() > 0:
                    item = self.cloud_container_layout.takeAt(0)
                    if item.widget(): item.widget().deleteLater()

                # Añadir un loading visual temporal
                self.cloud_container_layout.addWidget(QLabel("Cargando nueva carpeta..."))

                # Guardar configuración
                config_manager.set_drive_folder_id(folder_id)

                # Actualizar referencia actual
                self.current_drive_folder_id = folder_id
                self.current_drive_folder_name = folder_name

                self.btn_change_folder.setVisible(True)
                self.btn_change_folder.setText(f"Carpeta: {folder_name} (Cambiar)")

                self._set_status(f"Cambiando a carpeta: {folder_name}...")

                # --- ACTUALIZAR EL ÁRBOL DE CARPETAS ---
                self._reset_drive_tree() # Borrar árbol viejo

                # Si el panel está visible, cargamos la nueva raíz inmediatamente
                if self.btn_show_tree.isChecked():
                    self._load_folder_tree_root()

                # 3. INICIAR NUEVO ESCANEO
                self._scan_drive_content(folder_id)

            dialog.deleteLater()

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Error al abrir navegador de Drive: {e}")

    def _load_drive_from_db(self, root_folder_id):
        """Carga solo las fotos que pertenecen a la carpeta seleccionada."""
        self._set_status("Cargando caché local...")

        db_photos = self.db.get_all_drive_photos(root_folder_id)

        if not db_photos:
            # Si está vacía, limpiamos todo por si acaso
            self.drive_photos_by_date = {}
            self.drive_loaded_ids = set()
            self.cloud_photo_count = 0
            self._display_cloud_photos() # Limpia la pantalla
            return

        formatted_photos = []
        for row in db_photos:
            formatted_photos.append({
                'id': row['id'],
                'name': row['name'],
                'createdTime': row['created_time'],
                'mimeType': row['mime_type'],
                'thumbnailLink': row['thumbnail_link'],
                'webContentLink': row['web_content_link']
            })

        self.drive_photos_by_date = {}
        self.drive_loaded_ids = set()
        self.cloud_photo_count = 0

        self._classify_drive_items_in_memory(formatted_photos)
        self._display_cloud_photos()
        self._set_status(f"Caché cargado: {self.cloud_photo_count} fotos.")

    def _classify_drive_items_in_memory(self, items):
        """Clasifica en el diccionario de fechas EVITANDO DUPLICADOS."""
        for f in items:
            file_id = f.get('id')

            # --- FILTRO ANTI-DUPLICADOS ---
            if file_id in self.drive_loaded_ids:
                continue # ¡Ya tenemos esta foto! La saltamos.

            # Si es nueva, la registramos
            self.drive_loaded_ids.add(file_id)
            # ------------------------------

            created_time = f.get('createdTime', '')
            year = "Sin Fecha"
            month = "00"
            if created_time:
                try:
                    dt = datetime.datetime.strptime(created_time[:10], "%Y-%m-%d")
                    year = str(dt.year)
                    month = f"{dt.month:02d}"
                except: pass

            if year not in self.drive_photos_by_date:
                self.drive_photos_by_date[year] = {}
            if month not in self.drive_photos_by_date[year]:
                self.drive_photos_by_date[year][month] = []

            self.drive_photos_by_date[year][month].append(f)
            self.cloud_photo_count += 1

    def _scan_drive_content(self, folder_id):
        """Inicia el escaneo de Drive."""
        self.current_drive_folder_id = folder_id

        # 1. Carga inicial de lo que ya tengamos (para que no se vea vacío)
        self._load_drive_from_db(folder_id)

        self._set_status("Iniciando indexación en la nube...")

        if self.drive_scan_thread is not None:
            self._retire_thread(self.drive_scan_thread, self.drive_scan_worker)
        self.drive_scan_thread = QThread()
        self.drive_scan_worker = DriveScanWorker(folder_id, self.db.db_path)
        self.drive_scan_worker.moveToThread(self.drive_scan_thread)

        self.set_drive_priority_low.connect(self.drive_scan_worker.set_slow_mode)

        self.drive_scan_thread.started.connect(self.drive_scan_worker.run)

        self.drive_scan_worker.progress.connect(self._set_status)
        self.drive_scan_worker.finished.connect(self._on_drive_scan_finished)

        self.drive_scan_worker.finished.connect(self.drive_scan_thread.quit)
        self.drive_scan_worker.finished.connect(self.drive_scan_worker.deleteLater)
        self.drive_scan_thread.finished.connect(self.drive_scan_thread.deleteLater)

        self.drive_scan_thread.start()

    @Slot(int)
    def _on_drive_scan_finished(self, total_count):
        """Se llama cuando termina el escaneo."""
        if total_count < 0:
            # Sesión caducada: el worker ya lo ha indicado en la barra de estado
            self.is_drive_connected = False
            self.btn_gdrive.setText("Reconectar con Google")
            self.btn_gdrive.setStyleSheet("")
            return
        self._set_status(f"Indexación completada ({total_count} nuevos). Recargando vista...")

        # Volver a cargar desde la BD local (ya redibuja la Nube) para mostrar lo nuevo
        self.cloud_scroll_area.setUpdatesEnabled(False)
        self._load_drive_from_db(self.current_drive_folder_id)
        self.cloud_scroll_area.setUpdatesEnabled(True)

        if self.cloud_photo_count == 0:
             QMessageBox.information(self, "Aviso", "No se encontraron imágenes en esa carpeta.")

        self._set_status(f"Listo. {self.cloud_photo_count} fotos disponibles.")

    def _display_cloud_photos(self):
        """Dibuja la interfaz de Nube (Usa ajuste de altura automático)."""

        while self.cloud_container_layout.count() > 0:
            item = self.cloud_container_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        self.cloud_date_tree.clear()
        self.cloud_group_widgets = {}
        self.cloud_list_widget_items = {}

        sorted_years = sort_years(self.drive_photos_by_date.keys())

        for year in sorted_years:
            year_item = QTreeWidgetItem(self.cloud_date_tree, [str(year)])

            year_label = QLabel(year_title(year))
            year_label.setStyleSheet("font-size: 16pt; font-weight: bold; margin-top: 20px; margin-bottom: 5px;")
            widgets_to_add_for_year = [year_label]
            self.cloud_group_widgets[str(year)] = year_label

            sorted_months = sort_months(self.drive_photos_by_date[year].keys(), reverse=True)

            for month in sorted_months:
                photos = self.drive_photos_by_date[year][month]
                if not photos: continue

                try: month_name = datetime.datetime.strptime(month, "%m").strftime("%B").capitalize()
                except: month_name = "Desconocido"

                month_item = QTreeWidgetItem(year_item, [f"{month_name} ({len(photos)})"])
                month_item.setData(0, Qt.UserRole, f"{year}-{month}")

                month_label = QLabel(month_name)
                month_label.setStyleSheet("font-size: 14pt; font-weight: bold; margin-top: 10px;")
                widgets_to_add_for_year.append(month_label)
                self.cloud_group_widgets[f"{year}-{month}"] = month_label

                # --- CONFIGURACIÓN LISTWIDGET ---
                list_widget = PreviewListWidget()
                list_widget.setMovement(QListWidget.Static)
                list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
                list_widget.setUniformItemSizes(False)
                list_widget.setViewMode(QListWidget.IconMode)
                list_widget.setResizeMode(QListWidget.Adjust)
                list_widget.setSpacing(10)

                list_widget.itemPressed.connect(self._handle_global_selection) # Corrección selección

                list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                list_widget.setFrameShape(QFrame.NoFrame)

                list_widget.customContextMenuRequested.connect(
                    lambda pos, lw=list_widget: self._on_drive_context_menu(pos, lw)
                )
                list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
                list_widget.previewRequested.connect(self._on_drive_preview_requested)

                thumb_size = self.current_thumbnail_size
                list_widget.setIconSize(QSize(thumb_size, thumb_size))
                item_w = thumb_size + 10
                item_h = thumb_size + 10

                for f in photos:
                    item = QListWidgetItem("Cargando...")
                    item.setToolTip(f['name'])
                    safe_data = {
                        'id': str(f['id']),
                        'name': str(f['name']),
                        'mimeType': f.get('mimeType',''),
                        'thumbnailLink': f.get('thumbnailLink',''),
                        'webContentLink': f.get('webContentLink','')
                    }
                    item.setData(Qt.UserRole, safe_data)
                    self.cloud_list_widget_items[safe_data['id']] = item
                    item.setData(Qt.UserRole + 1, "not_loaded")
                    item.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
                    item.setSizeHint(QSize(item_w, item_h))
                    list_widget.addItem(item)

                # --- ALTURA INICIAL APROXIMADA ---
                rows = (len(photos) // 5) + 1
                initial_height = rows * (item_h + 10)
                list_widget.setFixedHeight(initial_height)

                # --- AUTOCORRECCIÓN DE ALTURA ---
                QTimer.singleShot(10, list_widget.adjust_height_to_content)

                widgets_to_add_for_year.append(list_widget)

            for w in widgets_to_add_for_year:
                self.cloud_container_layout.addWidget(w)

            year_item.setExpanded(True)

        self.cloud_container_layout.addStretch(1)

        # Ajuste extra por si el layout tarda en pintarse
        if self.cloud_scroll_area.widget():
             self.cloud_scroll_area.widget().adjustSize()

        QTimer.singleShot(50, self._load_visible_cloud_thumbnails)
        QTimer.singleShot(300, self._load_visible_cloud_thumbnails)

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _scroll_to_cloud_item(self, current, previous):
        """Navegación rápida al hacer clic en el árbol de fechas."""
        if not current: return

        key = ""
        user_data = current.data(0, Qt.UserRole)

        if current.parent(): # Es un mes
            # --- CORRECCIÓN ROBUSTA ---
            # Si es una Tupla/Lista: ('2023', '05') -> Formato Nuevo
            if isinstance(user_data, (list, tuple)) and len(user_data) >= 2:
                year, month = user_data[0], user_data[1]
                key = f"{year}-{month}"

            # Si es Texto: "2023-05" -> Formato Antiguo o Caché
            elif isinstance(user_data, str):
                key = user_data
            # --------------------------
        else:
            # Es un año
            key = current.text(0)

        target_widget = self.cloud_group_widgets.get(key)

        if target_widget:
            try:
                self.cloud_scroll_area.ensureWidgetVisible(target_widget, 0, 0)
                QTimer.singleShot(200, self._load_visible_cloud_thumbnails)
            except RuntimeError:
                pass

    def _load_visible_cloud_thumbnails(self):
        """
        Carga miniaturas visibles con PRIORIDAD ALTA y pre-carga las siguientes con PRIORIDAD BAJA.
        """
        viewport = self.cloud_scroll_area.viewport()

        # 1. Área visible inmediata (Prioridad 10)
        visible_rect = viewport.rect()

        # 2. Área de pre-carga: 2 pantallas más abajo (Prioridad 0)
        prefetch_rect = viewport.rect().adjusted(0, 0, 0, viewport.height() * 2)

        widget_contenedor = self.cloud_scroll_area.widget()
        if not widget_contenedor: return

        for list_widget in widget_contenedor.findChildren(PreviewListWidget):
            if not list_widget.isVisible(): continue

            # Mapear coordenadas de la lista al viewport
            pos = list_widget.mapTo(viewport, list_widget.rect().topLeft())
            rect = list_widget.rect().translated(pos)

            # Si la lista no está ni en visible ni en prefetch, la ignoramos para ahorrar CPU
            if not (visible_rect.intersects(rect) or prefetch_rect.intersects(rect)):
                continue

            for i in range(list_widget.count()):
                item = list_widget.item(i)

                if item.data(Qt.UserRole + 1) == "not_loaded":
                    # Calcular posición aproximada del item
                    # (No es exacto píxel a píxel por rendimiento, pero sirve para priorizar)

                    priority = 0 # Baja por defecto (Prefetch)

                    # Si la lista intersecta el área visible, asumimos prioridad alta
                    # para asegurar que se carguen rápido.
                    if visible_rect.intersects(rect):
                        priority = 10

                    data = item.data(Qt.UserRole)
                    thumb_link = data.get('thumbnailLink')
                    file_id = data.get('id')

                    if thumb_link and file_id:
                        item.setData(Qt.UserRole + 1, "loading")
                        worker = NetworkThumbnailLoader(thumb_link, file_id, self.thumb_signals)
                        # Lanzar con PRIORIDAD
                        self.threadpool.start(worker, priority)

    def _stop_cloud_operations(self):
        """Detiene de forma SEGURA cualquier descarga o escaneo."""
        self._set_status("Deteniendo operaciones actuales...")

        # 1. Vaciar cola de descargas de miniaturas (y reintentar las locales canceladas)
        self._cancel_pending_loads()

        # 2. Detener escáner de carpetas si existe
        if self.drive_scan_thread:
            try:
                # Intentamos acceder al objeto. Si ya fue borrado por C++,
                # esto lanzará un RuntimeError que capturamos abajo.
                if self.drive_scan_thread.isRunning():

                    if self.drive_scan_worker:
                        try:
                            self.drive_scan_worker.is_running = False
                            # Desconectar de la interfaz para evitar actualizaciones fantasma
                            # (p. ej. "No se encontraron imágenes" tras cerrar sesión). Su
                            # finished sigue conectado a quit/deleteLater para terminar bien.
                            self.drive_scan_worker.progress.disconnect(self._set_status)
                            self.drive_scan_worker.finished.disconnect(self._on_drive_scan_finished)
                        except (RuntimeError, TypeError):
                            pass # Ya estaba desconectado o borrado

                    self.drive_scan_thread.quit()
                    self.drive_scan_thread.wait(1000)
                    # Si aún no ha terminado (red lenta), conservar la referencia
                    self._retire_thread(self.drive_scan_thread, self.drive_scan_worker)

            except RuntimeError:
                # El objeto C++ ya fue borrado (deleteLater), pero la variable Python seguía ahí.
                # No pasa nada, simplemente lo ignoramos.
                print("Aviso: El hilo anterior ya estaba eliminado.")
                self.drive_scan_thread = None

    def _check_auto_login(self):
        """Intenta conectar automáticamente si hay credenciales guardadas."""
        auth = DriveAuthenticator()

        if auth.has_credentials():
            self._set_status("Detectada sesión de Google anterior. Conectando...")
            # En segundo plano: si el token ha caducado se renueva por red y,
            # sin conexión, la petición puede tardar en fallar
            self.btn_gdrive.setEnabled(False)
            self.btn_gdrive.setText("Conectando...")
            self._start_drive_login(silent=True)

    @Slot(str)
    def _on_auto_login_failure(self, error_message):
        """El inicio de sesión automático no pudo usar la sesión guardada."""
        self.btn_gdrive.setEnabled(True)
        self.btn_gdrive.setText("Iniciar sesión con Google")
        self._set_status(error_message or "No se pudo restaurar la sesión de Google.")

    # --- LÓGICA DEL ÁRBOL DE DIRECTORIOS ---

    @Slot()
    def _toggle_drive_folder_tree(self):
        """Muestra u oculta el panel lateral de carpetas."""
        is_visible = self.btn_show_tree.isChecked()
        self.cloud_folder_panel.setVisible(is_visible)

        if is_visible:
            # Si lo abrimos y está vacío, cargamos la raíz
            if self.cloud_folder_tree.topLevelItemCount() == 0:
                self._load_folder_tree_root()

    # Antigüedad a partir de la cual un listado de carpetas en caché se
    # comprueba de nuevo con Drive (se muestra igualmente al momento)
    DRIVE_FOLDER_TTL_S = 600

    def _reset_drive_tree(self):
        """Vacía el árbol de carpetas; las respuestas pendientes se ignorarán."""
        self._drive_tree_gen += 1
        self._drive_tree_items = {}
        self.cloud_folder_tree.clear()

    def _load_folder_tree_root(self):
        """
        Carga la Carpeta Raíz como primer elemento del árbol.
        """
        if not self.current_drive_folder_id:
            return

        self._reset_drive_tree()

        # 1. Crear el elemento RAÍZ manualmente
        root_name = getattr(self, 'current_drive_folder_name', 'Carpeta Raíz')
        root_item = QTreeWidgetItem(self.cloud_folder_tree, [root_name])
        root_item.setData(0, Qt.UserRole, self.current_drive_folder_id)
        root_item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon))
        self._drive_tree_items[self.current_drive_folder_id] = root_item

        # 2. Sus subcarpetas: de la caché al momento, o de Drive
        self._show_drive_subfolders(root_item)
        root_item.setExpanded(True) # Lo mostramos abierto

    @staticmethod
    def _is_drive_placeholder(item):
        return item.childCount() == 1 and item.child(0).data(0, Qt.UserRole + 1) == "placeholder"

    @staticmethod
    def _add_drive_placeholder(item, text="Cargando..."):
        """Hijo provisional: hace que aparezca la flecha de expansión."""
        placeholder = QTreeWidgetItem(item, [text])
        placeholder.setData(0, Qt.UserRole + 1, "placeholder")
        placeholder.setFlags(Qt.NoItemFlags)
        return placeholder

    def _show_drive_subfolders(self, item):
        """
        Muestra las subcarpetas de item: al momento si están en la caché (y,
        si son antiguas, las comprueba con Drive en segundo plano); si no, las
        pide a Drive dejando "Cargando..." mientras tanto.
        """
        folder_id = item.data(0, Qt.UserRole)
        if not folder_id:
            return
        folders, fetched_at = self.db.get_drive_subfolders(folder_id)
        if folders is not None:
            self._fill_drive_tree_item(item, folders)
            if time.time() - fetched_at > self.DRIVE_FOLDER_TTL_S:
                self._request_drive_folders([folder_id], priority=5)
        else:
            if item.childCount() == 0:
                self._add_drive_placeholder(item)
            self._request_drive_folders([folder_id], priority=10)

    def _fill_drive_tree_item(self, item, folders):
        """
        Pone folders como hijos de item. Las carpetas que ya estaban se
        conservan (con lo que tuvieran desplegado); de las nuevas se adelanta,
        en una sola consulta, el listado de sus subcarpetas para que abrirlas
        sea inmediato.
        """
        old = {}
        for child in item.takeChildren():
            child_id = child.data(0, Qt.UserRole)
            if child_id:
                old[child_id] = child

        new_children = []
        for f in folders:
            child = old.pop(f['id'], None)
            if child is None:
                child = QTreeWidgetItem([f['name']])
                child.setData(0, Qt.UserRole, f['id'])
                child.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                new_children.append(child)
            else:
                child.setText(0, f['name'])
            item.addChild(child)
            self._drive_tree_items[f['id']] = child
        for gone in old.values():
            self._forget_drive_tree_item(gone)

        if not folders and item.parent() is None:
            info = QTreeWidgetItem(item, ["(Sin subcarpetas)"])
            info.setFlags(Qt.NoItemFlags)

        if not new_children:
            return
        # Flecha solo en las que tienen subcarpetas (si ya se sabe)
        counts = self.db.get_drive_subfolder_counts([c.data(0, Qt.UserRole) for c in new_children])
        unknown = []
        for child in new_children:
            child_id = child.data(0, Qt.UserRole)
            if child_id not in counts:
                unknown.append(child_id)
                self._add_drive_placeholder(child)
            elif counts[child_id]:
                self._add_drive_placeholder(child)
        if unknown:
            self._request_drive_folders(unknown, priority=0)  # Adelantar el siguiente nivel

    def _forget_drive_tree_item(self, item):
        """Quita item y sus descendientes del índice por id."""
        item_id = item.data(0, Qt.UserRole)
        if item_id and self._drive_tree_items.get(item_id) is item:
            del self._drive_tree_items[item_id]
        for i in range(item.childCount()):
            self._forget_drive_tree_item(item.child(i))

    def _request_drive_folders(self, folder_ids, priority=0):
        """Pide a Drive, en segundo plano, las subcarpetas de folder_ids."""
        folder_ids = [f for f in folder_ids if f not in self._drive_folders_in_flight]
        if not folder_ids:
            return
        if not self._drive_folders_in_flight:
            # Que el escáner de fotos ceda la red mientras se navega
            self.set_drive_priority_low.emit(True)
        self._drive_folders_in_flight.update(folder_ids)
        loader = DriveFolderLoader(self._drive_tree_gen, folder_ids, self.drive_folder_signals)
        self.drive_folder_pool.start(loader, priority)

    @Slot(int, list, object)
    def _on_drive_folders_loaded(self, generation, folder_ids, listings):
        """Guarda en la caché las subcarpetas recibidas y actualiza el árbol."""
        self._drive_folders_in_flight.difference_update(folder_ids)
        if not self._drive_folders_in_flight:
            self.set_drive_priority_low.emit(False)

        if listings is None:
            if generation == self._drive_tree_gen:
                for folder_id in folder_ids:
                    item = self._drive_tree_items.get(folder_id)
                    if item is not None and self._is_drive_placeholder(item):
                        item.child(0).setText(0, "(No se pudo cargar; pliega y vuelve a desplegar)")
                self._set_status("No se pudieron cargar las carpetas de Drive.")
            return

        try:
            self.db.save_drive_subfolders(listings, time.time())
        except Exception as e:
            print(f"Error guardando carpetas de Drive: {e}")
        if generation != self._drive_tree_gen or not self.is_drive_connected:
            return  # El árbol ha cambiado; la caché sí sirve

        for folder_id, folders in listings.items():
            item = self._drive_tree_items.get(folder_id)
            if item is None:
                continue
            if item.isExpanded() or not self._is_drive_placeholder(item):
                self._fill_drive_tree_item(item, folders)
            elif not folders:
                item.takeChildren()  # Plegada y sin subcarpetas: sin flecha

    @Slot(QTreeWidgetItem)
    def _on_folder_tree_item_expanded(self, item):
        """Se llama al hacer clic en la flechita de expansión."""
        if self._is_drive_placeholder(item):
            item.child(0).setText(0, "Cargando...")
        self._show_drive_subfolders(item)

    @Slot(str, str)
    def _on_drive_link_refreshed(self, file_id, link):
        """Guarda el enlace de miniatura renovado para no volver a pedirlo."""
        try:
            self.db.update_drive_thumbnail_links([(link, file_id)])
        except Exception as e:
            print(f"Error guardando enlace de miniatura: {e}")

    @Slot(QTreeWidgetItem, int)
    def _on_folder_tree_item_clicked(self, item, column):
        """
        Gestiona la navegación:
        - Si es la Raíz -> Muestra TODO (Recursivo).
        - Si es Subcarpeta -> Muestra solo contenido de esa carpeta.
        """
        folder_id = item.data(0, Qt.UserRole)
        folder_name = item.text(0)

        if not folder_id:
            return

        # CASO 1: Hemos pulsado la Carpeta Raíz (Volver al inicio)
        if folder_id == self.current_drive_folder_id:
            self._set_status(f"Mostrando vista completa: {folder_name}")

            # Carga TODO lo de la carpeta raíz (recursivo) y redibuja la Nube
            self.cloud_scroll_area.setUpdatesEnabled(False)
            self._load_drive_from_db(self.current_drive_folder_id)
            self.cloud_scroll_area.setUpdatesEnabled(True)
            return

        # CASO 2: Hemos pulsado una Subcarpeta
        self._set_status(f"Filtrando carpeta: {folder_name}...")
        self._load_specific_folder_view(folder_id)

    def _load_specific_folder_view(self, target_folder_id):
        """
        Carga en memoria y muestra SOLO las fotos de la carpeta indicada.
        """
        # 1. Obtener fotos filtradas de la DB
        db_photos = self.db.get_drive_photos_by_parent(target_folder_id)

        # Si no hay fotos en la DB todavía (quizás el scanner no llegó), avisamos visualmente
        # pero NO borramos la pantalla si está vacía para no flashear, a menos que sea necesario.

        # 2. Limpiar estructuras de memoria
        self.drive_photos_by_date = {}
        self.drive_loaded_ids = set()
        self.cloud_photo_count = 0

        # 3. Formatear datos (Igual que en _load_drive_from_db)
        formatted_photos = []
        for row in db_photos:
            formatted_photos.append({
                'id': row['id'],
                'name': row['name'],
                'createdTime': row['created_time'],
                'mimeType': row['mime_type'],
                'thumbnailLink': row['thumbnail_link'],
                'webContentLink': row['web_content_link']
            })

        # 4. Clasificar en memoria (Fechas)
        self._classify_drive_items_in_memory(formatted_photos)

        # 5. Redibujar la interfaz
        # Congelamos actualizaciones visuales para que sea instantáneo
        self.cloud_scroll_area.setUpdatesEnabled(False)
        self._display_cloud_photos()
        self.cloud_scroll_area.setUpdatesEnabled(True)

        self._set_status(f"Mostrando {self.cloud_photo_count} fotos de esta carpeta.")

    # ========================================================
    # GESTIÓN DE DUPLICADOS
    # ========================================================
    @Slot()
    def _start_duplicate_search(self):
        """Inicia el worker de búsqueda."""
        if not self.photos_by_year_month:
            QMessageBox.information(self, "Aviso", "Primero carga una carpeta con fotos.")
            return

        self.btn_duplicates.setEnabled(False)
        self.btn_duplicates.setText("Analizando...")
        self._set_status("Iniciando búsqueda visual de duplicados...")

        # Crear hilo y worker
        self.dup_thread = QThread()
        self.dup_worker = DuplicateFinderWorker(self.db.db_path)
        self.dup_worker.moveToThread(self.dup_thread)

        self.dup_thread.started.connect(self.dup_worker.run)
        self.dup_worker.progress.connect(self._set_status)
        self.dup_worker.finished.connect(self._on_duplicate_search_finished)

        # Limpieza automática
        self.dup_worker.finished.connect(self.dup_thread.quit)
        self.dup_worker.finished.connect(self.dup_worker.deleteLater)
        self.dup_thread.finished.connect(self.dup_thread.deleteLater)

        self.dup_thread.start()

    @Slot(dict)
    def _on_duplicate_search_finished(self, duplicates):
        """Recibe los resultados y abre el diálogo."""
        self.btn_duplicates.setEnabled(True)
        self.btn_duplicates.setText("Buscar Duplicados")
        self._set_status("Búsqueda finalizada.")

        if not duplicates:
            QMessageBox.information(self, "Resultado", "¡Genial! No se encontraron duplicados visuales.")
            return

        # Calcular total de fotos duplicadas
        total_dupes = sum(len(v) for v in duplicates.values())
        self._set_status(f"Encontrados {len(duplicates)} grupos ({total_dupes} fotos).")

        # Abrir diálogo
        dialog = DuplicateDialog(duplicates, self.db, self)
        dialog.exec()

        # Al cerrar, verificar si se borró algo para refrescar la galería
        deleted_files = dialog.get_deleted_items()
        if deleted_files:
            self._set_status(f"Se eliminaron {len(deleted_files)} fotos. Actualizando vista...")

            # Eliminamos las fotos borradas de la memoria de la app
            for path in deleted_files:
                self._remove_from_memory_struct(path, self.photos_by_year_month)

            # Redibujamos la pantalla de fotos
            self._display_photos()

    def _setup_safe_tab(self):
        layout = QVBoxLayout(self.safe_tab)

        # ESTADO BLOQUEADO (Igual que antes)
        self.locked_widget = QWidget()
        lock_layout = QVBoxLayout(self.locked_widget)
        lock_layout.setAlignment(Qt.AlignCenter)

        icon_lbl = QLabel("🔒")
        icon_lbl.setStyleSheet("font-size: 64px;")
        icon_lbl.setAlignment(Qt.AlignCenter)
        lock_layout.addWidget(icon_lbl)

        lbl = QLabel("Esta zona está protegida.")
        lbl.setAlignment(Qt.AlignCenter)
        lock_layout.addWidget(lbl)

        btn_unlock = QPushButton("Desbloquear Caja Fuerte")
        btn_unlock.setFixedWidth(200)
        btn_unlock.clicked.connect(self._unlock_safe)
        lock_layout.addWidget(btn_unlock, 0, Qt.AlignCenter)

        layout.addWidget(self.locked_widget)

        # ESTADO DESBLOQUEADO (Rediseñado)
        self.unlocked_widget = QWidget()
        self.unlocked_widget.setVisible(False)
        unlock_layout = QVBoxLayout(self.unlocked_widget)

        # Barra superior
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("📂 Archivos Protegidos (Desencriptados en memoria)"))
        btn_lock = QPushButton("Bloquear")
        btn_lock.clicked.connect(self._lock_safe)
        top_bar.addWidget(btn_lock, 0, Qt.AlignRight)
        unlock_layout.addLayout(top_bar)

        # Área de scroll (Igual que la pestaña fotos)
        self.safe_scroll = QScrollArea()
        self.safe_scroll.setWidgetResizable(True)

        # Contenedor interno VERTICAL (antes era Grid)
        self.safe_container = QWidget()
        self.safe_container_layout = QVBoxLayout(self.safe_container)
        self.safe_container_layout.setSpacing(0)

        self.safe_scroll.setWidget(self.safe_container)
        unlock_layout.addWidget(self.safe_scroll)

        layout.addWidget(self.unlocked_widget)

        self.current_safe_key = None
        self.current_safe_legacy_key = None

    def _unlock_safe(self):
        # Verificar si ya existe contraseña configurada
        if not config_manager.has_safe_password():
            QMessageBox.information(self, "Configuración", "Primero debes añadir una foto a la caja fuerte para configurar la contraseña.")
            return

        dialog = LoginDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.current_safe_key = dialog.key
            self.current_safe_legacy_key = dialog.legacy_key
            self._migrate_legacy_safe_files()
            self.locked_widget.setVisible(False)
            self.unlocked_widget.setVisible(True)
            self._load_safe_content()

    def _migrate_legacy_safe_files(self):
        """Convierte al cifrado AES los archivos de versiones antiguas (XOR)."""
        pending = []
        for row in self.db.get_safe_files():
            for path in (row['encrypted_path'], row['encrypted_path'] + ".thumb"):
                try:
                    if os.path.exists(path) and safe_crypto.is_legacy_file(path):
                        pending.append(path)
                except OSError as e:
                    print(f"No se pudo leer {path}: {e}")
        if not pending:
            return

        migrated, errors = 0, []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for i, path in enumerate(pending):
                self._set_status(f"Actualizando cifrado de la caja fuerte ({i+1}/{len(pending)})...")
                QApplication.processEvents()
                try:
                    CryptoManager.migrate_legacy_file(path, self.current_safe_key, self.current_safe_legacy_key)
                    migrated += 1
                except Exception as e:
                    print(f"Error migrando {path}: {e}")
                    errors.append(f"{Path(path).name}: {e}")
        finally:
            QApplication.restoreOverrideCursor()

        self._set_status(f"Cifrado actualizado en {migrated} archivo(s) de la caja fuerte.")
        if errors:
            QMessageBox.warning(
                self, "Actualización de cifrado incompleta",
                f"Se actualizaron {migrated} de {len(pending)} archivos. Los demás se reintentarán "
                "la próxima vez que desbloquees la caja fuerte.\n\n" + "\n".join(errors[:10])
            )

    def _lock_safe(self):
        self.current_safe_key = None
        self.current_safe_legacy_key = None
        # Las miniaturas que aún se estén descifrando se descartarán al llegar
        self.safe_generation += 1
        self.safe_pool.clear()
        self.safe_list_items = {}
        # Destruir las miniaturas desencriptadas por seguridad
        while self.safe_container_layout.count():
            item = self.safe_container_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        self.unlocked_widget.setVisible(False)
        self.locked_widget.setVisible(True)

    def _load_safe_content(self):
        self.safe_generation += 1
        self.safe_pool.clear()
        self.safe_list_items = {}
        placeholders = {}

        while self.safe_container_layout.count() > 0:
            item = self.safe_container_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        files = self.db.get_safe_files()
        if not files:
            lbl = QLabel("La caja fuerte está vacía.")
            lbl.setAlignment(Qt.AlignCenter)
            self.safe_container_layout.addWidget(lbl)
            return

        safe_data = {}
        for row in files:
            date_str = row['original_date']
            if not date_str or "-" not in date_str: date_str = "0000-00"
            year, month = date_str.split("-")
            if year not in safe_data: safe_data[year] = {}
            if month not in safe_data[year]: safe_data[year][month] = []
            safe_data[year][month].append(row)

        sorted_years = sort_years(safe_data.keys())
        thumb_size = self.current_thumbnail_size

        for year in sorted_years:
            year_label = QLabel(year_title(year))
            year_label.setStyleSheet("font-size: 16pt; font-weight: bold; margin-top: 20px; margin-bottom: 5px; color: #e74c3c;")
            self.safe_container_layout.addWidget(year_label)

            for month in sort_months(safe_data[year].keys(), reverse=True):
                file_rows = safe_data[year][month]
                try:
                    month_name = datetime.datetime.strptime(month, "%m").strftime("%B").capitalize()
                except: month_name = "Desconocido"

                month_label = QLabel(month_name)
                month_label.setStyleSheet("font-size: 14pt; font-weight: bold; margin-top: 10px;")
                self.safe_container_layout.addWidget(month_label)

                list_widget = PreviewListWidget()
                list_widget.setMovement(QListWidget.Static)
                list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
                list_widget.setSpacing(20)
                list_widget.setViewMode(QListWidget.IconMode)
                list_widget.setResizeMode(QListWidget.Adjust)
                list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                list_widget.setFrameShape(QFrame.NoFrame)
                list_widget.setIconSize(QSize(thumb_size, thumb_size))

                list_widget.itemDoubleClicked.connect(self._safe_item_double_clicked)
                list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
                list_widget.customContextMenuRequested.connect(
                    lambda pos, lw=list_widget: self._safe_list_context_menu(pos, lw)
                )

                for row in file_rows:
                    encrypted_path = row['encrypted_path']
                    original_name = Path(row['original_path']).name
                    media_type = row['media_type']

                    if not os.path.exists(encrypted_path): continue

                    item = QListWidgetItem()
                    item.setToolTip(original_name)
                    item.setText("")
                    item.setData(Qt.UserRole, row)

                    # Marcador inmediato; la miniatura real se descifra en segundo plano
                    if media_type not in placeholders:
                        placeholders[media_type] = self._safe_placeholder_icon(media_type, thumb_size)
                    item.setIcon(placeholders[media_type])
                    item.setSizeHint(QSize(thumb_size, thumb_size))
                    item.setData(Qt.UserRole + 1, "safe_loading")
                    self.safe_list_items[encrypted_path] = (item, media_type)
                    self.safe_pool.start(SafeThumbnailLoader(
                        self.safe_thumb_signals, self.safe_generation, encrypted_path, media_type,
                        self.current_safe_key, self.current_safe_legacy_key, thumb_size
                    ))

                    list_widget.addItem(item)

                item_full_dim = thumb_size + list_widget.spacing()
                viewport_width = self.safe_scroll.viewport().width() - 30
                num_cols = max(1, viewport_width // item_full_dim)
                rows = (len(file_rows) + num_cols - 1) // num_cols
                total_height = (rows * item_full_dim) + 30
                list_widget.setFixedHeight(total_height)

                self.safe_container_layout.addWidget(list_widget)

        self.safe_container_layout.addStretch(1)

    def _safe_placeholder_icon(self, media_type, thumb_size):
        """Icono gris de espera (o de error) para un elemento de la caja fuerte."""
        placeholder = QPixmap(thumb_size, thumb_size)
        placeholder.fill(Qt.transparent)
        painter = QPainter(placeholder)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setBrush(QBrush(QColor("#454545")))
        pen = QPen(QColor("#666666"))
        pen.setWidth(2)
        painter.setPen(pen)
        rect_size = thumb_size - 2
        painter.drawRoundedRect(1, 1, rect_size, rect_size, 4, 4)

        icon_type = QStyle.StandardPixmap.SP_MediaPlay if media_type == 'video' else QStyle.StandardPixmap.SP_FileIcon
        icon = self.style().standardIcon(icon_type)
        icon_dim = int(thumb_size * 0.5)
        x = (thumb_size - icon_dim) // 2
        y = (thumb_size - icon_dim) // 2
        icon.paint(painter, x, y, icon_dim, icon_dim)
        painter.end()
        return QIcon(placeholder)

    @Slot(int, str, QImage)
    def _on_safe_thumbnail_loaded(self, generation, encrypted_path, image):
        if generation != self.safe_generation:
            return  # Carga antigua o caja ya bloqueada
        entry = self.safe_list_items.get(encrypted_path)
        if not entry:
            return
        item, media_type = entry
        scaled = QPixmap.fromImage(image)

        # Si es vídeo, pintamos el icono de PLAY encima de la foto
        if media_type == 'video':
            icon_dim = int(min(scaled.width(), scaled.height()) * 0.5)
            x = (scaled.width() - icon_dim) // 2
            y = (scaled.height() - icon_dim) // 2
            painter = QPainter(scaled)
            painter.setRenderHint(QPainter.Antialiasing)
            # Fondo semitransparente para que se vea el play
            painter.setBrush(QColor(0, 0, 0, 128))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(x, y, icon_dim, icon_dim)
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay).paint(painter, x, y, icon_dim, icon_dim)
            painter.end()

        try:
            item.setIcon(QIcon(scaled))
            item.setSizeHint(scaled.size())
            item.setData(Qt.UserRole + 1, "safe_loaded")
        except RuntimeError:
            pass

    @Slot(int, str)
    def _on_safe_thumbnail_failed(self, generation, encrypted_path):
        if generation != self.safe_generation:
            return
        entry = self.safe_list_items.get(encrypted_path)
        if entry:
            try:
                entry[0].setData(Qt.UserRole + 1, "safe_failed")  # Se queda con el marcador gris
            except RuntimeError:
                pass

    def _move_to_safe_box(self, items, is_video):
        """Prepara y lanza el hilo de encriptación en segundo plano."""
        # 1. Obtener la clave (creando la contraseña la primera vez)
        if not config_manager.has_safe_password():
            dialog = CreatePasswordDialog(self)
            if dialog.exec() != QDialog.Accepted: return
            key = config_manager.set_safe_password(dialog.password)
        else:
            dialog = LoginDialog(self)
            if dialog.exec() != QDialog.Accepted: return
            key = dialog.key

        # 2. Recopilar datos para no pasar widgets al hilo
        items_data = []
        for item in items:
            path = item.data(Qt.UserRole)
            if path and os.path.exists(path):
                items_data.append((path, is_video))

        if not items_data: return

        self._set_status("Iniciando encriptación en segundo plano...")

        # 3. Configurar Worker y Thread
        self.safe_thread = QThread()
        self.safe_worker = MoveToSafeWorker(self.db.db_path, items_data, key)
        self.safe_worker.moveToThread(self.safe_thread)

        # Conectar señales
        self.safe_thread.started.connect(self.safe_worker.run)
        self.safe_worker.progress.connect(self._set_status)
        self.safe_worker.item_finished.connect(self._on_safe_item_processed)
        self.safe_worker.finished.connect(self._on_safe_worker_finished)

        # Limpieza automática
        self.safe_worker.finished.connect(self.safe_thread.quit)
        self.safe_worker.finished.connect(self.safe_worker.deleteLater)
        self.safe_thread.finished.connect(self.safe_thread.deleteLater)

        self.safe_thread.start()

    @Slot(QListWidgetItem)
    def _safe_item_double_clicked(self, item):
        """Abre la foto encriptada en el visor a pantalla completa."""
        row_data = item.data(Qt.UserRole)
        encrypted_path = row_data['encrypted_path']
        media_type = row_data['media_type']

        if media_type == 'video':
            QMessageBox.information(self, "Info", "La reproducción de vídeo encriptado en memoria aún no está soportada. Restáuralo para verlo.")
            return

        self._set_status("Desencriptando para visualización...")
        try:
            img_bytes = CryptoManager.decrypt_to_bytes(encrypted_path, self.current_safe_key, self.current_safe_legacy_key)
            if img_bytes:
                pixmap = QPixmap()
                pixmap.loadFromData(img_bytes)
                if not pixmap.isNull():
                    # Usamos tu visor existente
                    preview = ImagePreviewDialog(pixmap, self)
                    preview.show_with_animation()
                    self._set_status("Visualizando archivo seguro.")
                else:
                    self._set_status("Error: Imagen corrupta o formato no soportado.")
        except Exception as e:
            print(f"Error visualización safe: {e}")

    def _safe_list_context_menu(self, pos, list_widget):
        """Menú contextual para la lista de la caja fuerte."""
        item = list_widget.itemAt(pos)
        if not item: return

        menu = QMenu(self)
        action_restore = menu.addAction("Restaurar a Galería")
        action_restore.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))

        action = menu.exec(list_widget.mapToGlobal(pos))

        if action == action_restore:
            # Copiamos las rutas ANTES de restaurar: refrescar la vista destruye los items
            encrypted_paths = [sel.data(Qt.UserRole)['encrypted_path'] for sel in list_widget.selectedItems()]
            self._restore_files_from_safe(encrypted_paths)

    def _restore_files_from_safe(self, encrypted_paths):
        """Restaura varios archivos y refresca las vistas UNA sola vez al final."""
        if not encrypted_paths: return

        restored = 0
        errors = []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for i, encrypted_path in enumerate(encrypted_paths):
                self._set_status(f"Restaurando ({i+1}/{len(encrypted_paths)})...")
                QApplication.processEvents()
                try:
                    self._restore_from_safe(encrypted_path)
                    restored += 1
                except Exception as e:
                    print(f"Error restaurando {encrypted_path}: {e}")
                    errors.append(str(e))
        finally:
            QApplication.restoreOverrideCursor()

        self._load_safe_content()
        if restored:
            self._perform_auto_refresh()

        self._set_status(f"{restored} archivo(s) restaurado(s) de la caja fuerte.")
        if errors:
            QMessageBox.warning(
                self, "Restauración incompleta",
                f"Restaurados: {restored} de {len(encrypted_paths)}.\n\nErrores:\n" + "\n".join(errors[:10])
            )
        else:
            QMessageBox.information(self, "Éxito", f"{restored} archivo(s) restaurado(s) a su ubicación original.")

    def _restore_from_safe(self, encrypted_path):
        """
        Restaura UN archivo y recupera su fecha en la BD y en el sistema.
        No toca la interfaz; lanza una excepción si algo falla.
        """
        row = self.db.conn.execute("SELECT * FROM safe_files WHERE encrypted_path = ?", (encrypted_path,)).fetchone()
        if not row:
            raise RuntimeError(f"{Path(encrypted_path).name}: no figura en la caja fuerte")

        original_path = row['original_path']
        name = Path(original_path).name
        media_type = row['media_type']

        # Fecha guardada (YYYY-MM)
        saved_date = row['original_date']
        if saved_date and "-" in saved_date:
            year, month = saved_date.split("-", 1)
        else:
            year, month = NO_DATE_YEAR, NO_DATE_MONTH
        if not _is_known_year(year):
            year, month = NO_DATE_YEAR, NO_DATE_MONTH

        # No sobrescribir un archivo nuevo que ocupe ya la ruta original
        if os.path.exists(original_path):
            raise RuntimeError(f"{name}: ya existe un archivo en {original_path}")

        # 1. Desencriptar a un temporal y renombrar: un fallo no deja un archivo a medias
        temp_path = original_path + ".restoring"
        try:
            CryptoManager.decrypt_file(encrypted_path, temp_path, self.current_safe_key, self.current_safe_legacy_key)
            os.replace(temp_path, original_path)
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise RuntimeError(f"{name}: {e}") from e

        # 2. Volver a darlo de alta en la BD (se borró al entrar en la caja fuerte)
        with self.db.conn:
            if media_type == 'video':
                self.db.conn.execute("""
                    INSERT OR REPLACE INTO videos (filepath, year, month, is_hidden)
                    VALUES (?, ?, ?, 0)
                """, (original_path, year, month))
            else:
                # scanned_for_faces=0 para que vuelva a buscar caras
                self.db.conn.execute("""
                    INSERT OR REPLACE INTO photos (filepath, year, month, scanned_for_faces, is_hidden)
                    VALUES (?, ?, ?, 0, 0)
                """, (original_path, year, month))

        # 3. Restaurar la fecha física del archivo (si se conoce)
        if _is_known_year(year):
            self._update_file_metadata_on_disk(original_path, year, month)

        # 4. Limpiar la caja fuerte (registro, archivo cifrado y miniatura de vídeo)
        self.db.remove_from_safe(encrypted_path)
        for leftover in (encrypted_path, encrypted_path + ".thumb"):
            if os.path.exists(leftover):
                try: os.remove(leftover)
                except OSError as e: print(f"No se pudo borrar {leftover}: {e}")

    @Slot(str, bool)
    def _on_safe_item_processed(self, original_path, is_video):
        """Se llama cada vez que el worker termina con un archivo."""
        # Eliminamos el elemento de la memoria de la aplicación
        if is_video:
            self._remove_from_memory_struct(original_path, self.videos_by_year_month)
        else:
            self._remove_from_memory_struct(original_path, self.photos_by_year_month)

    @Slot()
    def _on_safe_worker_finished(self):
        """Se llama cuando todos los archivos se han movido."""
        self._set_status("Proceso de caja fuerte finalizado.")

        # Refrescar las vistas
        if self.videos_by_year_month:
            self._display_videos()
        if self.photos_by_year_month:
            self._display_photos()

        # Si la caja fuerte está abierta, refrescarla también para ver los nuevos items
        if hasattr(self, 'unlocked_widget') and self.unlocked_widget.isVisible():
            self._load_safe_content()

        QMessageBox.information(self, "Completado", "Los archivos se han movido a la caja fuerte correctamente.")

    # ==========================================================
    # LÓGICA DE ÁRBOLES DE DIRECTORIO LOCALES (FOTOS Y VÍDEOS)
    # ==========================================================

    @Slot()
    def _toggle_photo_folder_tree(self):
        self._toggle_local_folder_tree(is_video=False)

    @Slot()
    def _toggle_video_folder_tree(self):
        self._toggle_local_folder_tree(is_video=True)

    def _toggle_local_folder_tree(self, is_video):
        """Muestra u oculta el árbol de carpetas sin tocar el panel derecho."""
        g = self._gallery(is_video)
        left, center, right = g.splitter.sizes()
        should_show = g.tree_button.isChecked()
        g.folder_panel.setVisible(should_show)

        if should_show:
            # Si estaba colapsado, darle 280 px quitándoselos a la galería
            if left < 50:
                target_width = 280
                g.splitter.setSizes([target_width, max(100, center - target_width), right])
            # Carga perezosa
            if g.folder_tree.topLevelItemCount() == 0 and self.current_directory:
                self._load_local_tree_root(g.folder_tree, self.current_directory)
        else:
            # El ancho del árbol vuelve a la galería; la derecha no cambia
            g.splitter.setSizes([0, center + left, right])

    def _load_local_tree_root(self, tree_widget, root_path):
        """Carga la raíz del árbol local."""
        tree_widget.clear()
        root_name = Path(root_path).name
        root_item = QTreeWidgetItem(tree_widget, [root_name])
        root_item.setData(0, Qt.UserRole, root_path)
        root_item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        root_item.setExpanded(True)

        # Cargar primer nivel de subcarpetas
        self._populate_local_item(root_item, root_path)

    def _populate_local_item(self, parent_item, folder_path):
        """Busca subcarpetas y las añade al item."""
        try:
            # Listar directorios (no ocultos)
            entries = []
            with os.scandir(folder_path) as it:
                for entry in it:
                    if entry.is_dir() and not entry.name.startswith('.'):
                        entries.append(entry)

            # Ordenar alfabéticamente
            entries.sort(key=lambda e: e.name.lower())

            for entry in entries:
                item = QTreeWidgetItem(parent_item, [entry.name])
                item.setData(0, Qt.UserRole, entry.path)
                item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))

                # Chequeo rápido de si tiene hijos para añadir dummy (Lazy Load)
                has_subdirs = False
                try:
                    with os.scandir(entry.path) as sub_it:
                        for sub in sub_it:
                            if sub.is_dir() and not sub.name.startswith('.'):
                                has_subdirs = True
                                break
                except: pass

                if has_subdirs:
                    QTreeWidgetItem(item, ["Cargando..."])

        except Exception as e:
            print(f"Error leyendo carpeta {folder_path}: {e}")

    @Slot(QTreeWidgetItem)
    def _on_local_folder_tree_expanded(self, item):
        """Carga perezosa al expandir."""
        if item.childCount() == 1 and item.child(0).text(0) == "Cargando...":
            item.removeChild(item.child(0)) # Quitar dummy
            folder_path = item.data(0, Qt.UserRole)
            if folder_path:
                self._populate_local_item(item, folder_path)

    @Slot(QTreeWidgetItem, int)
    def _on_photo_folder_tree_clicked(self, item, column):
        self._on_local_folder_tree_clicked(item, is_video=False)

    @Slot(QTreeWidgetItem, int)
    def _on_video_folder_tree_clicked(self, item, column):
        self._on_local_folder_tree_clicked(item, is_video=True)

    def _on_local_folder_tree_clicked(self, item, is_video):
        """Filtra la galería por la carpeta pulsada (la raíz quita el filtro)."""
        path = item.data(0, Qt.UserRole)
        if not path: return
        kind = "vídeos" if is_video else "fotos"
        filter_path = None if path == self.current_directory else path
        if is_video:
            self.current_video_filter_path = filter_path
        else:
            self.current_photo_filter_path = filter_path
        if filter_path is None:
            self._set_status(f"Mostrando todos los {kind} de: {Path(path).name}")
        else:
            self._set_status(f"Filtrando {kind} en: {Path(path).name}")
        self._display_media(is_video)

    def _handle_global_selection(self, item):
        """
        Limpia la selección de todas las demás listas cuando el usuario hace clic en una.
        Permite mantener la selección múltiple si se pulsa Ctrl.
        """
        sender_list = self.sender()
        if not sender_list: return

        # Si el usuario pulsa Control, asumimos que quiere seleccionar cosas de varios meses
        if QApplication.keyboardModifiers() & Qt.ControlModifier:
            return

        # Buscar el contenedor padre (el widget dentro del ScrollArea)
        # Esto funciona para Fotos, Vídeos y Nube indistintamente
        parent_widget = sender_list.parent()
        if not parent_widget: return

        # Recorrer TODAS las listas hermanas y limpiar su selección
        for other_list in parent_widget.findChildren(PreviewListWidget):
            if other_list != sender_list:
                # Bloqueamos señales para evitar bucles recursivos innecesarios
                other_list.blockSignals(True)
                other_list.clearSelection()
                other_list.blockSignals(False)

SPLASH_MIN_MS = 2000  # Tiempo mínimo que se ve el splash (incluye lo que tarda en abrir la ventana)

def run_visagevault():
    """Inicia la aplicación con splash. Nunca bloquea la interfaz."""
    # Si se ejecuta visagevault.py, el splash ya está en pantalla desde antes de
    # las importaciones pesadas (ver "SPLASH TEMPRANO" al principio del fichero)
    app = QApplication.instance() or QApplication(sys.argv)
    if _early_splash is not None:
        splash, shown_at = _early_splash, _early_splash_shown_at
    else:
        splash, shown_at = _create_splash(app)

    # 2. Ventana principal. Los diálogos de arranque esperan a que se cierre
    #    el splash; el escaneo y la carga de datos empiezan ya, detrás.
    window = VisageVaultApp()
    window._splash_open = True
    window.showMaximized()

    # 3. Cerrar el splash sin bloquear (antes: bucle anidado de 2 s con splash modal)
    def close_splash():
        splash.finish(window)
        window.on_splash_closed()

    elapsed_ms = int((time.monotonic() - shown_at) * 1000)
    QTimer.singleShot(max(0, SPLASH_MIN_MS - elapsed_ms), close_splash)

    exit_code = app.exec()

    # Salir sin la limpieza final de PySide: al terminar Python, PySide destruye
    # uno a uno los widgets que siguen vivos y, según el orden, puede intentar
    # destruir alguno que ya lo estaba -> fallo de segmentación al cerrar
    # (visto en openSUSE con el selector de carpetas). closeEvent ya ha guardado
    # la configuración y parado las tareas; solo queda cerrar la base de datos.
    for conn in (window.db.conn, window.db.meta_conn):
        try:
            if conn:
                conn.close()  # Cierre ordenado: SQLite vuelca el WAL a la BD
        except Exception as e:
            print(f"Error cerrando la base de datos: {e}")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)

def _create_splash(app):
    """Splash para cuando la app se lanza importando el módulo (no como script)."""
    pixmap = QPixmap(resource_path("AnabasaSoft.png"))
    if pixmap.isNull():
        pixmap = QPixmap(resource_path("visagevault.png")).scaled(
            600, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
    splash = QSplashScreen(pixmap)
    splash.show()
    app.processEvents()  # Pintarlo ya
    return splash, time.monotonic()

if __name__ == "__main__":
    run_visagevault()
