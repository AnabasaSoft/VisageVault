# ==============================================================================
# PROYECTO: VisageVault - Gestor de Fotografías Inteligente
# VERSIÓN: 1.5.2
# DERECHOS DE AUTOR: © 2025 Daniel Serrano Armenta
# ==============================================================================
#
# Autor: Daniel Serrano Armenta
# Contacto: dani.eus79@gmail.com
# GitHub: github.com/danitxu79
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
from pathlib import Path
import datetime
import locale
import warnings
import sqlite3
import time

import threading # Necesario para evitar que la UI se congele
from drive_auth import DriveAuthenticator
import requests # Para bajar thumbnails
from drive_manager import DriveManager
import config_manager # Para guardar la carpeta elegida

# --- Silenciar solo el aviso de pkg_resources ---
warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API",
    category=UserWarning,
)

import numpy as np
from sklearn.cluster import DBSCAN
import sklearn
import rawpy # Importar rawpy para soporte RAW
import cv2

from PySide6.QtWidgets import (
    QDialog, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QDialogButtonBox, QTreeWidget, QTreeWidgetItem,
    QComboBox, QMenu, QListWidget, QListWidgetItem, QFrame, QMessageBox
)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QStyle, QFileDialog,
    QScrollArea, QGridLayout, QLabel, QGroupBox, QSpacerItem, QSizePolicy,
    QSplitter, QTabWidget, QStackedWidget
)
from PySide6.QtCore import (
    Qt, QSize, QObject, Signal, QThread, Slot, QTimer,
    QRunnable, QThreadPool, QPropertyAnimation, QEasingCurve, QRect, QPoint, QRectF,
    QPointF, QBuffer, QIODevice, QUrl
)
from PySide6.QtGui import (
    QPixmap, QIcon, QCursor, QTransform, QPainter, QPaintEvent,
    QPainterPath, QKeyEvent, QDesktopServices, QImage
)

# --- MODIFICADO: Importar las funciones de foto Y vídeo ---
from photo_finder import find_photos, find_videos
import config_manager
from metadata_reader import get_photo_date, get_video_date
from thumbnail_generator import (
    generate_image_thumbnail, generate_video_thumbnail, THUMBNAIL_SIZE
)
# --- FIN DE MODIFICACIÓN ---

import metadata_reader
import piexif.helper
import re
import db_manager
from db_manager import VisageVaultDB
import face_recognition
from PIL import Image
import ast
import pickle

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
    thumbnail_loaded = Signal(str, QPixmap) # original_path, pixmap
    load_failed = Signal(str)

# =================================================================
# CLASE PARA CARGAR MINIATURAS DE IMAGEN (QRunnable)
# =================================================================
class ThumbnailLoader(QRunnable):
    """QRunnable para cargar una miniatura de IMAGEN de forma asíncrona."""

    def __init__(self, original_filepath: str, signals: ThumbnailLoaderSignals):
        super().__init__()
        self.original_filepath = original_filepath
        self.signals = signals

    @Slot()
    def run(self):
        # --- MODIFICADO: Llama a la función específica de IMAGEN ---
        thumbnail_path = generate_image_thumbnail(self.original_filepath)
        # --- FIN DE MODIFICACIÓN ---
        if thumbnail_path:
            try:
                pixmap = QPixmap(thumbnail_path)
                self.signals.thumbnail_loaded.emit(self.original_filepath, pixmap)
            except Exception:
                self.signals.load_failed.emit(self.original_filepath)
        else:
            self.signals.load_failed.emit(self.original_filepath)

# =================================================================
# CLASE PARA CARGAR MINIATURAS DE VÍDEO (QRunnable) - ¡NUEVA!
# =================================================================
class VideoThumbnailLoader(QRunnable):
    """QRunnable para cargar una miniatura de VÍDEO de forma asíncrona."""

    def __init__(self, original_filepath: str, signals: ThumbnailLoaderSignals):
        super().__init__()
        self.original_filepath = original_filepath
        self.signals = signals

    @Slot()
    def run(self):
        # --- MODIFICADO: Llama a la función específica de VÍDEO ---
        thumbnail_path = generate_video_thumbnail(self.original_filepath)
        # --- FIN DE MODIFICACIÓN ---
        if thumbnail_path:
            try:
                pixmap = QPixmap(thumbnail_path)
                self.signals.thumbnail_loaded.emit(self.original_filepath, pixmap)
            except Exception:
                self.signals.load_failed.emit(self.original_filepath)
        else:
            self.signals.load_failed.emit(self.original_filepath)

# =================================================================
# CLASE: NetworkThumbnailLoader (CON CACHÉ EN DISCO)
# =================================================================
class NetworkThumbnailLoader(QRunnable):
    """
    1. Mira si la miniatura ya existe en disco.
    2. Si existe, la carga al instante.
    3. Si no, la descarga, la guarda en disco y luego la carga.
    """
    def __init__(self, url, file_id, signals):
        super().__init__()
        self.url = url
        self.file_id = file_id
        self.signals = signals

        # Definir ruta de caché específica para Drive
        # Usamos .visagevault_cache/drive_thumbnails
        base_dir = os.path.dirname(os.path.abspath(__file__))
        # visagevault_cache/drive_snapshot_cache
        self.cache_dir = os.path.join(base_dir, "visagevault_cache", "drive_snapshot_cache")

        if not os.path.exists(self.cache_dir):
            try: os.makedirs(self.cache_dir)
            except: pass

        # Crear carpeta si no existe (hilo seguro porque makedirs es atómico o lanza error tolerable)
        if not os.path.exists(self.cache_dir):
            try:
                os.makedirs(self.cache_dir)
            except OSError:
                pass # Ya existía

    @Slot()
    def run(self):
        # Ruta del archivo: Usamos el ID de Google como nombre único
        cache_path = os.path.join(self.cache_dir, f"{self.file_id}.jpg")

        # --- 1. INTENTO DE CARGA DESDE CACHÉ (RÁPIDO) ---
        if os.path.exists(cache_path):
            # Verificar que no sea un archivo corrupto de 0 bytes
            if os.path.getsize(cache_path) > 0:
                try:
                    pixmap = QPixmap(cache_path)
                    if not pixmap.isNull():
                        self.signals.thumbnail_loaded.emit(self.file_id, pixmap)
                        return
                except Exception:
                    pass # Si falla la carga local, intentamos descargar de nuevo

            # Si llegamos aquí es que el archivo estaba corrupto o vacío
            try: os.remove(cache_path)
            except: pass

        # --- 2. DESCARGA DE LA RED (LENTO) ---
        if not self.url:
            return

        try:
            # Descargar
            response = requests.get(self.url, timeout=10)

            if response.status_code == 200:
                # 1. Guardar en disco para la próxima vez
                with open(cache_path, 'wb') as f:
                    f.write(response.content)

                # 2. Cargar en memoria para mostrar ahora
                pixmap = QPixmap()
                pixmap.loadFromData(response.content)

                if not pixmap.isNull():
                    self.signals.thumbnail_loaded.emit(self.file_id, pixmap)

        except Exception as e:
            # Si falla, no pasa nada, se queda con el icono de "Cargando" o genérico
            # print(f"Error descargando thumb {self.file_id}: {e}")
            pass

class DriveFolderDialog(QDialog):
    def __init__(self, drive_manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Navegador de Google Drive")
        self.resize(600, 450)
        self.drive = drive_manager

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

        # --- NUEVO: AVISO INFORMATIVO ---
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
            QApplication.setOverrideCursor(Qt.WaitCursor)
            folders = self.drive.list_folders(folder_id)
            QApplication.restoreOverrideCursor()

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
            from PySide6.QtWidgets import QMessageBox
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
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Aviso", "Por favor, entra en una carpeta específica para seleccionarla.")
            return

        self.selected_folder_id = self.current_folder_id
        self.selected_folder_name = self.current_folder_name
        self.accept()

# =================================================================
# SEÑALES Y WORKER PARA CARGAR Y RECORTAR CARAS (Sin cambios)
# =================================================================
class FaceLoaderSignals(QObject):
    face_loaded = Signal(int, QPixmap, str)
    face_load_failed = Signal(int)

# =================================================================
# WORKER PARA LOGIN DE GOOGLE DRIVE
# =================================================================
class DriveLoginWorker(QObject):
    """Worker para manejar la autenticación de Google Drive en segundo plano."""
    login_success = Signal(object)  # Emite el servicio de Drive
    login_failed = Signal(str)      # Emite mensaje de error
    finished = Signal()

    def __init__(self):
        super().__init__()

    @Slot()
    def run(self):
        try:
            from drive_auth import DriveAuthenticator
            auth = DriveAuthenticator()
            service = auth.get_service()
            self.login_success.emit(service)
        except FileNotFoundError as e:
            self.login_failed.emit(str(e))
        except Exception as e:
            print(f"Error de Login con Google: {e}")
            self.login_failed.emit(str(e))
        finally:
            self.finished.emit()

class DriveScanWorker(QObject):
    """
    Worker 'Silencioso' y Optimizado.
    1. Escanea Drive.
    2. Guarda en DB localmente (WAL mode).
    3. Solo avisa del progreso numérico para no congelar la UI.
    """
    progress = Signal(str)
    finished = Signal(int)

    def __init__(self, folder_id, db_path):
        super().__init__()
        self.folder_id = folder_id
        self.db_path = db_path
        self.is_running = True

    @Slot()
    def run(self):
        # --- CONFIGURACIÓN DE LA CONEXIÓN DB ---
        local_db = VisageVaultDB(os.path.basename(self.db_path), is_worker=True)
        local_db.db_path = self.db_path
        local_db.conn = sqlite3.connect(self.db_path, check_same_thread=False)

        # 1. Corrección para evitar bloqueos
        local_db.conn.execute("PRAGMA journal_mode=WAL;")
        # 2. Corrección para evitar errores de tuplas vs diccionarios
        local_db.conn.row_factory = sqlite3.Row

        try:
            from drive_manager import DriveManager
            local_manager = DriveManager()

            count = 0
            buffer = []
            BATCH_SIZE = 100

            # Usamos time.time() para controlar la frecuencia de actualización
            last_update_time = time.time()

            # Llamamos a la función recursiva (asegúrate de haber puesto el time.sleep en drive_manager.py)
            for batch_of_images in local_manager.list_images_recursively(self.folder_id):
                if not self.is_running:
                    break

                buffer.extend(batch_of_images)

                if len(buffer) >= BATCH_SIZE:
                    self._save_to_db(local_db, buffer)
                    count += len(buffer)
                    buffer = []

                    # Actualizar UI solo cada 1 segundo para evitar congelamiento
                    if time.time() - last_update_time > 1.0:
                        self.progress.emit(f"Indexando nube... {count} fotos guardadas.")
                        last_update_time = time.time()

                    # Pequeña pausa para ceder CPU
                    time.sleep(0.05)

            # Guardar lo restante al final
            if buffer:
                self._save_to_db(local_db, buffer)
                count += len(buffer)

            self.progress.emit(f"Finalizado. Total: {count} fotos.")
            self.finished.emit(count)

        except Exception as e:
            print(f"❌ ERROR FATAL EN WORKER DRIVE: {e}")
            import traceback
            traceback.print_exc()
            self.finished.emit(0)
        finally:
            try: local_db.conn.close()
            except: pass

    def _save_to_db(self, db_instance, items):
        """Guarda el lote en la base de datos de forma segura."""
        try:
            db_instance.bulk_upsert_drive_photos(items, root_folder_id=self.folder_id)
        except Exception as e:
            print(f"Error guardando en DB Drive: {e}")

class FaceScanWorker(QObject):
    def __init__(self, db_path: str):
        super().__init__()
        self.db_path = db_path
        self.signals = FaceScanSignals()
        self.is_running = True

    @Slot()
    def run(self):
        # Configuración de la DB en el hilo
        local_db = VisageVaultDB(os.path.basename(self.db_path), is_worker=True)
        local_db.db_path = self.db_path
        local_db.conn = sqlite3.connect(self.db_path, check_same_thread=False)

        # --- CORRECCIÓN CRÍTICA ---
        local_db.conn.row_factory = sqlite3.Row  # <--- ¡ESTA ES LA LÍNEA QUE FALTABA!
        # --------------------------

        local_db.conn.execute("PRAGMA journal_mode=WAL;")

        try:
            self.signals.scan_progress.emit("Buscando fotos sin escanear...")

            # Ahora esto funcionará porque row_factory convierte las tuplas en objetos accesibles por nombre
            unscanned_photos = local_db.get_unscanned_photos()

            total = len(unscanned_photos)
            if total == 0:
                self.signals.scan_progress.emit("No hay fotos nuevas para analizar.")
                self.signals.scan_percentage.emit(100)
                self.signals.scan_finished.emit()
                return

            self.signals.scan_progress.emit(f"Escaneando {total} fotos nuevas para caras...")

            # Extensiones RAW
            RAW_EXTENSIONS = ('.nef', '.cr2', '.cr3', '.crw', '.arw', '.srf', '.orf', '.rw2', '.raf', '.pef', '.dng', '.raw')

            for i, row in enumerate(unscanned_photos):
                if not self.is_running: break

                # AQUÍ DABA EL ERROR ANTES: row['id'] fallaba sin row_factory
                photo_id = row['id']
                photo_path = row['filepath']

                # Actualizar barra de progreso con menos frecuencia (cada 5 fotos)
                if i % 5 == 0:
                    percentage = (i + 1) * 100 // total
                    self.signals.scan_percentage.emit(percentage)
                    self.signals.scan_progress.emit(f"Analizando caras ({i+1}/{total})...")
                    time.sleep(0.001)

                try:
                    image = None
                    file_suffix = Path(photo_path).suffix.lower()

                    # 1. Cargar Imagen (Soporte RAW + Standard)
                    if file_suffix in RAW_EXTENSIONS:
                        try:
                            with rawpy.imread(photo_path) as raw:
                                image = raw.postprocess()
                        except Exception:
                            local_db.mark_photo_as_scanned(photo_id)
                            continue
                    else:
                        image = face_recognition.load_image_file(photo_path)

                    if image is None:
                        local_db.mark_photo_as_scanned(photo_id)
                        continue

                    # 2. Optimización: Redimensionar si es gigante
                    h, w = image.shape[:2]
                    max_width = 1000
                    scale_ratio = 1.0

                    if w > max_width:
                        scale_ratio = max_width / float(w)
                        new_h = int(h * scale_ratio)
                        image = cv2.resize(image, (max_width, new_h))

                    # 3. Detectar caras
                    locations = face_recognition.face_locations(image)

                    if locations:
                        encodings = face_recognition.face_encodings(image, locations)

                        for loc, enc in zip(locations, encodings):
                            # Restaurar coordenadas originales si hubo redimensionado
                            if scale_ratio != 1.0:
                                top, right, bottom, left = loc
                                top = int(top / scale_ratio)
                                right = int(right / scale_ratio)
                                bottom = int(bottom / scale_ratio)
                                left = int(left / scale_ratio)
                                loc = (top, right, bottom, left)

                            location_str = str(loc)
                            encoding_blob = pickle.dumps(enc)

                            # Guardar cara encontrada
                            face_db_id = local_db.add_face(photo_id, encoding_blob, location_str)
                            self.signals.face_found.emit(face_db_id, photo_path, location_str)

                    # Marcar foto como procesada
                    local_db.mark_photo_as_scanned(photo_id)

                except Exception as e:
                    print(f"Error procesando caras en {photo_path}: {e}")
                    local_db.mark_photo_as_scanned(photo_id)

            self.signals.scan_progress.emit("Escaneo de caras finalizado.")
            self.signals.scan_finished.emit()

        except Exception as e:
            print(f"Error crítico worker caras: {e}")
            self.signals.scan_progress.emit(f"Error: {e}")
            self.signals.scan_finished.emit()
        finally:
            local_db.conn.close()

# =================================================================
# CLASE OPTIMIZADA: CARGA DE CARAS CON CACHÉ DE DISCO
# =================================================================
class FaceLoader(QRunnable):
    def __init__(self, signals: FaceLoaderSignals, face_id: int, photo_path: str, location_str: str):
        super().__init__()
        self.signals = signals
        self.face_id = face_id
        self.photo_path = photo_path
        self.location_str = location_str
        base_dir = os.path.dirname(os.path.abspath(__file__))
        # visagevault_cache/face_cache
        self.cache_dir = os.path.join(base_dir, "visagevault_cache", "face_cache")

        if not os.path.exists(self.cache_dir):
            try: os.makedirs(self.cache_dir)
            except: pass

        self.cache_path = os.path.join(self.cache_dir, f"face_{self.face_id}.jpg")

    @Slot()
    def run(self):
        try:
            pixmap = QPixmap()

            # 1. INTENTO DE CARGA RÁPIDA (CACHÉ)
            # Si el archivo pequeño ya existe, lo cargamos y terminamos. ¡Instantáneo!
            if os.path.exists(self.cache_path):
                if pixmap.load(self.cache_path):
                    self.signals.face_loaded.emit(self.face_id, pixmap, self.photo_path)
                    return

            # 2. SI NO EXISTE CACHÉ: PROCESO LENTO (Abrir original y recortar)
            location = ast.literal_eval(self.location_str)
            (top, right, bottom, left) = location

            RAW_EXTENSIONS = ('.nef', '.cr2', '.cr3', '.crw', '.arw', '.srf', '.orf', '.rw2', '.raf', '.pef', '.dng', '.raw')
            file_suffix = Path(self.photo_path).suffix.lower()

            img = None

            if file_suffix in RAW_EXTENSIONS:
                try:
                    with rawpy.imread(self.photo_path) as raw:
                        rgb_array = raw.postprocess()
                        img = Image.fromarray(rgb_array)
                except Exception as e:
                    print(f"Error rawpy en FaceLoader: {e}")
                    raise e
            else:
                img = Image.open(self.photo_path)

            if img is None:
                raise Exception("No se pudo cargar la imagen base")

            # Recortar la cara
            face_image_pil = img.crop((left, top, right, bottom))

            # 3. GUARDAR EN CACHÉ (Para que la próxima vez sea rápido)
            try:
                # Convertimos a RGB por si acaso (para guardar en JPG)
                if face_image_pil.mode != "RGB":
                    face_image_pil = face_image_pil.convert("RGB")

                # Guardamos el recorte en la carpeta face_cache
                face_image_pil.save(self.cache_path, "JPEG", quality=90)
            except Exception as e:
                print(f"No se pudo guardar caché para cara {self.face_id}: {e}")

            # 4. Convertir a QPixmap para mostrar ahora mismo
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.ReadWrite)
            face_image_pil.save(buffer, "PNG")
            pixmap.loadFromData(buffer.data())
            buffer.close()

            if pixmap.isNull():
                raise Exception("QPixmap nulo después de la conversión.")

            self.signals.face_loaded.emit(self.face_id, pixmap, self.photo_path)

        except Exception as e:
            # Si falla, emitimos señal de fallo pero no rompemos el programa
            # print(f"Error en FaceLoader (ID: {self.face_id}): {e}")
            self.signals.face_load_failed.emit(self.face_id)

# =================================================================
# SEÑALES Y WORKER PARA AGRUPAR CARAS (CLUSTERING) (Sin cambios)
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
        local_db = VisageVaultDB(os.path.basename(self.db_path), is_worker=True)
        local_db.db_path = self.db_path
        local_db.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        local_db.conn.row_factory = sqlite3.Row

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
# CLASE PARA VISTA PREVIA CON ZOOM (QDialog) (Sin cambios)
# =================================================================
class ImagePreviewDialog(QDialog):
    is_showing = False
    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        ImagePreviewDialog.is_showing = True
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._pixmap = pixmap
        self.label = ZoomableClickableLabel(self)
        self.label.is_thumbnail_view = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        self.animation = QPropertyAnimation(self, b"geometry")
    def show_with_animation(self):
        screen = QApplication.screenAt(QCursor.pos())
        if not screen:
            screen = QApplication.primaryScreen()
        screen_geom = screen.availableGeometry()
        img_size = self._pixmap.size()
        max_width = int(screen_geom.width() * 0.9)
        max_height = int(screen_geom.height() * 0.9)
        target_size = img_size
        if img_size.width() > max_width or img_size.height() > max_height:
            target_size = img_size.scaled(max_width, max_height, Qt.KeepAspectRatio)
        self.label.setOriginalPixmap(self._pixmap)
        self.resize(target_size)
        center_x = screen_geom.x() + (screen_geom.width() - target_size.width()) // 2
        center_y = screen_geom.y() + (screen_geom.height() - target_size.height()) // 2
        self.move(center_x, center_y)
        self.show()
    def close_with_animation(self):
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
        ImagePreviewDialog.is_showing = False
        self.accept()
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Escape:
            self.close_with_animation()
        else:
            super().keyPressEvent(event)
    def resizeEvent(self, event):
        if self.label._current_scale == 1.0:
            self.label.fitToWindow()
        super().resizeEvent(event)

# =================================================================
# CLASE: PreviewListWidget
# =================================================================
# =================================================================
# CLASE: PreviewListWidget (LIMPIA)
# =================================================================
class PreviewListWidget(QListWidget):
    """
    QListWidget personalizado:
    1. Doble Clic -> Abre Vista Previa.
    2. ESC -> Cierra Vista Previa activa.
    3. Shift+Clic -> Selección múltiple lineal.
    """
    previewRequested = Signal(object)

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
            from PySide6.QtWidgets import QApplication
            for widget in QApplication.allWidgets():
                if isinstance(widget, ImagePreviewDialog) and widget.isVisible():
                    if hasattr(widget, 'close_with_animation'):
                        widget.close_with_animation()
                    else:
                        widget.close()
                    event.accept()
                    return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
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

# =================================================================
# CLASE PARA MOSTRAR CARAS RECORTADAS (Sin cambios)
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
# CLASE: ZoomableClickableLabel (Sin cambios)
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
        self._current_scale = 1.0
        self._view_offset = QPointF(0.0, 0.0)
        self.fitToWindow()
    def fitToWindow(self):
        if self._original_pixmap.isNull():
            self.setPixmap(QPixmap())
            return
        scaled_pixmap = self._original_pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        if self._original_pixmap.width() > 0:
            self._current_scale = scaled_pixmap.width() / self._original_pixmap.width()
        else:
            self._current_scale = 1.0
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
                    parent_dialog = self.window()
                    if isinstance(parent_dialog, ImagePreviewDialog):
                        parent_dialog.close_with_animation()
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
        if event.button() == Qt.LeftButton and not self.is_thumbnail_view:
            self._panning = True
            self._last_mouse_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)
    def mouseMoveEvent(self, event):
        if self._panning and not self.is_thumbnail_view:
            delta = event.position().toPoint() - self._last_mouse_pos
            self._view_offset -= QPointF(delta.x() / self._current_scale, delta.y() / self._current_scale)
            self._last_mouse_pos = event.position().toPoint()
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
        if self.is_thumbnail_view and self.original_path:
            self.doubleClickedPath.emit(self.original_path)
        if not self.is_thumbnail_view:
            self.fitToWindow()
        super().mouseDoubleClickEvent(event)
    def _clamp_view_offset(self):
        if self._original_pixmap.isNull() or self._current_scale == 0: return
        scaled_img_width = self._original_pixmap.width() * self._current_scale
        scaled_img_height = self._original_pixmap.height() * self._current_scale
        if scaled_img_width < self.width():
            self._view_offset.setX(0)
        else:
            max_x_offset = self._original_pixmap.width() - (self.width() / self._current_scale)
            self._view_offset.setX(max(0.0, min(self._view_offset.x(), max_x_offset)))
        if scaled_img_height < self.height():
            self._view_offset.setY(0)
        else:
            max_y_offset = self._original_pixmap.height() - (self.height() / self._current_scale)
            self._view_offset.setY(max(0.0, min(self._view_offset.y(), max_y_offset)))
    def paintEvent(self, event: QPaintEvent):
        if self.is_thumbnail_view:
            super().paintEvent(event)
            return
        if self._original_pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        scaled_width = self._original_pixmap.width() * self._current_scale
        scaled_height = self._original_pixmap.height() * self._current_scale
        target_x = 0.0
        target_y = 0.0
        if scaled_width < self.width():
            target_x = (self.width() - scaled_width) / 2.0
        if scaled_height < self.height():
            target_y = (self.height() - scaled_height) / 2.0
        target_rect = QRectF(target_x, target_y, scaled_width, scaled_height)
        src_x = self._view_offset.x()
        src_y = self._view_offset.y()
        src_width = self.width() / self._current_scale
        src_height = self.height() / self._current_scale
        if scaled_width < self.width():
            src_width = self._original_pixmap.width()
        if scaled_height < self.height():
            src_height = self._original_pixmap.height()
        source_rect = QRectF(src_x, src_y, src_width, src_height)
        painter.drawPixmap(target_rect, self._original_pixmap, source_rect)
        painter.end()
    def resizeEvent(self, event):
        if not self.is_thumbnail_view:
            self.fitToWindow()
        super().resizeEvent(event)
    def _open_preview(self):
        if ImagePreviewDialog.is_showing:
            return
        if not self.original_path:
            return
        full_pixmap = QPixmap(self.original_path)
        if full_pixmap.isNull():
            return
        preview_dialog = ImagePreviewDialog(full_pixmap, self)
        preview_dialog.show_with_animation()

# -----------------------------------------------------------------
# CLASE MODIFICADA: PhotoDetailDialog (¡CON SOPORTE RAW!)
# -----------------------------------------------------------------
class PhotoDetailDialog(QDialog):
    metadata_changed = Signal(str, str, str)
    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        self.main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.main_splitter)
        self.image_label = ZoomableClickableLabel(self.original_path, self)
        self.image_label.is_thumbnail_view = False
        self.main_splitter.addWidget(self.image_label)
        right_panel_widget = QWidget()
        right_panel_layout = QVBoxLayout(right_panel_widget)
        right_panel_widget.setMinimumWidth(300)
        right_panel_widget.setMaximumWidth(450)
        date_group = QGroupBox("Fecha (Base de Datos)")
        date_layout = QGridLayout(date_group)
        date_layout.addWidget(QLabel("Año:"), 0, 0)
        self.year_edit = QLineEdit()
        self.year_edit.setPlaceholderText("Ej: 2024 o 'Sin Fecha'")
        date_layout.addWidget(self.year_edit, 0, 1)
        date_layout.addWidget(QLabel("Mes:"), 1, 0)
        self.month_combo = QComboBox()
        self.month_combo.addItem("Mes Desconocido", "00")
        for i in range(1, 13):
            month_str = str(i).zfill(2)
            try:
                month_name = datetime.datetime.strptime(month_str, "%m").strftime("%B").capitalize()
            except ValueError:
                month_name = datetime.date(2000, i, 1).strftime("%B").capitalize()
            self.month_combo.addItem(month_name, month_str)
        date_layout.addWidget(self.month_combo, 1, 1)
        exif_group = QGroupBox("Datos EXIF (Solo Lectura)")
        exif_layout = QVBoxLayout(exif_group)
        self.metadata_table = QTableWidget()
        self.metadata_table.setColumnCount(2)
        self.metadata_table.setHorizontalHeaderLabels(["Campo", "Valor"])
        self.metadata_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.metadata_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.metadata_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        exif_layout.addWidget(self.metadata_table)
        right_panel_layout.addWidget(date_group)
        right_panel_layout.addWidget(exif_group, 1)
        self.main_splitter.addWidget(right_panel_widget)
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self._save_metadata)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)
        self.main_splitter.setSizes([int(self.width() * 0.7), int(self.width() * 0.3)])
    def __init__(self, original_path, db_manager: VisageVaultDB, parent=None):
        super().__init__(parent)
        self.original_path = original_path
        self.db = db_manager
        self.exif_dict = {}
        self.date_time_tag_info = None
        self.setWindowTitle(Path(original_path).name)
        self.resize(1000, 800)
        self._setup_ui()
        self._load_photo()
        self._load_metadata()
    def _load_photo(self):
        try:
            # Definir extensiones RAW (deben coincidir con las de los otros archivos)
            RAW_EXTENSIONS = ('.nef', '.cr2', '.cr3', '.crw', '.arw', '.srf', '.orf', '.rw2', '.raf', '.pef', '.dng', '.raw')
            file_suffix = Path(self.original_path).suffix.lower()
            pixmap = QPixmap() # Empezar con un pixmap vacío

            if file_suffix in RAW_EXTENSIONS:
                # 1. Usar rawpy para leer el archivo RAW
                with rawpy.imread(self.original_path) as raw:
                    # postprocess() aplica correcciones de color y devuelve un array numpy (H, W, 3)
                    rgb_array = raw.postprocess()

                # 2. Convertir el array de numpy a QImage
                height, width, channel = rgb_array.shape
                bytes_per_line = 3 * width
                # .copy() es crucial para que QImage tome propiedad de los datos
                q_image = QImage(rgb_array.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()

                # 3. Convertir QImage a QPixmap
                pixmap = QPixmap.fromImage(q_image)

            else:
                # 4. Lógica original para JPG, PNG, etc.
                pixmap = QPixmap(self.original_path)

            if pixmap.isNull():
                raise Exception("QPixmap está vacío después de cargar (formato no soportado o archivo corrupto).")

            self.image_label.setOriginalPixmap(pixmap)

        except Exception as e:
            print(f"Error detallado al cargar {self.original_path}: {e}")
            self.image_label.setText(f"Error al cargar imagen: {e}")

    def _load_metadata(self):
        self.exif_dict = metadata_reader.get_exif_dict(self.original_path)
        self.metadata_table.setRowCount(0)
        current_year, current_month = self.db.get_photo_date(self.original_path)
        if current_year is None or current_month is None:
            exif_year, exif_month = metadata_reader.get_photo_date(self.original_path)
            if current_year is None:
                current_year = exif_year
            if current_month is None:
                current_month = exif_month
        self.year_edit.setText(current_year or "Sin Fecha")
        month_index = self.month_combo.findData(current_month or "00")
        self.month_combo.setCurrentIndex(month_index if month_index != -1 else 0)
        if not self.exif_dict:
            self.metadata_table.insertRow(0)
            self.metadata_table.setItem(0, 0, QTableWidgetItem("Info"))
            self.metadata_table.setItem(0, 1, QTableWidgetItem("No se encontraron metadatos EXIF."))
            return
        row = 0
        for ifd_name, tags in self.exif_dict.items():
            if not isinstance(tags, dict): continue
            for tag_id, value in tags.items():
                self.metadata_table.insertRow(row)
                tag_name = piexif.TAGS[ifd_name].get(tag_id, {"name": f"UnknownTag_{tag_id}"})["name"]
                if isinstance(value, bytes):
                    try: value_str = piexif.helper.decode_bytes(value)
                    except: value_str = str(value)
                else:
                    value_str = str(value)
                self.metadata_table.setItem(row, 0, QTableWidgetItem(tag_name))
                self.metadata_table.setItem(row, 1, QTableWidgetItem(value_str))
                row += 1
    def _save_metadata(self):
        try:
            new_year_str = self.year_edit.text()
            new_month_str = self.month_combo.currentData()
            if not (new_year_str == "Sin Fecha" or (len(new_year_str) == 4 and new_year_str.isdigit())):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self,
                                    "Datos Inválidos",
                                    "El Año debe ser 'Sin Fecha' o un número de 4 dígitos (ej: 2024).")
                return
            old_year, old_month = self.db.get_photo_date(self.original_path)
            if old_year != new_year_str or old_month != new_month_str:
                self.db.update_photo_date(self.original_path, new_year_str, new_month_str)
                self.metadata_changed.emit(self.original_path, new_year_str, new_month_str)
            self.accept()
        except Exception as e:
            print(f"Error al guardar la fecha en la BD: {e}")

# =================================================================
# CLASE: DIÁLOGO DE ETIQUETADO DE GRUPOS (CLUSTERS) (Sin cambios)
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
                from PySide6.QtWidgets import QMessageBox
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
    @Slot(int, QPixmap, str)
    def _on_dialog_face_loaded(self, face_id: int, pixmap: QPixmap, photo_path: str):
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
        RAW_EXTENSIONS = ('.nef', '.cr2', '.cr3', '.crw', '.arw', '.srf', '.orf', '.rw2', '.raf', '.pef', '.dng', '.raw')
        file_suffix = Path(photo_path).suffix.lower()

        full_pixmap = QPixmap()

        try:
            if file_suffix in RAW_EXTENSIONS:
                # Procesar con rawpy
                with rawpy.imread(photo_path) as raw:
                    rgb_array = raw.postprocess()

                height, width, channel = rgb_array.shape
                bytes_per_line = 3 * width
                q_image = QImage(rgb_array.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()
                full_pixmap = QPixmap.fromImage(q_image)
            else:
                # Procesar estándar
                full_pixmap = QPixmap(photo_path)

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
            from PySide6.QtWidgets import QMessageBox # Asegurar import
            QMessageBox.warning(self, "Año incorrecto", "Por favor, escribe un año válido de 4 cifras (ej: 2025).")
            return

        self.accept()

    def get_data(self):
        return self.year_edit.text().strip(), self.month_combo.currentData()

# =================================================================
# CLASE TRABAJADORA DEL ESCANEO DE FOTOS (Sin cambios)
# =================================================================
class PhotoFinderWorker(QObject):
    finished = Signal(dict)
    progress = Signal(str)

    # Recibimos db_path (texto) en lugar de db_manager (objeto)
    def __init__(self, directory_path: str, db_path: str):
        super().__init__()
        self.directory_path = directory_path
        self.db_path = db_path
        self.is_running = True

    @Slot()
    def run(self):
        # Abrimos nuestra propia conexión segura
        local_db = VisageVaultDB(os.path.basename(self.db_path), is_worker=True)
        # Forzamos que use la ruta correcta si no coincide con el default
        local_db.db_path = self.db_path
        local_db.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        local_db.conn.row_factory = sqlite3.Row

        photos_by_year_month = {}
        try:
            self.progress.emit("Cargando fechas de fotos conocidas desde la BD...")
            db_dates = local_db.load_all_photo_dates()

            self.progress.emit("Escaneando archivos de FOTOS en el directorio...")
            photo_paths_on_disk = find_photos(self.directory_path)
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

                if year not in photos_by_year_month:
                    photos_by_year_month[year] = {}
                if month not in photos_by_year_month[year]:
                    photos_by_year_month[year][month] = []
                photos_by_year_month[year][month].append(path)

            self.progress.emit("Buscando fotos eliminadas...")
            db_paths_set = set(db_dates.keys())
            paths_to_delete = list(db_paths_set - photo_paths_on_disk_set)

            if paths_to_delete:
                self.progress.emit(f"Eliminando {len(paths_to_delete)} fotos de la BD...")
                local_db.bulk_delete_photos(paths_to_delete)

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
            self.finished.emit(photos_by_year_month)

# =================================================================
# CLASE TRABAJADORA DEL ESCANEO DE VÍDEOS (Sin cambios)
# =================================================================
class VideoFinderWorker(QObject):
    finished = Signal(dict)
    progress = Signal(str)

    def __init__(self, directory_path: str, db_path: str):
        super().__init__()
        self.directory_path = directory_path
        self.db_path = db_path
        self.is_running = True

    @Slot()
    def run(self):
        local_db = VisageVaultDB(os.path.basename(self.db_path), is_worker=True)
        local_db.db_path = self.db_path
        local_db.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        local_db.conn.row_factory = sqlite3.Row

        videos_by_year_month = {}
        try:
            self.progress.emit("Cargando fechas de vídeos conocidas desde la BD...")
            db_dates = local_db.load_all_video_dates()

            self.progress.emit("Escaneando archivos de VÍDEOS en el directorio...")
            video_paths_on_disk = find_videos(self.directory_path)
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

                if year not in videos_by_year_month:
                    videos_by_year_month[year] = {}
                if month not in videos_by_year_month[year]:
                    videos_by_year_month[year][month] = []
                videos_by_year_month[year][month].append(path)

            self.progress.emit("Buscando vídeos eliminados...")
            db_paths_set = set(db_dates.keys())
            paths_to_delete = list(db_paths_set - video_paths_on_disk_set)

            if paths_to_delete:
                self.progress.emit(f"Eliminando {len(paths_to_delete)} vídeos de la BD...")
                local_db.bulk_delete_videos(paths_to_delete)

            if videos_to_upsert_in_db:
                self.progress.emit(f"Guardando {len(videos_to_upsert_in_db)} vídeos nuevos en la BD...")
                local_db.bulk_upsert_videos(videos_to_upsert_in_db)

            self.progress.emit(f"Escaneo de vídeos finalizado. Encontrados {len(video_paths_on_disk)} vídeos.")

        except Exception as e:
            print(f"Error crítico en el hilo VideoFinderWorker: {e}")
            self.progress.emit(f"Error en escaneo de vídeos: {e}")
        finally:
            local_db.conn.close()
            self.finished.emit(videos_by_year_month)

# =================================================================
# CLASE TRABAJADORA DEL ESCANEO DE CARAS (¡CON SOPORTE RAW!)
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

    @Slot()
    def run(self):
        local_db = VisageVaultDB(os.path.basename(self.db_path), is_worker=True)
        local_db.db_path = self.db_path
        local_db.conn = sqlite3.connect(self.db_path, check_same_thread=False)

        # Intentamos poner esto por si acaso, pero usaremos índices numéricos para asegurar
        local_db.conn.row_factory = sqlite3.Row
        local_db.conn.execute("PRAGMA journal_mode=WAL;")

        try:
            self.signals.scan_progress.emit("Buscando fotos sin escanear...")
            unscanned_photos = local_db.get_unscanned_photos()

            total = len(unscanned_photos)
            if total == 0:
                self.signals.scan_progress.emit("No hay fotos nuevas para analizar.")
                self.signals.scan_percentage.emit(100)
                self.signals.scan_finished.emit()
                return

            self.signals.scan_progress.emit(f"Escaneando {total} fotos nuevas para caras...")
            RAW_EXTENSIONS = ('.nef', '.cr2', '.cr3', '.crw', '.arw', '.srf', '.orf', '.rw2', '.raf', '.pef', '.dng', '.raw')

            for i, row in enumerate(unscanned_photos):
                if not self.is_running: break

                # --- CAMBIO BLINDADO AQUÍ ---
                # Usamos índices numéricos. Esto funciona SIEMPRE (tupla o Row)
                # La consulta SQL es "SELECT id, filepath...", así que:
                # 0 = id
                # 1 = filepath
                photo_id = row[0]
                photo_path = row[1]
                # ----------------------------

                if i % 5 == 0:
                    percentage = (i + 1) * 100 // total
                    self.signals.scan_percentage.emit(percentage)
                    self.signals.scan_progress.emit(f"Analizando caras ({i+1}/{total})...")
                    time.sleep(0.001)

                try:
                    image = None
                    file_suffix = Path(photo_path).suffix.lower()

                    if file_suffix in RAW_EXTENSIONS:
                        try:
                            with rawpy.imread(photo_path) as raw:
                                image = raw.postprocess()
                        except Exception:
                            local_db.mark_photo_as_scanned(photo_id)
                            continue
                    else:
                        image = face_recognition.load_image_file(photo_path)

                    if image is None:
                        local_db.mark_photo_as_scanned(photo_id)
                        continue

                    # Redimensionar para velocidad
                    h, w = image.shape[:2]
                    max_width = 1000
                    scale_ratio = 1.0
                    if w > max_width:
                        scale_ratio = max_width / float(w)
                        new_h = int(h * scale_ratio)
                        image = cv2.resize(image, (max_width, new_h))

                    locations = face_recognition.face_locations(image)

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

                            location_str = str(loc)
                            encoding_blob = pickle.dumps(enc)
                            face_db_id = local_db.add_face(photo_id, encoding_blob, location_str)
                            self.signals.face_found.emit(face_db_id, photo_path, location_str)

                    local_db.mark_photo_as_scanned(photo_id)

                except Exception as e:
                    print(f"Error procesando caras en {photo_path}: {e}")
                    local_db.mark_photo_as_scanned(photo_id)

            self.signals.scan_progress.emit("Escaneo de caras finalizado.")
            self.signals.scan_finished.emit()

        except Exception as e:
            print(f"Error crítico worker caras: {e}")
            import traceback
            traceback.print_exc()
            self.signals.scan_finished.emit()
        finally:
            try: local_db.conn.close()
            except: pass

# =================================================================
# CLASE: DIÁLOGO DE AYUDA Y ACERCA DE
# =================================================================
class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ayuda y Acerca de VisageVault")
        self.setFixedSize(500, 600)

        layout = QVBoxLayout(self)

        # 1. Logo
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignCenter)
        # Usamos resource_path para que funcione en el .exe compilado
        logo_path = resource_path("visagevault.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            logo_label.setPixmap(pixmap.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(logo_label)

        # 2. Título y Versión
        title_label = QLabel("<h2>VisageVault v1.4</h2>")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # 3. Texto de Ayuda (HTML)
        help_text = """
        <style>
            p { margin-bottom: 10px; line-height: 1.4; }
            a { color: #3daee9; text-decoration: none; font-weight: bold; }
        </style>

        <h3>📖 Guía Rápida</h3>
        <p><b>📷 Fotos / 🎥 Vídeos:</b> Navega por tus recuerdos organizados por fecha.
        Haz <b>doble clic</b> para ver en detalle. Usa <b>Ctrl+Rueda</b> para zoom.</p>

        <p><b>👥 Personas:</b> La IA agrupa caras automáticamente.
        Entra en esta pestaña para etiquetar a tus amigos y familiares.</p>

        <p><b>🖱️ Acciones:</b> Haz <b>Clic Derecho</b> en una foto o vídeo para:
        <ul>
            <li>Cambiar su fecha (y actualizar el archivo).</li>
            <li>Ocultarlo de la vista principal.</li>
            <li>Eliminarlo permanentemente.</li>
        </ul>
        </p>

        <hr>

        <h3>📬 Contacto y Soporte</h3>
        <p>Desarrollado por <b>Daniel Serrano Armenta</b>.</p>

        <p>🐙 <b>GitHub:</b><br>
        <a href="https://github.com/danitxu79/VisageVault">github.com/danitxu79/VisageVault</a></p>

        <p>📧 <b>Email:</b><br>
        <a href="mailto:dani.eus79@gmail.com">dani.eus79@gmail.com</a></p>
        """

        info_label = QLabel(help_text)
        info_label.setWordWrap(True)
        info_label.setOpenExternalLinks(True) # ¡Importante para que funcionen los links!
        info_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        info_label.setTextInteractionFlags(Qt.TextBrowserInteraction)

        # Área de scroll por si el texto es largo
        scroll = QScrollArea()
        scroll.setWidget(info_label)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(scroll)

        # 4. Botón Cerrar
        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.accept)
        layout.addWidget(btn_box)

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
        def __init__(self, signal):
            self.signal = signal
            self.last_emit_time = 0

        def on_any_event(self, event):
            # Ignorar directorios y archivos temporales o de caché
            if event.is_directory:
                return

            filename = os.path.basename(event.src_path)
            if filename.startswith('.') or "face_cache" in event.src_path:
                return

            # Comprobar extensiones relevantes (Fotos y Vídeos)
            valid_exts = (
                '.jpg', '.jpeg', '.png', '.tiff', '.webp', '.heic', '.nef', '.cr2', '.dng', '.raw', # Fotos
                '.mp4', '.avi', '.mkv', '.mov' # Vídeos
            )
            if not filename.lower().endswith(valid_exts):
                return

            # Debounce: Evitar emitir 100 señales si copias 100 fotos de golpe
            # Emitimos la señal y dejamos que la App gestione el refresco con un Timer
            self.signal.emit()

# =================================================================
# VENTANA PRINCIPAL DE LA APLICACIÓN (VisageVaultApp)
# =================================================================
class VisageVaultApp(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("VisageVault")
        icon_path = resource_path("visagevault.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            print(f"Advertencia: No se pudo encontrar el icono en {icon_path}")

        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.root_cache = os.path.join(base_dir, "visagevault_cache")

        # Creamos la estructura si no existe
        os.makedirs(os.path.join(self.root_cache, "face_cache"), exist_ok=True)
        os.makedirs(os.path.join(self.root_cache, "drive_cache"), exist_ok=True)
        os.makedirs(os.path.join(self.root_cache, "drive_snapshot_cache"), exist_ok=True)

        # Referencia para compatibilidad si se usa self.cache_dir en algún sitio antiguo
        self.cache_dir = self.root_cache

        self.refresh_timer = QTimer()
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(2000) # Esperar 2 segundos de inactividad antes de refrescar
        self.refresh_timer.timeout.connect(self._perform_auto_refresh)

        self.file_watcher = None

        self.setMinimumSize(QSize(900, 600))
        self.db = VisageVaultDB()
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


        # --- Variables de Vídeos (NUEVO) ---
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
        self.cloud_photo_count = 0
        self.current_drive_folder_id = None
        self.drive_scan_thread = None
        self.drive_scan_worker = None
        self.drive_loaded_ids = set()

        # --- Hilos y Señales ---
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(os.cpu_count() or 4)

        # Usamos la MISMA señal para todas las miniaturas (fotos, vídeos, caras)
        self.thumb_signals = ThumbnailLoaderSignals()
        self.thumb_signals.thumbnail_loaded.connect(self._update_thumbnail)
        self.thumb_signals.load_failed.connect(self._handle_thumbnail_failed)

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
        QTimer.singleShot(100, self._initial_check)


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

        # Panel Izquierdo (Fotos)
        photo_area_widget = QWidget()
        self.photo_container_layout = QVBoxLayout(photo_area_widget)
        self.photo_container_layout.setSpacing(0) # Sin espacio entre widgets
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(photo_area_widget)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._load_main_visible_thumbnails)
        self.main_splitter.addWidget(self.scroll_area)

        # Panel Derecho (Navegación de Fotos)
        photo_right_panel_widget = QWidget()
        photo_right_panel_layout = QVBoxLayout(photo_right_panel_widget)

        # Controles superiores (Botón y Path)
        top_controls = QVBoxLayout()
        self.select_dir_button = QPushButton("Cambiar Directorio")
        self.select_dir_button.clicked.connect(self._open_directory_dialog)
        top_controls.addWidget(self.select_dir_button)
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

        # self.status_label = QLabel("Estado: Inicializando...")
        # photo_right_panel_layout.addWidget(self.status_label)
        self.main_splitter.addWidget(photo_right_panel_widget)

        fotos_layout.addWidget(self.main_splitter)

        # ==========================================================
        # 3. Pestaña "Vídeos" - ¡NUEVA!
        # ==========================================================
        videos_tab_widget = QWidget()
        videos_layout = QVBoxLayout(videos_tab_widget)
        videos_layout.setContentsMargins(0, 0, 0, 0)

        self.video_splitter = QSplitter(Qt.Horizontal)

        # Panel Izquierdo (Vídeos)
        video_area_widget = QWidget()
        self.video_container_layout = QVBoxLayout(video_area_widget)
        self.video_container_layout.setSpacing(0) # Sin espacio entre widgets
        self.video_scroll_area = QScrollArea()
        self.video_scroll_area.setWidgetResizable(True)
        self.video_scroll_area.setWidget(video_area_widget)
        self.video_scroll_area.verticalScrollBar().valueChanged.connect(self._load_visible_video_thumbnails)
        self.video_splitter.addWidget(self.video_scroll_area)

        # Panel Derecho (Navegación de Vídeos)
        video_right_panel_widget = QWidget()
        video_right_panel_layout = QVBoxLayout(video_right_panel_widget)

        # (No necesitamos el botón de cambiar directorio aquí, solo el árbol)
        video_year_label = QLabel("Navegación por Fecha (Vídeos):")
        video_right_panel_layout.addWidget(video_year_label)
        self.video_date_tree_widget = QTreeWidget()
        self.video_date_tree_widget.setHeaderHidden(True)
        self.video_date_tree_widget.currentItemChanged.connect(self._scroll_to_video_item)
        video_right_panel_layout.addWidget(self.video_date_tree_widget)

        # Añadir un spacer para llenar
        video_right_panel_layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        self.video_splitter.addWidget(video_right_panel_widget)

        videos_layout.addWidget(self.video_splitter)


        # ==========================================================
        # 4. Pestaña "Personas" (Sin cambios)
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
        self.cluster_faces_button = QPushButton("Buscar Duplicados")
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
        # 5. Pestaña "Ayuda" (NUEVO)
        # ==========================================================
        help_tab_widget = QWidget()
        help_layout = QVBoxLayout(help_tab_widget)
        help_layout.setAlignment(Qt.AlignCenter)

        # Logo grande en la pestaña
        tab_logo = QLabel()
        logo_path = resource_path("visagevault.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            tab_logo.setPixmap(pixmap.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        # Ajuste fino para centrar ópticamente si la imagen tiene márgenes desiguales
        tab_logo.setStyleSheet("margin-left: 100px;") # Prueba valores pequeños
        help_layout.addWidget(tab_logo)

        help_layout.addSpacing(20)

        # Texto de bienvenida
        welcome_label = QLabel("<h1>Bienvenido a VisageVault</h1>")
        welcome_label.setAlignment(Qt.AlignCenter)
        help_layout.addWidget(welcome_label)

        subtitle_label = QLabel("Tu gestor de recuerdos inteligente, privado y local.")
        subtitle_label.setStyleSheet("font-size: 14pt; color: gray;")
        subtitle_label.setAlignment(Qt.AlignCenter)
        help_layout.addWidget(subtitle_label)

        help_layout.addSpacing(40)

        # Botón para abrir el diálogo
        btn_open_help = QPushButton("  Ver Ayuda / Acerca de / Contacto  ")
        btn_open_help.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation))
        btn_open_help.setStyleSheet("""
            QPushButton {
                font-size: 14pt;
                padding: 15px;
                border-radius: 8px;
                background-color: #3daee9;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #4dbef9; }
        """)
        btn_open_help.setCursor(Qt.PointingHandCursor)
        btn_open_help.clicked.connect(self._open_help_dialog) # Conectamos a la función

        help_layout.addWidget(btn_open_help)
        help_layout.addStretch(1)

        # ==========================================================
        # PESTAÑA NUBE (Google Drive) - ORGANIZADA POR FECHA
        # ==========================================================
        self.cloud_tab = QWidget()
        cloud_layout = QVBoxLayout(self.cloud_tab)

        # 1. Cabecera (Botón Login y Cambiar Carpeta)
        header_layout = QHBoxLayout()
        self.btn_gdrive = QPushButton("Iniciar sesión con Google")
        self.btn_gdrive.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon))
        self.btn_gdrive.clicked.connect(self._on_gdrive_login_click)
        header_layout.addWidget(self.btn_gdrive)

        self.btn_change_folder = QPushButton("Cambiar Carpeta")
        self.btn_change_folder.setVisible(False)
        self.btn_change_folder.clicked.connect(self._select_drive_folder)
        header_layout.addWidget(self.btn_change_folder)

        header_layout.addStretch() # Empujar botones a la izquierda
        cloud_layout.addLayout(header_layout)

        # 2. Splitter Principal (Igual que en Fotos: Árbol a la derecha, Fotos a la izquierda)
        self.cloud_splitter = QSplitter(Qt.Horizontal)

        # --- PANEL IZQUIERDO: Área de Scroll para las Fotos ---
        cloud_area_widget = QWidget()
        self.cloud_container_layout = QVBoxLayout(cloud_area_widget)
        self.cloud_container_layout.setSpacing(0)

        self.cloud_scroll_area = QScrollArea()
        self.cloud_scroll_area.setWidgetResizable(True)
        self.cloud_scroll_area.setWidget(cloud_area_widget)

        # Conectamos el scroll para cargar miniaturas bajo demanda (Lazy Loading)
        self.cloud_scroll_area.verticalScrollBar().valueChanged.connect(self._load_visible_cloud_thumbnails)

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
        self.cloud_splitter.setSizes([800, 200]) # Tamaño inicial

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
        self._load_video_splitter_state() # <-- NUEVO

        self.tab_widget.currentChanged.connect(self._on_tab_changed)

    # ----------------------------------------------------
    # Lógica de Inicio y Configuración
    # ----------------------------------------------------

    def _initial_check(self):
        """Comprueba la configuración al arrancar la app."""
        directory = config_manager.get_photo_directory()
        if directory and Path(directory).is_dir():
            self.current_directory = directory
            self.path_label.setText(f"Ruta: {Path(directory).name}")
            # --- MODIFICADO: Iniciar ambos escaneos ---
            self._start_media_scan(directory)
            # --- FIN DE MODIFICACIÓN ---
        else:
            self._set_status("No se encontró un directorio válido. Por favor, selecciona uno.")
            self._open_directory_dialog(force_select=True)

    def _open_directory_dialog(self, force_select=False):
        """Abre el diálogo para seleccionar el directorio."""
        dialog_title = "Selecciona la Carpeta Raíz de Fotos"
        directory = QFileDialog.getExistingDirectory(self, dialog_title, os.path.expanduser("~"))

        if directory:
            self.current_directory = directory
            config_manager.set_photo_directory(directory)
            self.path_label.setText(f"Ruta: {Path(directory).name}")
            self.date_tree_widget.clear()
            self.video_date_tree_widget.clear() # <-- NUEVO
            # --- MODIFICADO: Iniciar ambos escaneos ---
            self._start_media_scan(directory)
            # --- FIN DE MODIFICACIÓN ---
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

        self._start_photo_search(directory)
        self._start_video_search(directory)

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
            self._start_photo_search(self.current_directory)
            self._start_video_search(self.current_directory)
            # El escaneo de caras se lanzará solo al terminar el de fotos

    def _start_photo_search(self, directory):
        """Configura y lanza el trabajador de escaneo de FOTOS."""
        if self.photo_thread and self.photo_thread.isRunning():
            self._set_status("El escaneo de fotos anterior sigue en curso.")
            return

        self.photo_thread = QThread()
        self.photo_worker = PhotoFinderWorker(directory, self.db.db_path)
        self.photo_worker.moveToThread(self.photo_thread)

        self.photo_thread.started.connect(self.photo_worker.run)
        self.photo_worker.finished.connect(self._handle_search_finished)
        self.photo_worker.progress.connect(self._set_status)

        self.photo_worker.finished.connect(self.photo_thread.quit)
        self.photo_worker.finished.connect(self.photo_worker.deleteLater)
        self.photo_thread.finished.connect(self._on_scan_thread_finished)

        self.select_dir_button.setEnabled(False)
        self.photo_thread.start()

    # --- NUEVA FUNCIÓN ---
    def _start_video_search(self, directory):
        """Configura y lanza el trabajador de escaneo de VÍDEOS."""
        if self.video_thread and self.video_thread.isRunning():
            self._set_status("El escaneo de vídeos anterior sigue en curso.")
            return

        self.video_thread = QThread()
        self.video_worker = VideoFinderWorker(directory, self.db.db_path)
        self.video_worker.moveToThread(self.video_thread)

        self.video_thread.started.connect(self.video_worker.run)
        self.video_worker.finished.connect(self._handle_video_search_finished)
        self.video_worker.progress.connect(self._set_status) # Ambos workers reportan al mismo status_label

        self.video_worker.finished.connect(self.video_thread.quit)
        self.video_worker.finished.connect(self.video_worker.deleteLater)
        self.video_thread.finished.connect(self._on_video_scan_thread_finished)

        self.select_dir_button.setEnabled(False) # Compartido
        self.video_thread.start()
    # --- FIN DE LO NUEVO ---

    # ----------------------------------------------------
    # Escaneo de caras (Sin cambios)
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

    def _display_photos(self):
        """Muestra las FOTOS agrupadas por fecha (FILTRANDO LAS OCULTAS)."""
        while self.photo_container_layout.count() > 0:
            item = self.photo_container_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        self.date_tree_widget.clear()
        self.photo_list_widget_items.clear()
        self.photo_group_widgets = {}

        # --- PASO 1: OBTENER LISTA NEGRA DE FOTOS OCULTAS ---
        # Usamos un set() para que la búsqueda sea instantánea
        hidden_paths = set(self.db.get_hidden_photos())
        # ----------------------------------------------------

        # Sección Ocultas en el árbol
        hidden_item = QTreeWidgetItem(self.date_tree_widget, ["Ocultas"])
        hidden_item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning))
        hidden_item.setData(0, Qt.UserRole, "HIDDEN_SECTION")

        sorted_years = sorted(self.photos_by_year_month.keys(), reverse=True)

        for year in sorted_years:
            if year == "Sin Fecha": continue

            # Creamos el item del año, pero no lo expandimos todavía
            year_item = QTreeWidgetItem(self.date_tree_widget, [str(year)])

            # Etiqueta del Año (La creamos, pero si luego el año está vacío, la ocultaremos)
            # *Nota: Para simplificar, la añadimos. Si queda vacía no es grave,
            # pero lo ideal es filtrar antes.*
            year_label = QLabel(f"Año {year}")
            year_label.setStyleSheet("font-size: 16pt; font-weight: bold; margin-top: 20px; margin-bottom: 5px;")

            # Guardamos referencia temporalmente
            widgets_added_for_year = []
            widgets_added_for_year.append(year_label)

            sorted_months = sorted(self.photos_by_year_month[year].keys())

            month_added_count = 0

            for month in sorted_months:
                if month == "00": continue
                all_photos = self.photos_by_year_month[year][month]

                # --- PASO 2: FILTRAR FOTOS VISIBLES ---
                visible_photos = [p for p in all_photos if p not in hidden_paths]

                # Si no hay fotos visibles en este mes, saltamos al siguiente
                if not visible_photos:
                    continue
                # --------------------------------------

                month_added_count += 1

                try:
                    month_name = datetime.datetime.strptime(month, "%m").strftime("%B").capitalize()
                except ValueError:
                    month_name = "Mes Desconocido"

                month_item = QTreeWidgetItem(year_item, [f"{month_name} ({len(visible_photos)})"])
                month_item.setData(0, Qt.UserRole, (year, month))

                month_label = QLabel(month_name)
                month_label.setStyleSheet("font-size: 14pt; font-weight: bold; margin-top: 10px;")
                widgets_added_for_year.append(month_label)

                self.photo_group_widgets[f"{year}-{month}"] = month_label

                list_widget = PreviewListWidget()
                list_widget.setMovement(QListWidget.Static)
                list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
                list_widget.setSpacing(20)

                list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
                list_widget.customContextMenuRequested.connect(
                    lambda pos, lw=list_widget: self._on_context_menu(pos, lw, is_video=False)
                )

                list_widget.previewRequested.connect(self._open_preview_dialog)
                list_widget.itemDoubleClicked.connect(self._on_photo_item_double_clicked)
                list_widget.setViewMode(QListWidget.IconMode)
                list_widget.setResizeMode(QListWidget.Adjust)
                list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                list_widget.setFrameShape(QFrame.NoFrame)
                list_widget.setIconSize(QSize(self.current_thumbnail_size, self.current_thumbnail_size))

                item_w = self.current_thumbnail_size + 8
                item_h = self.current_thumbnail_size + 8

                # --- USAMOS LA LISTA FILTRADA (visible_photos) ---
                for photo_path in visible_photos:
                    item = QListWidgetItem("Cargando...")
                    item.setToolTip(Path(photo_path).name)
                    item.setSizeHint(QSize(item_w, item_h))
                    item.setData(Qt.UserRole, photo_path)
                    item.setData(Qt.UserRole + 1, "not_loaded")
                    list_widget.addItem(item)
                    self.photo_list_widget_items[photo_path] = item

                # Calcular altura
                viewport_width = self.scroll_area.viewport().width() - 30
                thumb_width = item_w + list_widget.spacing()
                num_cols = max(1, viewport_width // thumb_width)
                rows = (len(visible_photos) + num_cols - 1) // num_cols
                total_height = (rows * item_h) + (rows * list_widget.spacing())
                list_widget.setFixedHeight(total_height)

                widgets_added_for_year.append(list_widget)

            # Solo añadimos los widgets al layout si el año tiene al menos un mes visible
            if month_added_count > 0:
                self.photo_container_layout.addWidget(year_label)
                self.photo_group_widgets[year] = year_label
                # Añadir el resto (meses y listas)
                # year_label ya estaba en la lista widgets_added_for_year[0], pero no en el layout
                for i, w in enumerate(widgets_added_for_year):
                    if i == 0: continue # El label ya lo añadimos arriba
                    self.photo_container_layout.addWidget(w)

                year_item.setExpanded(True)
            else:
                # Si el año se quedó vacío, quitamos el item del árbol
                # (Esto ocurre si ocultaste TODAS las fotos de 2024, por ejemplo)
                # year_item no se añade al padre si lo borramos o lo ocultamos
                year_item.setHidden(True)

        self.photo_container_layout.addStretch(1)
        QTimer.singleShot(100, self._load_main_visible_thumbnails)


    def _display_videos(self):
        """Muestra los VÍDEOS agrupados por fecha (FILTRANDO LOS OCULTOS)."""
        while self.video_container_layout.count() > 0:
            item = self.video_container_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.video_date_tree_widget.clear()

        self.video_list_widget_items.clear()
        self.video_group_widgets = {}

        # --- PASO 1: OBTENER LISTA NEGRA DE VÍDEOS ---
        hidden_paths = set(self.db.get_hidden_videos())
        # ---------------------------------------------

        hidden_item = QTreeWidgetItem(self.video_date_tree_widget, ["Ocultos"])
        hidden_item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning))
        hidden_item.setData(0, Qt.UserRole, "HIDDEN_SECTION")

        sorted_years = sorted(self.videos_by_year_month.keys(), reverse=True)

        for year in sorted_years:
            if year == "Sin Fecha": continue
            year_item = QTreeWidgetItem(self.video_date_tree_widget, [str(year)])

            year_label = QLabel(f"Año {year}")
            year_label.setStyleSheet("font-size: 16pt; font-weight: bold; margin-top: 20px; margin-bottom: 5px;")

            widgets_added_for_year = [year_label]
            month_added_count = 0

            sorted_months = sorted(self.videos_by_year_month[year].keys())

            for month in sorted_months:
                if month == "00": continue
                all_videos = self.videos_by_year_month[year][month]

                # --- PASO 2: FILTRAR VÍDEOS VISIBLES ---
                visible_videos = [v for v in all_videos if v not in hidden_paths]

                if not visible_videos:
                    continue
                # ---------------------------------------

                month_added_count += 1

                try:
                    month_name = datetime.datetime.strptime(month, "%m").strftime("%B").capitalize()
                except ValueError:
                    month_name = "Mes Desconocido"

                month_item = QTreeWidgetItem(year_item, [f"{month_name} ({len(visible_videos)})"])
                month_item.setData(0, Qt.UserRole, (year, month))

                month_label = QLabel(month_name)
                month_label.setStyleSheet("font-size: 14pt; font-weight: bold; margin-top: 10px;")
                widgets_added_for_year.append(month_label)

                self.video_group_widgets[f"{year}-{month}"] = month_label

                list_widget = PreviewListWidget()
                list_widget.setMovement(QListWidget.Static)
                list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
                list_widget.setSpacing(20)

                list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
                list_widget.customContextMenuRequested.connect(
                    lambda pos, lw=list_widget: self._on_context_menu(pos, lw, is_video=True)
                )

                list_widget.setViewMode(QListWidget.IconMode)
                list_widget.setResizeMode(QListWidget.Adjust)
                list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                list_widget.setFrameShape(QFrame.NoFrame)
                list_widget.setToolTip("Ctrl + (+/-): Zoom\n\nHaz clic para seleccionar.")

                list_widget.itemDoubleClicked.connect(self._on_video_item_double_clicked)

                list_widget.setIconSize(QSize(self.current_thumbnail_size, self.current_thumbnail_size))

                item_w = self.current_thumbnail_size + 8
                item_h = self.current_thumbnail_size + 8

                # --- USAR LISTA FILTRADA ---
                for video_path in visible_videos:
                    item = QListWidgetItem("Cargando...")
                    item.setToolTip(Path(video_path).name)
                    item.setSizeHint(QSize(item_w, item_h))
                    item.setData(Qt.UserRole, video_path)
                    item.setData(Qt.UserRole + 1, "not_loaded")
                    list_widget.addItem(item)
                    self.video_list_widget_items[video_path] = item

                viewport_width = self.video_scroll_area.viewport().width() - 30
                thumb_width = item_w + list_widget.spacing()
                num_cols = max(1, viewport_width // thumb_width)

                rows = (len(visible_videos) + num_cols - 1) // num_cols
                total_height = (rows * item_h) + (rows * list_widget.spacing())
                list_widget.setFixedHeight(total_height)

                widgets_added_for_year.append(list_widget)

            if month_added_count > 0:
                self.video_container_layout.addWidget(year_label)
                self.video_group_widgets[year] = year_label
                for i, w in enumerate(widgets_added_for_year):
                    if i == 0: continue
                    self.video_container_layout.addWidget(w)
                year_item.setExpanded(True)
            else:
                year_item.setHidden(True)

        self.video_container_layout.addStretch(1)
        QTimer.singleShot(100, self._load_visible_video_thumbnails)

    # --- FIN DE LAS NUEVAS FUNCIONES DE DISPLAY ---

    # ----------------------------------------------------------------
    # LÓGICA DE MENÚ CONTEXTUAL Y GESTIÓN DE ARCHIVOS
    # ----------------------------------------------------------------

    def _on_context_menu(self, pos, list_widget, is_video, is_hidden_view=False):
        """Muestra el menú contextual con opción de cambio de fecha y ojos rojos."""
        selected_items = list_widget.selectedItems()
        if not selected_items:
            return

        menu = QMenu(self)

        if is_hidden_view:
            # --- OPCIONES PARA OCULTAS ---
            action_restore = menu.addAction("Restaurar a la galería")
            action_restore.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))

            action_delete = menu.addAction("Eliminar del disco (Permanente)")
            action_delete.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))

            action = menu.exec(list_widget.mapToGlobal(pos))

            if action == action_restore:
                self._restore_selected_media(selected_items, is_video)
            elif action == action_delete:
                self._delete_selected_media(selected_items, is_video, from_hidden_view=True)
        else:
            # --- OPCIONES NORMALES ---

            # 1. Cambiar Fecha
            action_date = menu.addAction("Cambiar Fecha (Mover)")
            action_date.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))

            # 2. Corregir Ojos Rojos (SOLO PARA FOTOS)
            action_redeye = None
            if not is_video:
                action_redeye = menu.addAction("Corregir Ojos Rojos (Auto)")
                # No hay un icono estándar perfecto, usamos uno genérico o DialogApply
                action_redeye.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))

            menu.addSeparator()

            # 3. Resto de opciones
            action_hide = menu.addAction("Ocultar de la vista")
            action_delete = menu.addAction("Eliminar del disco (Permanente)")
            action_delete.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))

            action = menu.exec(list_widget.mapToGlobal(pos))

            if action == action_hide:
                self._hide_selected_media(selected_items, is_video)
            elif action == action_delete:
                self._delete_selected_media(selected_items, is_video, from_hidden_view=False)
            elif action == action_date:
                self._change_date_for_selected(selected_items, is_video)
            elif action_redeye and action == action_redeye:
                self._remove_red_eyes_for_selected(selected_items)

    def _remove_red_eye_from_image(self, image_path):
        """Detecta y corrige ojos rojos automáticamente usando OpenCV."""
        try:
            # 1. Leer imagen
            img = cv2.imread(image_path)
            if img is None:
                return False

            img_out = img.copy()

            # 2. Cargar clasificador de ojos pre-entrenado (Haar Cascade)
            # OpenCV suele incluirlo en cv2.data.haarcascades
            eye_cascade_path = cv2.data.haarcascades + 'haarcascade_eye.xml'
            eye_cascade = cv2.CascadeClassifier(eye_cascade_path)

            if eye_cascade.empty():
                print("Error: No se encontró el clasificador de ojos XML.")
                return False

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # 3. Detectar ojos
            eyes = eye_cascade.detectMultiScale(gray, 1.3, 5)

            if len(eyes) == 0:
                return False # No se detectaron ojos

            changed = False

            for (x, y, w, h) in eyes:
                # Extraer la región de interés (ROI) del ojo
                eye_roi = img_out[y:y+h, x:x+w]

                # Separar canales: Blue, Green, Red
                b = eye_roi[:, :, 0]
                g = eye_roi[:, :, 1]
                r = eye_roi[:, :, 2]

                # 4. Crear máscara de "ojo rojo"
                # La rojez suele ser mucho mayor que el verde y el azul combinados
                bg_sum = cv2.add(b, g)
                mask = (r > 150) & (r > bg_sum) # Umbral simple
                mask = mask.astype(np.uint8) * 255

                # Refinar la máscara (llenar huecos)
                mask = cv2.dilate(mask, None, iterations=1)

                # Si hay píxeles rojos detectados
                if np.sum(mask) > 0:
                    changed = True
                    # 5. Corregir: Reemplazar el canal rojo con el promedio de verde y azul
                    mean_bg = cv2.addWeighted(b, 0.5, g, 0.5, 0)

                    # Aplicar solo donde diga la máscara
                    eye_roi_fixed = eye_roi.copy()
                    # Usamos bitwise para mezclar
                    # Donde la mascara es blanca, usamos el promedio cian (mean_bg)
                    # Donde es negra, dejamos el original

                    # Forma numpy rápida:
                    # Convertir máscara a booleano para indexar
                    mask_bool = mask.astype(bool)
                    eye_roi_fixed[:, :, 2][mask_bool] = mean_bg[mask_bool]

                    # Volver a poner el ROI corregido en la imagen principal
                    img_out[y:y+h, x:x+w] = eye_roi_fixed

            if changed:
                # Guardar resultado sobrescribiendo (o podrías guardar copia)
                cv2.imwrite(image_path, img_out)

                # Actualizar fecha de modificación para que se refresquen metadatos si es necesario
                os.utime(image_path, None)
                return True

            return False

        except Exception as e:
            print(f"Error corrigiendo ojos rojos en {image_path}: {e}")
            return False

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
            # Esto asegura que al re-escanear, la función 'get_photo_date' o 'get_video_date'
            # lea esta fecha si falla la lectura de metadatos internos.
            os.utime(filepath, (timestamp, timestamp))

        except Exception as e:
            print(f"Error general actualizando fichero físico {filepath}: {e}")

    def _change_date_for_selected(self, items, is_video):
        """Abre diálogo para cambiar fecha y ACTUALIZA ARCHIVOS FÍSICOS."""
        dialog = DateChangeDialog(self)
        if dialog.exec() == QDialog.Accepted:
            new_year, new_month = dialog.get_data()

            count = 0
            paths_to_update = [item.data(Qt.UserRole) for item in items]

            # Barra de progreso en el status (opcional, pero útil si son muchos)
            total = len(paths_to_update)

            for i, path in enumerate(paths_to_update):
                try:
                    self._set_status(f"Procesando ({i+1}/{total}): {Path(path).name}")

                    # --- NUEVO: ACTUALIZAR EL ARCHIVO FÍSICO ---
                    self._update_file_metadata_on_disk(path, new_year, new_month)
                    # -------------------------------------------

                    # 1. Actualizar Base de Datos
                    if is_video:
                        self.db.update_video_date(path, new_year, new_month)
                        self._remove_from_memory_struct(path, self.videos_by_year_month)

                        if new_year not in self.videos_by_year_month:
                            self.videos_by_year_month[new_year] = {}
                        if new_month not in self.videos_by_year_month[new_year]:
                            self.videos_by_year_month[new_year][new_month] = []
                        self.videos_by_year_month[new_year][new_month].append(path)

                    else:
                        self.db.update_photo_date(path, new_year, new_month)
                        self._remove_from_memory_struct(path, self.photos_by_year_month)

                        if new_year not in self.photos_by_year_month:
                            self.photos_by_year_month[new_year] = {}
                        if new_month not in self.photos_by_year_month[new_year]:
                            self.photos_by_year_month[new_year][new_month] = []
                        self.photos_by_year_month[new_year][new_month].append(path)

                    count += 1
                except Exception as e:
                    print(f"Error actualizando fecha de {path}: {e}")

            self._set_status(f"Fecha actualizada (BD y Archivos) para {count} elementos. Refrescando...")

            # 3. Refrescar la vista
            if is_video:
                self._display_videos()
            else:
                self._display_photos()

    def _delete_selected_media(self, items, is_video, from_hidden_view=False):
        """Elimina físicamente los archivos y de la BD."""
        count = len(items)
        confirm = QMessageBox.question(
            self,
            "Confirmar eliminación",
            f"¿Estás seguro de que quieres eliminar {count} archivo(s) de tu DISCO DURO?\nEsta acción no se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if confirm != QMessageBox.StandardButton.Yes:
            return

        paths_to_delete = [item.data(Qt.UserRole) for item in items]
        deleted_count = 0

        for path in paths_to_delete:
            try:
                # 1. Borrar del disco
                if os.path.exists(path):
                    os.remove(path)

                # 2. Borrar de la BD
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

        self._set_status(f"{deleted_count} archivos eliminados permanentemente.")

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

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _scroll_to_item(self, current_item: QTreeWidgetItem, previous_item: QTreeWidgetItem):
        """Desplazarse al grupo de FOTOS. Versión blindada contra errores C++."""
        if not current_item: return

        # --- PASO 1: EXTRAER DATOS ---
        user_data = current_item.data(0, Qt.UserRole)

        if user_data == "HIDDEN_SECTION":
            self._show_hidden_photos_view()
            return

        target_key = ""
        if current_item.parent():
            year, month = user_data
            target_key = f"{year}-{month}"
        else:
            target_key = current_item.text(0)

        # --- PASO 2: OBTENER WIDGET ---
        target_widget = self.photo_group_widgets.get(target_key)

        # --- PASO 3: VALIDACIÓN DE VIDA ---
        is_zombie = False
        if target_widget:
            try:
                _ = target_widget.isVisible()
            except RuntimeError:
                is_zombie = True

        # Si no existe o es un zombie, regeneramos la vista
        if not target_widget or is_zombie:
            self._display_photos()
            target_widget = self.photo_group_widgets.get(target_key)

        # --- PASO 4: SCROLL SEGURO ---
        if target_widget:
            try:
                self.scroll_area.ensureWidgetVisible(target_widget, 50, 50)
                QTimer.singleShot(200, self._load_main_visible_thumbnails)
            except RuntimeError:
                print("Aviso: No se pudo hacer scroll al widget de foto.")

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _scroll_to_video_item(self, current_item: QTreeWidgetItem, previous_item: QTreeWidgetItem):
        """Desplazarse al grupo de VÍDEOS. Versión blindada contra errores C++."""
        if not current_item: return

        # --- PASO 1: EXTRAER DATOS ---
        user_data = current_item.data(0, Qt.UserRole)

        if user_data == "HIDDEN_SECTION":
            self._show_hidden_videos_view()
            return

        target_key = ""
        if current_item.parent():
            year, month = user_data
            target_key = f"{year}-{month}"
        else:
            target_key = current_item.text(0)

        # --- PASO 2: OBTENER WIDGET ---
        target_widget = self.video_group_widgets.get(target_key)

        # --- PASO 3: VALIDACIÓN DE VIDA ---
        is_zombie = False
        if target_widget:
            try:
                _ = target_widget.isVisible()
            except RuntimeError:
                is_zombie = True

        if not target_widget or is_zombie:
            self._display_videos()
            target_widget = self.video_group_widgets.get(target_key)

        # --- PASO 4: SCROLL SEGURO ---
        if target_widget:
            try:
                self.video_scroll_area.ensureWidgetVisible(target_widget, 50, 50)
                QTimer.singleShot(200, self._load_visible_video_thumbnails)
            except RuntimeError:
                print("Aviso: No se pudo hacer scroll al widget de vídeo.")

    @Slot(dict)
    def _handle_search_finished(self, new_photos_by_year_month):
        """Se llama cuando el PhotoFinderWorker termina."""
        self.select_dir_button.setEnabled(True)

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

    @Slot(dict)
    def _handle_video_search_finished(self, new_videos_by_year_month):
        """Se llama cuando el VideoFinderWorker termina."""
        self.select_dir_button.setEnabled(True)

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

    def _set_status(self, message):
        # Usamos la barra de estado nativa de la ventana (visible en todas las pestañas)
        self.statusBar().showMessage(f"Estado: {message}")

    def _load_main_visible_thumbnails(self):
        """Carga miniaturas de FOTOS visibles (Refactorizado para QListWidget)."""
        viewport = self.scroll_area.viewport()
        preload_rect = viewport.rect().adjusted(0, -PRELOAD_MARGIN_PX, 0, PRELOAD_MARGIN_PX)

        # Iterar sobre los QListWidgets en el área de scroll de fotos
        for list_widget in self.scroll_area.widget().findChildren(PreviewListWidget):

            # Comprobar si el QListWidget está visible
            list_widget_pos = list_widget.mapTo(viewport, list_widget.rect().topLeft())
            list_widget_rect_in_viewport = list_widget.rect().translated(list_widget_pos)

            if preload_rect.intersects(list_widget_rect_in_viewport):
                # Si el widget es visible, comprobar sus items
                for i in range(list_widget.count()):
                    item = list_widget.item(i)
                    load_status = item.data(Qt.UserRole + 1)

                    if load_status == "not_loaded":
                        original_path = item.data(Qt.UserRole)
                        if original_path:
                            item.setData(Qt.UserRole + 1, "loading") # Marcar como "cargando"
                            item.setText("Cargando...") # Asegurarse de que el texto de carga está

                            loader = ThumbnailLoader(original_path, self.thumb_signals)
                            self.threadpool.start(loader)

    def _load_visible_video_thumbnails(self):
        """Carga miniaturas de VÍDEOS visibles (Refactorizado para QListWidget)."""
        viewport = self.video_scroll_area.viewport()
        preload_rect = viewport.rect().adjusted(0, -PRELOAD_MARGIN_PX, 0, PRELOAD_MARGIN_PX)

        # Iterar sobre los QListWidgets en el área de scroll de vídeos
        for list_widget in self.video_scroll_area.widget().findChildren(PreviewListWidget):

            # Comprobar si el QListWidget está visible
            list_widget_pos = list_widget.mapTo(viewport, list_widget.rect().topLeft())
            list_widget_rect_in_viewport = list_widget.rect().translated(list_widget_pos)

            if preload_rect.intersects(list_widget_rect_in_viewport):
                # Si el widget es visible, comprobar sus items
                for i in range(list_widget.count()):
                    item = list_widget.item(i)
                    load_status = item.data(Qt.UserRole + 1)

                    if load_status == "not_loaded":
                        original_path = item.data(Qt.UserRole)
                        if original_path:
                            item.setData(Qt.UserRole + 1, "loading") # Marcar como "cargando"
                            item.setText("Cargando...")

                            loader = VideoThumbnailLoader(original_path, self.thumb_signals)
                            self.threadpool.start(loader)

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

    @Slot(str, QPixmap)
    def _update_thumbnail(self, original_path, pixmap):
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
            item.setSizeHint(scaled_pixmap.size()) # <--- Esto ajusta el tamaño en local
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
        # 3. BLOQUE PARA DRIVE (CORREGIDO PARA AJUSTAR TAMAÑO)
        # ---------------------------------------------------------
        if self.cloud_scroll_area.widget():
            for list_widget in self.cloud_scroll_area.widget().findChildren(PreviewListWidget):
                if not list_widget.isVisible(): continue

                for i in range(list_widget.count()):
                    item = list_widget.item(i)
                    data = item.data(Qt.UserRole)

                    if data and data.get('id') == original_path:
                        # Escalamos manteniendo aspecto
                        scaled = pixmap.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        item.setIcon(QIcon(scaled))

                        # --- ¡ESTA ES LA LÍNEA QUE FALTABA! ---
                        # Ajusta la celda al tamaño real de la imagen (ej: 128x90)
                        # eliminando el espacio vacío sobrante.
                        item.setSizeHint(scaled.size())
                        # --------------------------------------

                        item.setText("")
                        item.setData(Qt.UserRole + 1, "loaded")
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

        self._set_status(f"Vista previa: Bajando {name}...")

        # --- NUEVA RUTA UNIFICADA ---
        base_dir = os.path.dirname(os.path.abspath(__file__))
        # visagevault_cache/drive_cache
        temp_dir = os.path.join(base_dir, "visagevault_cache", "drive_cache")
        # ----------------------------

        if not os.path.exists(temp_dir): os.makedirs(temp_dir)
        local_path = os.path.join(temp_dir, name)

        # Comprobar Caché
        if os.path.exists(local_path):
            if os.path.getsize(local_path) == 0:
                try: os.remove(local_path)
                except: pass
            else:
                self._open_preview_dialog(local_path)
                self._set_status("Vista previa (desde caché).")
                return

        # Descarga en hilo seguro
        threading.Thread(target=self._download_thread_safe, args=(file_id, local_path), daemon=True).start()

    def _download_thread_safe(self, file_id, local_path):
        """Descarga el archivo sin bloquear la interfaz."""
        try:
            manager = DriveManager()
            manager.download_file(file_id, local_path)

            # Volver al hilo principal para abrir la ventana
            QTimer.singleShot(0, lambda: self._finish_cloud_preview(local_path))
        except Exception as e:
            print(f"Error descarga preview: {e}")
            QTimer.singleShot(0, lambda: self._set_status("Error al descargar imagen."))
            # Borrar archivo parcial si falló
            if os.path.exists(local_path):
                try: os.remove(local_path)
                except: pass

    def _finish_cloud_preview(self, local_path):
        """Se ejecuta en el hilo principal cuando la descarga termina."""
        self._set_status("Imagen descargada. Abriendo visor...")
        self._open_preview_dialog(local_path)

    def _download_for_preview(self, file_id, local_path):
        """Descarga y abre el diálogo de vista previa rápida."""
        try:
            local_manager = DriveManager()
            local_manager.download_file(file_id, local_path)

            # Abrir la vista previa (ImagePreviewDialog) en el hilo principal
            QTimer.singleShot(0, lambda: self._open_preview_dialog(local_path))
            QTimer.singleShot(0, lambda: self._set_status("Vista previa lista."))
        except Exception as e:
            print(f"Error descarga preview: {e}")
            QTimer.singleShot(0, lambda: self._set_status("Error al descargar para vista previa."))

    @Slot(QListWidgetItem)
    def _on_drive_item_double_clicked(self, item):
        file_data = item.data(Qt.UserRole)
        if not file_data: return

        file_id = file_data['id']
        name = file_data['name']

        self._set_status(f"Descargando {name} de la nube...")

        # Crear carpeta temporal si no existe
        temp_dir = os.path.join(self.root_cache, "drive_cache")
        if not os.path.exists(temp_dir): os.makedirs(temp_dir)

        local_path = os.path.join(temp_dir, name)

        # Descargar en hilo para no congelar
        threading.Thread(target=self._download_and_show, args=(file_id, local_path), daemon=True).start()

    def _download_and_show(self, file_id, local_path):
        try:
            # --- CORRECCIÓN CRÍTICA DE SEGURIDAD DE HILOS ---
            local_manager = DriveManager()
            local_manager.download_file(file_id, local_path)

            # Volver a UI para abrir el visor
            QTimer.singleShot(0, lambda: self._open_photo_detail(local_path))
            QTimer.singleShot(0, lambda: self._set_status("Descarga completada."))
        except Exception as e:
            print(f"Error descarga: {e}")

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
        """Guarda las posiciones del splitter de FOTOS en la configuración."""
        sizes = self.main_splitter.sizes()
        config_data = config_manager.load_config()
        config_data['photo_splitter_sizes'] = sizes
        config_manager.save_config(config_data)

    @Slot()
    def _save_video_splitter_state(self):
        """Guarda las posiciones del splitter de VÍDEOS en la configuración."""
        sizes = self.video_splitter.sizes()
        config_data = config_manager.load_config()
        config_data['video_splitter_sizes'] = sizes
        config_manager.save_config(config_data)

    def _load_photo_splitter_state(self):
        """Carga las posiciones del splitter de FOTOS desde la configuración."""
        config_data = config_manager.load_config()
        sizes = config_data.get('photo_splitter_sizes')
        min_right_width = 180
        if sizes and len(sizes) == 2:
            if sizes[1] < min_right_width:
                sizes[0] = sizes[0] + (sizes[1] - min_right_width)
                sizes[1] = min_right_width
            self.main_splitter.setSizes(sizes)
        else:
            default_width = self.width()
            default_sizes = [int(default_width * 0.8), int(default_width * 0.2)]
            if default_sizes[1] < min_right_width:
                 default_sizes[1] = min_right_width
                 default_sizes[0] = default_width - min_right_width
            self.main_splitter.setSizes(default_sizes)

    def _load_video_splitter_state(self):
        """Carga las posiciones del splitter de VÍDEOS desde la configuración."""
        config_data = config_manager.load_config()
        sizes = config_data.get('video_splitter_sizes')
        min_right_width = 180
        if sizes and len(sizes) == 2:
            if sizes[1] < min_right_width:
                sizes[0] = sizes[0] + (sizes[1] - min_right_width)
                sizes[1] = min_right_width
            self.video_splitter.setSizes(sizes)
        else:
            default_width = self.width()
            default_sizes = [int(default_width * 0.8), int(default_width * 0.2)]
            if default_sizes[1] < min_right_width:
                 default_sizes[1] = min_right_width
                 default_sizes[0] = default_width - min_right_width
            self.video_splitter.setSizes(default_sizes)

    def resizeEvent(self, event):
        self.resize_timer.start()
        super().resizeEvent(event)

    @Slot()
    def _handle_resize_timeout(self):
        # Si no hay fotos O vídeos cargados, no hagas nada
        if not self.photos_by_year_month and not self.videos_by_year_month:
            return

        # print(f"Redibujando layout para el nuevo ancho.")
        # Re-dibujar AMBAS pestañas
        if self.photos_by_year_month:
            self._display_photos()
        if self.videos_by_year_month:
            self._display_videos()

    @Slot(str)
    def _open_photo_detail(self, original_path):
        """Abre la ventana de detalle de la foto."""
        self._set_status(f"Abriendo detalle para: {Path(original_path).name}")
        dialog = PhotoDetailDialog(original_path, self.db, self)
        dialog.metadata_changed.connect(self._handle_photo_date_changed)
        dialog.exec()
        self._set_status("Detalle cerrado.")

    @Slot(QListWidgetItem)
    def _on_photo_item_double_clicked(self, item: QListWidgetItem):
        """Se llama cuando se hace doble clic en un item de QListWidget de fotos."""
        original_path = item.data(Qt.UserRole)
        if original_path:
            self._open_photo_detail(original_path)

    @Slot(QListWidgetItem)
    def _on_video_item_double_clicked(self, item: QListWidgetItem):
        """Se llama cuando se hace doble clic en un item de QListWidget de vídeos."""
        original_path = item.data(Qt.UserRole)
        if original_path:
            self._open_video_player(original_path)

    # --- ¡NUEVO SLOT PARA VISTA PREVIA! ---
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

        pixmap = QPixmap() # Empezar con un pixmap vacío

        # Definir extensiones RAW (deben coincidir con las de los otros archivos)
        RAW_EXTENSIONS = ('.nef', '.cr2', '.cr3', '.crw', '.arw', '.srf', '.orf', '.rw2', '.raf', '.pef', '.dng', '.raw')
        file_suffix = Path(original_path).suffix.lower()

        try:
            if file_suffix in RAW_EXTENSIONS:
                # 1. Usar rawpy para leer el archivo RAW
                with rawpy.imread(original_path) as raw:
                    rgb_array = raw.postprocess()

                # 2. Convertir el array de numpy a QImage
                height, width, channel = rgb_array.shape
                bytes_per_line = 3 * width
                q_image = QImage(rgb_array.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()

                # 3. Convertir QImage a QPixmap
                pixmap = QPixmap.fromImage(q_image)

            else:
                # 4. Lógica original para JPG, PNG, etc.
                pixmap = QPixmap(original_path)

            if pixmap.isNull():
                print(f"Error cargando pixmap para vista previa: {original_path}")
                return

            # Lanzar el diálogo
            preview_dialog = ImagePreviewDialog(pixmap, self)
            preview_dialog.show_with_animation()

        except Exception as e:
            print(f"Error al cargar vista previa (Ctrl+Rueda): {e}")

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

    @Slot(int)
    def _on_tab_changed(self, index):
        """Se llama cuando el usuario cambia de pestaña."""
        # Limpiamos cola de hilos para priorizar lo que se ve ahora
        self.threadpool.clear()

        tab_name = self.tab_widget.tabText(index)

        if tab_name == "Personas":
            self._set_status("Cargando vista de personas...")
            self._load_people_list()

            # NOTA: Ya NO borramos manualmente los widgets aquí.
            # Dejamos que _load_existing_faces_async decida qué añadir.

            if self.face_loading_label:
                self.face_loading_label.deleteLater()
                self.face_loading_label = None

            # Cargar caras (modo incremental)
            # Si vengo de 'Caras Eliminadas', necesito resetear la vista a 'Desconocidas'
            current_item = self.people_tree_widget.currentItem()
            if current_item and current_item.data(0, Qt.UserRole) == -2:
                 # Si estaba en eliminadas, aquí no hacemos nada, dejamos que el usuario navegue
                 pass
            else:
                 # Si estoy en vista normal, cargo lo nuevo
                 self._load_existing_faces_async()

            if self.face_scan_thread and self.face_scan_thread.isRunning():
                 self._set_status("Mostrando caras. Escaneo sigue en segundo plano...")

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

        # Si NO es append (es una carga total), limpiamos todo
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

        # Si es append y no hay nada nuevo, salimos
        if append and not face_list:
            return

        # Limpiar placeholder de "No se han encontrado" si existe
        if self.unknown_faces_layout.count() == 1:
            item = self.unknown_faces_layout.itemAt(0)
            widget = item.widget()
            if isinstance(widget, QLabel) and not isinstance(widget, CircularFaceLabel):
                 widget.deleteLater()
                 self.current_face_count = 0

        # Recalcular columnas disponibles
        viewport_width = self.left_people_stack.width() - 30
        num_cols = max(1, viewport_width // 110)

        # --- MEJORA: Usar el conteo real del layout para no pisar items ---
        # Esto asegura que si borraste una cara, la nueva no intente ocupar su hueco antiguo erróneamente
        start_index = self.unknown_faces_layout.count()

        for i, face_row in enumerate(face_list):
            face_id = face_row['id']

            # Crear el widget de la cara
            face_widget = CircularFaceLabel(QPixmap())
            # Usamos un texto más claro o vacío mientras carga
            face_widget.setText("Cargando...")
            face_widget.setStyleSheet("color: gray; font-size: 10px;")

            face_widget.setProperty("face_id", face_id)
            face_widget.setProperty("is_deleted_view", is_deleted_view)
            face_widget.rightClicked.connect(self._on_face_right_clicked)
            face_widget.clicked.connect(self._on_face_clicked)

            # Calcular posición exacta (Flow Layout simulado)
            current_idx = start_index + i
            row = current_idx // num_cols
            col = current_idx % num_cols

            self.unknown_faces_layout.addWidget(face_widget, row, col, Qt.AlignTop)

            # Lanzar carga de imagen en segundo plano
            loader = FaceLoader(
                self.face_loader_signals,
                face_id,
                face_row['filepath'],
                face_row['location']
            )
            self.threadpool.start(loader)

        # Actualizamos el contador global
        self.current_face_count = start_index + len(face_list)

    def _load_existing_faces_async(self):
        """Carga solo las caras nuevas que no estén ya visualizadas."""
        self.unknown_faces_group.setTitle("Caras Sin Asignar")
        self.cluster_faces_button.setEnabled(True)
        self.show_deleted_faces_button.setEnabled(True)

        # 1. Obtener todas las caras candidatas de la BD
        all_unknown_faces = self.db.get_unknown_faces()

        # 2. Mapear qué IDs ya tenemos pintados en pantalla
        existing_ids = set()
        count_widgets = self.unknown_faces_layout.count()

        for i in range(count_widgets):
            item = self.unknown_faces_layout.itemAt(i)
            if item and item.widget():
                # Solo nos interesan los widgets que son caras (CircularFaceLabel)
                # Ignoramos QLabels de "No hay fotos" o "Cargando"
                fid = item.widget().property("face_id")
                if fid is not None:
                    existing_ids.add(fid)

        # 3. Filtrar: Quedarnos solo con las caras que NO están en pantalla
        new_faces_to_add = [f for f in all_unknown_faces if f['id'] not in existing_ids]

        # 4. Decidir si limpiamos o añadimos
        # Si hay IDs existentes, es un APPEND. Si no, es una carga inicial (CLEAR).
        is_append = (len(existing_ids) > 0)

        # Solo llamamos a populate si hay algo nuevo que añadir o si es una carga inicial vacía
        if new_faces_to_add or not is_append:
            self._populate_face_grid_async(new_faces_to_add, is_deleted_view=False, append=is_append)

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
        self.db.soft_delete_face(face_id)
        widget.deleteLater()
        self._set_status(f"Cara ID {face_id} eliminada.")
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
        Se llama cada vez que el escáner encuentra una cara nueva en segundo plano.
        """
        # --- OPTIMIZACIÓN CRÍTICA ---
        # Si NO estamos en la pestaña 'Personas', no cargamos la miniatura visual.
        # La cara ya está guardada en la BD, así que se cargará cuando el usuario cambie de pestaña.
        # Esto evita que se sature el procesador mientras navegas por fotos/vídeos.
        if self.tab_widget.currentWidget() != self.personas_tab_widget:
            return
        # ----------------------------

        # Si estamos en la pestaña Personas, cargamos la miniatura inmediatamente
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

    @Slot(int, QPixmap, str)
    def _handle_face_loaded(self, face_id: int, pixmap: QPixmap, photo_path: str):
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
        else:
            if self.unknown_faces_group.title() != "Caras Sin Asignar":
                return
            face_widget = CircularFaceLabel(pixmap)
            face_widget.setProperty("face_id", face_id)
            face_widget.setProperty("photo_path", photo_path)
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

    def closeEvent(self, event):
        """Limpia de forma segura todos los hilos antes de salir."""
        print("Cerrando aplicación... Por favor, espere.")
        self._set_status("Cerrando... esperando a que terminen las tareas de fondo.")

        try:
            self._save_photo_splitter_state()
            self._save_video_splitter_state()
            # También guardamos el tamaño de la miniatura por seguridad
            config_manager.set_thumbnail_size(self.current_thumbnail_size)
        except Exception as e:
            print(f"Error al guardar configuración al cerrar: {e}")

        if self.file_watcher:
            self.file_watcher.stop()

        # 1. Detener el hilo de escaneo de fotos
        if self.photo_thread and self.photo_thread.isRunning():
            print("Deteniendo el hilo de escaneo de fotos...")
            if self.photo_worker:
                self.photo_worker.is_running = False
                try: self.photo_worker.finished.disconnect()
                except RuntimeError: pass
            self.photo_thread.quit()
            self.photo_thread.wait(3000)

        # 2. Detener el hilo de escaneo de vídeos (NUEVO)
        if self.video_thread and self.video_thread.isRunning():
            print("Deteniendo el hilo de escaneo de vídeos...")
            if self.video_worker:
                self.video_worker.is_running = False
                try: self.video_worker.finished.disconnect()
                except RuntimeError: pass
            self.video_thread.quit()
            self.video_thread.wait(3000)

        # 3. Detener el hilo de escaneo de caras
        if self.face_scan_thread and self.face_scan_thread.isRunning():
            print("Deteniendo el hilo de escaneo de caras...")
            if self.face_scan_worker:
                self.face_scan_worker.is_running = False
                try: self.face_scan_worker.signals.scan_finished.disconnect()
                except RuntimeError: pass
            self.face_scan_thread.quit()
            self.face_scan_thread.wait(3000)

        # 4. Esperar al pool de QRunnables
        print("Esperando tareas del ThreadPool (miniaturas/caras)...")
        self.threadpool.clear()
        self.threadpool.waitForDone(3000)

        print("Todos los hilos finalizados. Saliendo.")
        event.accept()

    # --- ¡NUEVO MÉTODO DE KEYPRESS! ---
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
                # Si es otra tecla (ej: Ctrl+Rueda), dejar que el sistema la maneje
                super().keyPressEvent(event)
                return

            # 4. Si el tamaño ha cambiado, aplicarlo y guardarlo
            if new_size != self.current_thumbnail_size:
                self.current_thumbnail_size = new_size
                config_manager.set_thumbnail_size(new_size)

                # 5. Redibujar las vistas (igual que al redimensionar)
                if self.photos_by_year_month:
                    self._display_photos()
                if self.videos_by_year_month:
                    self._display_videos()

            event.accept() # Marcar el evento como manejado

        else:
            # Si no es Ctrl, pasar el evento
            super().keyPressEvent(event)

    @Slot()
    def _start_clustering(self):
        self.cluster_faces_button.setText("Procesando...")
        self.cluster_faces_button.setEnabled(False)
        self._set_status("Iniciando búsqueda de duplicados...")
        worker = ClusterWorker(self.cluster_signals, self.db.db_path)
        self.threadpool.start(worker)

    @Slot(list)
    def _handle_clusters_found(self, clusters: list):
        if not clusters:
            self._set_status("No se encontraron nuevos duplicados.")
            return
        self.cluster_queue = clusters
        self._set_status(f"¡Encontrados {len(self.cluster_queue)} grupos! Procesando...")
        self._process_cluster_queue()

    @Slot()
    def _handle_clustering_finished(self):
        self.cluster_faces_button.setText("Buscar Duplicados")
        self.cluster_faces_button.setEnabled(True)
        if not self.cluster_queue:
             self._set_status("Búsqueda de duplicados finalizada. No se encontraron grupos.")

    @Slot()
    def _process_cluster_queue(self):
        if not self.cluster_queue:
            self._set_status("¡Etiquetado de grupos completado!")
            self._load_existing_faces_async()
            return
        next_cluster_ids = self.cluster_queue.pop(0)
        self._set_status(f"Procesando grupo... quedan {len(self.cluster_queue)} grupos.")
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

        sorted_years = sorted(photos_by_year_month.keys(), reverse=True)
        for year in sorted_years:
            sorted_months = sorted(photos_by_year_month[year].keys(), reverse=True)
            for month in sorted_months:
                photos = photos_by_year_month[year][month]
                if not photos: continue
                try:
                    month_name = datetime.datetime.strptime(month, "%m").strftime("%B").capitalize()
                except ValueError:
                    month_name = "Mes Desconocido"
                group_label = QLabel(f"{month_name} {year}")
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
        """Muestra solo las fotos ocultas en el panel principal."""
        self._set_status("Cargando fotos ocultas...")

        # Limpiar layout existente
        while self.photo_container_layout.count() > 0:
            item = self.photo_container_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        # IMPORTANTE: Limpiar referencias a widgets antiguos para evitar RuntimeError
        self.photo_group_widgets.clear()
        self.photo_list_widget_items.clear()

        title = QLabel("Fotos Ocultas")
        title.setStyleSheet("font-size: 18pt; color: red; font-weight: bold; margin: 20px;")
        self.photo_container_layout.addWidget(title)

        hidden_paths = self.db.get_hidden_photos()

        if not hidden_paths:
            self.photo_container_layout.addWidget(QLabel("No hay fotos ocultas."))
            self.photo_container_layout.addStretch(1)
            return  # <--- Aquí salimos si no hay nada.

        # Si llegamos aquí, SÍ creamos el list_widget
        list_widget = PreviewListWidget()
        list_widget.setMovement(QListWidget.Static)
        list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        list_widget.setSpacing(20)

        list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        list_widget.customContextMenuRequested.connect(
            lambda pos, lw=list_widget: self._on_context_menu(pos, lw, is_video=False, is_hidden_view=True)
        )

        list_widget.setViewMode(QListWidget.IconMode)
        list_widget.setResizeMode(QListWidget.Adjust)

        list_widget.setIconSize(QSize(self.current_thumbnail_size, self.current_thumbnail_size))
        item_w = self.current_thumbnail_size + 8
        item_h = self.current_thumbnail_size + 8

        for path in hidden_paths:
            if not os.path.exists(path): continue
            item = QListWidgetItem("Cargando...")
            item.setSizeHint(QSize(item_w, item_h))
            item.setData(Qt.UserRole, path)
            item.setData(Qt.UserRole + 1, "not_loaded")
            list_widget.addItem(item)
            self.photo_list_widget_items[path] = item

        self.photo_container_layout.addWidget(list_widget)
        self.photo_container_layout.addStretch(1)
        QTimer.singleShot(100, self._load_main_visible_thumbnails)

    def _show_hidden_videos_view(self):
        """Muestra solo los vídeos ocultos en el panel principal."""
        self._set_status("Cargando vídeos ocultos...")

        while self.video_container_layout.count() > 0:
            item = self.video_container_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        self.video_list_widget_items.clear()

        title = QLabel("Vídeos Ocultos")
        title.setStyleSheet("font-size: 18pt; color: red; font-weight: bold; margin: 20px;")
        self.video_container_layout.addWidget(title)

        hidden_paths = self.db.get_hidden_videos()

        if not hidden_paths:
            self.video_container_layout.addWidget(QLabel("No hay vídeos ocultos."))
            self.video_container_layout.addStretch(1)
            return

        # Si llegamos aquí, SÍ creamos el list_widget
        list_widget = PreviewListWidget()
        list_widget.setMovement(QListWidget.Static)
        list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        list_widget.setSpacing(20)

        list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        list_widget.customContextMenuRequested.connect(
            lambda pos, lw=list_widget: self._on_context_menu(pos, lw, is_video=True, is_hidden_view=True)
        )
        list_widget.setViewMode(QListWidget.IconMode)
        list_widget.setResizeMode(QListWidget.Adjust)

        list_widget.setIconSize(QSize(self.current_thumbnail_size, self.current_thumbnail_size))
        item_w = self.current_thumbnail_size + 8
        item_h = self.current_thumbnail_size + 8

        for path in hidden_paths:
            if not os.path.exists(path): continue
            item = QListWidgetItem("Cargando...")
            item.setSizeHint(QSize(item_w, item_h))
            item.setData(Qt.UserRole, path)
            item.setData(Qt.UserRole + 1, "not_loaded")
            list_widget.addItem(item)
            self.video_list_widget_items[path] = item

        self.video_container_layout.addWidget(list_widget)
        self.video_container_layout.addStretch(1)
        QTimer.singleShot(100, self._load_visible_video_thumbnails)

    @Slot()
    def _open_help_dialog(self):
        """Abre la ventana de ayuda."""
        dialog = HelpDialog(self)
        dialog.exec()

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

                # Borrar miniatura antigua de la caché para obligar a regenerarla
                # (Asumiendo que importaste hashlib y THUMBNAIL_DIR de thumbnail_generator o copiaste la lógica)
                # Una forma rápida sin importar es borrarla si sabemos la ruta,
                # o simplemente recargar el loader que la regenerará si detecta cambio (depende de tu implementación).
                # Aquí simplemente recargamos la vista.

            processed += 1

        self._set_status(f"Proceso finalizado. {successes} fotos corregidas de {processed}.")

        if successes > 0:
            # Refrescar la vista actual para ver cambios (o regenerar thumbnails)
            # Lo ideal sería invalidar la caché de thumbnails de estas fotos específicas
            # Como solución simple, recargamos la vista:
            self._display_photos()

    @Slot()
    def _on_gdrive_login_click(self):
        self.btn_gdrive.setEnabled(False)
        self.btn_gdrive.setText("Esperando navegador...")
        self._set_status("Abriendo navegador para inicio de sesión en Google...")

        # Crear worker y thread de Qt
        self.drive_login_thread = QThread()
        self.drive_login_worker = DriveLoginWorker()
        self.drive_login_worker.moveToThread(self.drive_login_thread)

        # Conectar señales
        self.drive_login_thread.started.connect(self.drive_login_worker.run)
        self.drive_login_worker.login_success.connect(self._on_login_success_with_service)
        self.drive_login_worker.login_failed.connect(self._on_login_failure)

        # Limpieza
        self.drive_login_worker.finished.connect(self.drive_login_thread.quit)
        self.drive_login_worker.finished.connect(self.drive_login_worker.deleteLater)
        self.drive_login_thread.finished.connect(lambda: setattr(self, 'drive_login_thread', None))

        self.drive_login_thread.start()

    @Slot(object)
    def _on_login_success_with_service(self, service):
        """Recibe el servicio de Drive y continúa con la configuración."""
        self.drive_service = service
        self._on_login_success()

    @Slot(str)
    def _on_login_failure(self, error_message=None):
        """Maneja el fallo en el login."""
        self.btn_gdrive.setEnabled(True)
        self.btn_gdrive.setText("Reintentar conexión")
        if error_message:
            self._set_status(f"Conexión fallida: {error_message}")
        else:
            self._set_status("Conexión fallida. Verifique sus credenciales.")

    def _perform_google_login(self):
        try:
            self.drive_auth = DriveAuthenticator()
            # Esta línea bloquea el hilo hasta que el usuario inicia sesión en el navegador
            self.drive_service = self.drive_auth.get_service()

            # Si llegamos aquí, fue exitoso. Programar actualización de UI en el hilo principal
            QTimer.singleShot(0, self._on_login_success)

        except FileNotFoundError as e:
            QTimer.singleShot(0, lambda: QMessageBox.critical(self, "Error Fatal", str(e)))
        except Exception as e:
            print(f"Error de Login con Google: {e}")
            QTimer.singleShot(0, self._on_login_failure)

    @Slot()
    def _on_login_success(self):
        self._set_status("¡Conectado a Google Drive!")

        # Actualizar botón de conexión
        self.btn_gdrive.setText("Conectado ✅")
        self.btn_gdrive.setEnabled(False)
        self.btn_gdrive.setStyleSheet("background-color: #34a853; color: white; padding: 12px; font-weight: bold;")

        self.btn_change_folder.setVisible(True)

        # Inicializar el Manager real para usar la API
        try:
            self.drive_manager = DriveManager()
            self.drive_manager.authenticate()

            # Verificar si ya tenemos carpeta configurada
            folder_id = config_manager.get_drive_folder_id()

            if folder_id:
                self._set_status(f"Escaneando carpeta guardada...")

                # --- CORRECCIÓN CRÍTICA: LLAMADA DIRECTA (NO THREADING) ---
                # _scan_drive_content YA gestiona sus propios hilos internamente.
                # Al llamarla directo, permitimos que _load_drive_from_db pinte la UI sin crashear.
                self._scan_drive_content(folder_id)
                # ----------------------------------------------------------
            else:
                self._select_drive_folder()

        except Exception as e:
            print(f"Error post-login: {e}")
            self._set_status(f"Error inicializando Drive: {e}")

    def _select_drive_folder(self):
        """Abre el navegador de carpetas de Drive."""
        try:
            dialog = DriveFolderDialog(self.drive_manager, self)
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
                while self.cloud_container_layout.count() > 0:
                    item = self.cloud_container_layout.takeAt(0)
                    if item.widget(): item.widget().deleteLater()

                # Añadir un loading visual temporal
                self.cloud_container_layout.addWidget(QLabel("Cargando nueva carpeta..."))

                # Guardar configuración
                config_manager.set_drive_folder_id(folder_id)
                self.btn_change_folder.setVisible(True)
                self.btn_change_folder.setText(f"Carpeta: {folder_name} (Cambiar)")

                self._set_status(f"Cambiando a carpeta: {folder_name}...")

                # 3. INICIAR NUEVO ESCANEO
                self._scan_drive_content(folder_id)

            dialog.deleteLater()

        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", f"Error al abrir navegador de Drive: {e}")

    def _load_drive_from_db(self, root_folder_id):
        """Carga solo las fotos que pertenecen a la carpeta seleccionada."""
        self._set_status("Cargando caché local...")

        db_photos = self.db.get_all_drive_photos(root_folder_id)

        if not db_photos:
            # Si está vacía, limpiamos todo por si acaso
            self.drive_photos_by_date = {}
            self.drive_loaded_ids = set() # <--- LIMPIEZA
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
        self.drive_loaded_ids = set() # <--- LIMPIEZA ANTES DE RELLENAR
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

        self.drive_scan_thread = QThread()
        self.drive_scan_worker = DriveScanWorker(folder_id, self.db.db_path)
        self.drive_scan_worker.moveToThread(self.drive_scan_thread)

        self.drive_scan_thread.started.connect(self.drive_scan_worker.run)

        # CAMBIO: Ya no conectamos items_found porque lo hemos quitado
        # self.drive_scan_worker.items_found.connect(...) <--- ELIMINADO

        self.drive_scan_worker.progress.connect(self._set_status)
        self.drive_scan_worker.finished.connect(self._on_drive_scan_finished)

        self.drive_scan_worker.finished.connect(self.drive_scan_thread.quit)
        self.drive_scan_worker.finished.connect(self.drive_scan_worker.deleteLater)
        self.drive_scan_thread.finished.connect(self.drive_scan_thread.deleteLater)

        self.drive_scan_thread.start()

    @Slot(int)
    def _on_drive_scan_finished(self, total_count):
        """Se llama cuando termina el escaneo."""
        self._set_status(f"Indexación completada ({total_count} nuevos). Recargando vista...")

        # Volvemos a cargar desde la DB local para refrescar la pantalla con lo nuevo
        self._load_drive_from_db(self.current_drive_folder_id)

        # Forzar actualización visual
        self._display_cloud_photos()

        if self.cloud_photo_count == 0:
             from PySide6.QtWidgets import QMessageBox
             QMessageBox.information(self, "Aviso", "No se encontraron imágenes en esa carpeta.")

        self._set_status(f"Listo. {self.cloud_photo_count} fotos disponibles.")

    @Slot(list)
    def _add_drive_items(self, items):
        """
        Solo actualiza la estructura en memoria (RAM).
        La inserción en BD ya la hizo el worker.
        """
        # ELIMINADO: self.db.bulk_upsert_drive_photos(...) <- Esto congelaba la UI

        self._classify_drive_items_in_memory(items)
        self._set_status(f"Sincronizando... {self.cloud_photo_count} fotos procesadas.")

    def _display_cloud_photos(self):
        """Dibuja la interfaz de Nube EXACTAMENTE igual que Fotos (Estilo nativo)."""

        # Limpiar layout anterior
        while self.cloud_container_layout.count() > 0:
            item = self.cloud_container_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        self.cloud_date_tree.clear()
        self.cloud_group_widgets = {}

        sorted_years = sorted(self.drive_photos_by_date.keys(), reverse=True)

        for year in sorted_years:
            year_item = QTreeWidgetItem(self.cloud_date_tree, [str(year)])

            year_label = QLabel(f"Año {year}")
            year_label.setStyleSheet("font-size: 16pt; font-weight: bold; margin-top: 20px; margin-bottom: 5px;")

            widgets_to_add_for_year = [year_label]
            self.cloud_group_widgets[str(year)] = year_label

            sorted_months = sorted(self.drive_photos_by_date[year].keys(), reverse=True)

            for month in sorted_months:
                photos = self.drive_photos_by_date[year][month]
                if not photos: continue

                try:
                    month_name = datetime.datetime.strptime(month, "%m").strftime("%B").capitalize()
                except:
                    month_name = "Desconocido"

                month_item = QTreeWidgetItem(year_item, [f"{month_name} ({len(photos)})"])
                month_item.setData(0, Qt.UserRole, f"{year}-{month}")

                month_label = QLabel(month_name)
                month_label.setStyleSheet("font-size: 14pt; font-weight: bold; margin-top: 10px;")
                widgets_to_add_for_year.append(month_label)
                self.cloud_group_widgets[f"{year}-{month}"] = month_label

                # --- LISTA DE FOTOS (Configuración IDÉNTICA a _display_photos) ---
                list_widget = PreviewListWidget()
                list_widget.setMovement(QListWidget.Static)
                list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
                list_widget.setSpacing(20) # Mismo espaciado que Fotos

                # Configuración visual: SIN CSS MANUAL para usar el tema del sistema
                list_widget.setViewMode(QListWidget.IconMode)
                list_widget.setResizeMode(QListWidget.Adjust) # Adjust permite redimensionar celdas
                list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                list_widget.setFrameShape(QFrame.NoFrame)

                list_widget.previewRequested.connect(self._on_drive_preview_requested)

                # Usamos 128px de base
                icon_size = 128
                list_widget.setIconSize(QSize(icon_size, icon_size))

                # Tamaño inicial cuadrado (mientras carga)
                item_dim = icon_size + 8

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
                    item.setData(Qt.UserRole + 1, "not_loaded")
                    item.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))

                    # Tamaño inicial (se ajustará luego en _update_thumbnail)
                    item.setSizeHint(QSize(item_dim, item_dim))

                    list_widget.addItem(item)

                # Cálculo de altura para el ScrollArea
                viewport_width = self.cloud_scroll_area.viewport().width() - 30
                thumb_total_width = item_dim + list_widget.spacing()
                num_cols = max(1, viewport_width // thumb_total_width)
                rows = (len(photos) + num_cols - 1) // num_cols
                total_height = (rows * item_dim) + (rows * list_widget.spacing()) + 20

                list_widget.setFixedHeight(total_height)
                widgets_to_add_for_year.append(list_widget)

            for w in widgets_to_add_for_year:
                self.cloud_container_layout.addWidget(w)

            year_item.setExpanded(True)

        self.cloud_container_layout.addStretch(1)
        QTimer.singleShot(100, self._load_visible_cloud_thumbnails)

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _scroll_to_cloud_item(self, current, previous):
        """Navegación rápida al hacer clic en el árbol de fechas."""
        if not current: return

        key = ""
        if current.parent(): # Es un mes
            key = current.data(0, Qt.UserRole) # "2023-05"
        else: # Es un año
            key = current.text(0) # "2023"

        target_widget = self.cloud_group_widgets.get(key)
        if target_widget:
            self.cloud_scroll_area.ensureWidgetVisible(target_widget, 0, 0)
            # Forzar carga de miniaturas en la nueva posición
            QTimer.singleShot(200, self._load_visible_cloud_thumbnails)

    # ----------------------------------------------------------------------
    # FUNCIONES AUXILIARES QUE FALTAN (Pegar dentro de VisageVaultApp)
    # ----------------------------------------------------------------------

    def _calculate_list_height(self, num_items, icon_size, viewport_width):
        """Calcula la altura necesaria para una lista sin scrollbar."""
        # Ajuste de márgenes (icono + padding)
        item_w = icon_size + 20
        item_h = icon_size + 40

        # Columnas que caben en el ancho actual
        cols = max(1, (viewport_width - 30) // item_w)

        # Filas necesarias
        rows = (num_items + cols - 1) // cols

        return rows * item_h

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _scroll_to_cloud_item(self, current, previous):
        """Navegación rápida al hacer clic en el árbol de fechas."""
        if not current: return

        key = ""
        if current.parent(): # Es un mes
            key = current.data(0, Qt.UserRole) # "2023-05"
        else: # Es un año
            key = current.text(0) # "2023"

        target_widget = self.cloud_group_widgets.get(key)

        # Validar que el widget existe y es visible para evitar errores C++
        if target_widget:
            try:
                self.cloud_scroll_area.ensureWidgetVisible(target_widget, 0, 0)
                # Forzar carga de miniaturas en la nueva posición tras un breve retraso
                QTimer.singleShot(200, self._load_visible_cloud_thumbnails)
            except RuntimeError:
                pass

    def _load_visible_cloud_thumbnails(self):
        """Carga SOLO las miniaturas que se ven en pantalla (Nube)."""
        viewport = self.cloud_scroll_area.viewport()
        preload_rect = viewport.rect().adjusted(0, -500, 0, 500) # Precarga 500px arriba/abajo

        widget_contenedor = self.cloud_scroll_area.widget()
        if not widget_contenedor: return

        # Buscar todas las listas dentro del área de nube
        for list_widget in widget_contenedor.findChildren(PreviewListWidget):

            # Si la lista no está visible, saltarla
            if not list_widget.isVisible(): continue

            # Coordenadas relativas al viewport
            pos = list_widget.mapTo(viewport, list_widget.rect().topLeft())
            rect = list_widget.rect().translated(pos)

            # Si la lista cruza el área visible (+ margen)
            if preload_rect.intersects(rect):
                for i in range(list_widget.count()):
                    item = list_widget.item(i)
                    # Si no está cargada ni cargando...
                    if item.data(Qt.UserRole + 1) == "not_loaded":
                        data = item.data(Qt.UserRole)
                        thumb_link = data.get('thumbnailLink')
                        file_id = data.get('id')

                        if thumb_link and file_id:
                            item.setData(Qt.UserRole + 1, "loading")
                            # Usamos el NetworkThumbnailLoader
                            worker = NetworkThumbnailLoader(thumb_link, file_id, self.thumb_signals)
                            self.threadpool.start(worker)

    def _stop_cloud_operations(self):
        """Detiene de forma SEGURA cualquier descarga o escaneo."""
        self._set_status("Deteniendo operaciones actuales...")

        # 1. Vaciar cola de descargas de miniaturas
        self.threadpool.clear()

        # 2. Detener escáner de carpetas si existe
        if self.drive_scan_thread:
            try:
                # Intentamos acceder al objeto. Si ya fue borrado por C++,
                # esto lanzará un RuntimeError que capturamos abajo.
                if self.drive_scan_thread.isRunning():

                    if self.drive_scan_worker:
                        try:
                            self.drive_scan_worker.is_running = False
                            # Desconectar señales para evitar actualizaciones fantasma
                            self.drive_scan_worker.items_found.disconnect()
                        except Exception:
                            pass # Ya estaba desconectado o borrado

                    self.drive_scan_thread.quit()
                    self.drive_scan_thread.wait(1000)

            except RuntimeError:
                # El objeto C++ ya fue borrado (deleteLater), pero la variable Python seguía ahí.
                # No pasa nada, simplemente lo ignoramos.
                print("Aviso: El hilo anterior ya estaba eliminado.")
                self.drive_scan_thread = None

def run_visagevault():
    """Función para iniciar la aplicación gráfica."""
    app = QApplication(sys.argv)
    window = VisageVaultApp()
    window.showMaximized()
    sys.exit(app.exec())

if __name__ == "__main__":
    run_visagevault()
