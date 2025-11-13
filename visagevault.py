# ==============================================================================
# PROYECTO: VisageVault - Gestor de Fotografías Inteligente
# VERSIÓN: 0.1 pre-release
# DERECHOS DE AUTOR: © 2025 Daniel Serrano Armenta
# ==============================================================================
#
# Autor: Daniel Serrano Armenta
# Contacto: dani.eus79@gmail.com
# GitHub: github.com/danitxu79
# Portafolio: https://danitxu79.github.io/
#
# --- LICENCIA Y DERECHOS DE USO ---
#
# Este software está disponible bajo un doble modelo de licencia:
#
# 1. USO NO COMERCIAL (Licencia Pública):
#    El código base está licenciado bajo la **GNU Lesser General Public License v3 (LGPLv3)**.
#    Esto permite el uso, estudio, modificación y distribución para fines personales,
#    educativos y no comerciales. Las modificaciones al código principal deben
#    mantenerse abiertas bajo LGPLv3.
#
# 2. USO COMERCIAL (Licencia Propietaria):
#    Para cualquier uso comercial, lucrativo o que requiera evitar las restricciones
#    de copyleft de la LGPLv3, es OBLIGATORIO adquirir una **Licencia Comercial
#    Propietaria**.
#
#    Para adquirir una licencia comercial, por favor contacte al autor en:
#    dani.eus79@gmail.com
#
# ==============================================================================

import sys
import os
from pathlib import Path
import datetime
import locale

from PySide6.QtWidgets import (
    QDialog, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QDialogButtonBox, QTreeWidget, QTreeWidgetItem,
    QComboBox
)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QStyle, QFileDialog,
    QScrollArea, QGridLayout, QLabel, QGroupBox, QSpacerItem, QSizePolicy,
    QSplitter
)
from PySide6.QtCore import (
    Qt, QSize, QObject, Signal, QThread, Slot, QTimer,
    QRunnable, QThreadPool, QPropertyAnimation, QEasingCurve, QRect, QPoint
)
from PySide6.QtGui import QPixmap, QIcon, QCursor

# --- Importamos módulos auxiliares (ASUMIDOS EXISTENTES) ---
from photo_finder import find_photos
import config_manager
from metadata_reader import get_photo_date
from thumbnail_generator import generate_thumbnail, THUMBNAIL_SIZE
import metadata_reader
import piexif.helper
import re
import db_manager
from db_manager import VisageVaultDB

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
# CLASE PARA CARGAR MINIATURAS EN UN HILO SEPARADO (QRunnable)
# =================================================================
class ThumbnailLoader(QRunnable):
    """QRunnable para cargar una miniatura de forma asíncrona."""

    def __init__(self, original_filepath: str, signals: ThumbnailLoaderSignals):
        super().__init__()
        self.original_filepath = original_filepath
        # Recibimos las señales como un argumento
        self.signals = signals

    @Slot()
    def run(self):
        # ... (La lógica de run() es la misma, usando self.signals) ...
        thumbnail_path = generate_thumbnail(self.original_filepath)
        if thumbnail_path:
            try:
                pixmap = QPixmap(thumbnail_path)
                self.signals.thumbnail_loaded.emit(self.original_filepath, pixmap)
            except Exception:
                self.signals.load_failed.emit(self.original_filepath)
        else:
            self.signals.load_failed.emit(self.original_filepath)

# =================================================================
# CLASE PARA VISTA PREVIA CON ZOOM (QDialog)
# =================================================================
class ImagePreviewDialog(QDialog):
    """
    Un QDialog sin marco que muestra una imagen a pantalla completa con una
    animación de escalado al abrir y cerrar.
    """
    # Flag estático para evitar que se abra más de una instancia a la vez
    is_showing = False

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        
        ImagePreviewDialog.is_showing = True # Marcamos que una instancia está activa

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self._pixmap = pixmap # Guardamos el pixmap original
        self.label = QLabel(self)
        # self.label.setScaledContents(True) # ➤️ QUITAMOS ESTO

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

        self.animation = QPropertyAnimation(self, b"geometry")

    def wheelEvent(self, event):
        """Si el usuario gira la rueda hacia arriba y pulsa CTRL, cierra la ventana."""
        if event.modifiers() == Qt.ControlModifier and event.angleDelta().y() > 0:
            self.close_with_animation()

    def show_with_animation(self):
        """
        Muestra la ventana con una animación de zoom desde el cursor.
        La imagen se pre-escala para asegurar que quepa en pantalla.
        """
        start_pos = QCursor.pos()

        # 1. Determinar la pantalla correcta
        screen = QApplication.screenAt(start_pos)
        if not screen:
            screen = QApplication.primaryScreen()
        
        screen_geom = screen.availableGeometry()
        img_size = self._pixmap.size()

        # 2. Calcular el tamaño final
        target_size = img_size
        if (img_size.width() > screen_geom.width() * 0.9 or
            img_size.height() > screen_geom.height() * 0.9):
            target_size = img_size.scaled(
                screen_geom.size() * 0.9, Qt.KeepAspectRatio
            )

        # 3. Pre-escalar el pixmap y asignarlo al label
        scaled_pixmap = self._pixmap.scaled(
            target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.label.setPixmap(scaled_pixmap);

        # 4. Calcular la geometría final
        end_geom = QRect(QPoint(0, 0), target_size)
        end_geom.moveCenter(screen_geom.center())

        # 5. Configurar y ejecutar la animación
        start_geom = QRect(start_pos.x(), start_pos.y(), 1, 1)
        self.setGeometry(start_geom)
        
        self.animation.setDuration(200)
        self.animation.setStartValue(start_geom)
        self.animation.setEndValue(end_geom)
        self.animation.setEasingCurve(QEasingCurve.OutQuad)
        
        self.show()
        self.animation.start()

    def close_with_animation(self):
        """Cierra la ventana con una animación de zoom hacia el cursor."""
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
        """
        Este slot se ejecuta cuando la animación de cierre ha terminado.
        Resetea el flag y cierra el diálogo.
        """
        ImagePreviewDialog.is_showing = False
        self.accept()


# -----------------------------------------------------------------
# NUEVA CLASE: ZoomableClickableLabel (Combina Zoom y Doble Clic)
# -----------------------------------------------------------------
class ZoomableClickableLabel(QLabel):
    """
    Un QLabel que emite una señal de doble clic y maneja el zoom
    con la rueda del ratón o una vista previa especial.
    """
    # Señal para el doble clic (para la vista de miniaturas)
    doubleClickedPath = Signal(str)

    def __init__(self, original_path=None, parent=None):
        super().__init__(parent)
        self.original_path = original_path
        self.setAlignment(Qt.AlignCenter)

        # Atributos para el Zoom
        self._original_pixmap = QPixmap()
        self._current_scale = 1.0
        self.setMinimumSize(1, 1) # Importante para el zoom

        # NUEVO: Atributo para diferenciar el modo de vista
        self.is_thumbnail_view = False

    def setOriginalPixmap(self, pixmap: QPixmap):
        """Establece la imagen base (alta resolución) para el zoom."""
        self._original_pixmap = pixmap
        self.fitToWindow() # Ajuste inicial

    def fitToWindow(self):
        """Ajusta la imagen al tamaño actual del label (resetea el zoom)."""
        if self._original_pixmap.isNull():
            return
        self._current_scale = 1.0
        self.setPixmap(self._original_pixmap.scaled(
            self.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        ))

    def wheelEvent(self, event):
        """
        Maneja el evento de la rueda del ratón.
        - En la vista de miniaturas:
            - Con CTRL + Rueda Abajo: Abre la vista previa.
            - Sin CTRL: Permite el scroll normal.
        - En la vista de detalle: Hace zoom en la imagen.
        """
        # Si es una miniatura...
        if self.is_thumbnail_view:
            # Si se pulsa CTRL y la rueda es hacia abajo, abrimos el preview.
            if event.modifiers() == Qt.ControlModifier and event.angleDelta().y() < 0:
                self._open_preview()
            else:
                # Si no, pasamos el evento al padre (el QScrollArea) para que haga scroll.
                super().wheelEvent(event)
            return  # Importante: no continuar al código de zoom de abajo.

        # Si no, es la vista de detalle, y se aplica el zoom (sin CTRL)
        if self._original_pixmap.isNull():
            return

        angle = event.angleDelta().y()
        if angle > 0:
            self._current_scale *= 1.15  # Zoom In
        else:
            self._current_scale /= 1.15  # Zoom Out

        # Limitar el zoom para que no sea demasiado pequeño
        if self._original_pixmap.size().width() * self._current_scale < 10:
            self._current_scale = 10 / self._original_pixmap.size().width()

        self._updateScaledPixmap()

    def _open_preview(self):
        """
        Abre el diálogo de vista previa a pantalla completa, solo si no hay
        otro ya abierto.
        """
        # Prevenir que se abran múltiples vistas previas a la vez
        if ImagePreviewDialog.is_showing:
            return

        if not self.original_path:
            return
        
        # Cargamos la imagen completa para la vista previa
        full_pixmap = QPixmap(self.original_path)
        if full_pixmap.isNull():
            return

        # Creamos y mostramos el diálogo con animación
        preview_dialog = ImagePreviewDialog(full_pixmap, self)
        preview_dialog.show_with_animation()

    def _updateScaledPixmap(self):
        """Aplica el zoom actual al pixmap original."""
        if self._original_pixmap.isNull():
            return

        new_size = self._original_pixmap.size() * self._current_scale
        self.setPixmap(self._original_pixmap.scaled(
            new_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        ))

    def mouseDoubleClickEvent(self, event):
        """Maneja el doble clic (para la vista de miniaturas)."""
        if self.original_path:
            self.doubleClickedPath.emit(self.original_path)
        super().mouseDoubleClickEvent(event)

# -----------------------------------------------------------------
# CLASE MODIFICADA: PhotoDetailDialog (con Splitter y guardado de año/mes)
# -----------------------------------------------------------------
class PhotoDetailDialog(QDialog):
    """
    Ventana de detalle con splitter vertical, zoom y edición de metadatos.
    """
    # Señal para notificar a la ventana principal que los datos cambiaron
    metadata_changed = Signal() # Simplificada: solo notifica que algo cambió

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

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        self.splitter = QSplitter(Qt.Vertical)
        self.image_label = ZoomableClickableLabel()
        self.splitter.addWidget(self.image_label)

        metadata_container = QWidget()
        metadata_layout = QVBoxLayout(metadata_container)

        # --- Layout para edición de fecha ---
        edit_layout = QHBoxLayout()
        year_label = QLabel("Año:")
        self.year_edit = QLineEdit()
        self.year_edit.setMaximumWidth(80)

        month_label = QLabel("Mes:")
        self.month_combo = QComboBox()
        # Poblar con nombres de meses localizados
        self.month_combo.addItem("Mes Desconocido", "00")
        for i in range(1, 13):
            # Usamos strftime para obtener el nombre del mes de forma segura
            month_name = datetime.date(1900, i, 1).strftime('%B').capitalize()
            self.month_combo.addItem(month_name, f"{i:02d}")

        edit_layout.addWidget(year_label)
        edit_layout.addWidget(self.year_edit)
        edit_layout.addWidget(month_label)
        edit_layout.addWidget(self.month_combo)
        edit_layout.addStretch()
        metadata_layout.addLayout(edit_layout)

        self.metadata_table = QTableWidget()
        self.metadata_table.setColumnCount(2)
        self.metadata_table.setHorizontalHeaderLabels(["Metadato", "Valor"])
        self.metadata_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.metadata_table.setSelectionMode(QAbstractItemView.SingleSelection)
        metadata_layout.addWidget(self.metadata_table)

        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        button_box.accepted.connect(self._save_metadata)
        button_box.rejected.connect(self.reject)
        metadata_layout.addWidget(button_box)

        self.splitter.addWidget(metadata_container)
        self.splitter.setSizes([700, 300])
        layout.addWidget(self.splitter)

    def _load_photo(self):
        """Carga la foto completa y la pasa al label de zoom."""
        try:
            pixmap = QPixmap(self.original_path)
            self.image_label.setOriginalPixmap(pixmap)
        except Exception as e:
            self.image_label.setText(f"Error al cargar imagen: {e}")

    def _load_metadata(self):
        """Lee los metadatos y los carga en los widgets correspondientes."""
        self.exif_dict = metadata_reader.get_exif_dict(self.original_path)
        self.metadata_table.setRowCount(0)

        # --- Carga de fecha (año y mes) ---
        current_year, current_month = self.db.get_photo_date(self.original_path)
        if not current_year or not current_month:
            current_year, current_month = metadata_reader.get_photo_date(self.original_path)

        self.year_edit.setText(current_year or "Sin Fecha")
        month_index = self.month_combo.findData(current_month or "00")
        self.month_combo.setCurrentIndex(month_index if month_index != -1 else 0)

        # --- Carga de tabla de metadatos EXIF ---
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
        """
        Guarda el año y mes modificados en la base de datos.
        """
        try:
            new_year_str = self.year_edit.text()
            new_month_str = self.month_combo.currentData()

            if not (new_year_str == "Sin Fecha" or (len(new_year_str) == 4 and new_year_str.isdigit())):
                print("Error: El Año debe ser 'Sin Fecha' o un número de 4 dígitos.")
                # Opcional: Mostrar un QMessageBox de error
                return

            old_year, old_month = self.db.get_photo_date(self.original_path)

            if old_year != new_year_str or old_month != new_month_str:
                self.db.update_photo_date(self.original_path, new_year_str, new_month_str)
                self.metadata_changed.emit()

            self.accept()

        except Exception as e:
            print(f"Error al guardar la fecha en la BD: {e}")

    def resizeEvent(self, event):
        """Se llama cuando la ventana cambia de tamaño, para re-ajustar la foto."""
        # Solo reajustamos si el zoom está en el nivel base
        if self.image_label._current_scale == 1.0:
            self.image_label.fitToWindow()
        super().resizeEvent(event)

# =================================================================
# CLASE TRABAJADORA DEL ESCANEO (MODIFICADA)
# =================================================================
class PhotoFinderWorker(QObject):
    finished = Signal(dict)
    progress = Signal(str)

    def __init__(self, directory_path: str, db_manager: VisageVaultDB):
        super().__init__()
        self.directory_path = directory_path
        self.db = db_manager

    @Slot()
    def run(self):
        self.progress.emit("Cargando fechas conocidas desde la BD...")
        db_dates = self.db.load_all_photo_dates()
        
        self.progress.emit("Escaneando archivos en el directorio...")
        photo_paths_on_disk = find_photos(self.directory_path)
        
        photos_by_year_month = {}
        photos_to_upsert_in_db = []

        for path in photo_paths_on_disk:
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

        if photos_to_upsert_in_db:
            self.progress.emit(f"Guardando {len(photos_to_upsert_in_db)} fotos nuevas en la BD...")
            self.db.bulk_upsert_photos(photos_to_upsert_in_db)

        self.progress.emit(f"Escaneo finalizado. Encontradas {len(photo_paths_on_disk)} fotos.")
        self.finished.emit(photos_by_year_month)

# =================================================================
# VENTANA PRINCIPAL DE LA APLICACIÓN (VisageVaultApp)
# =================================================================
class VisageVaultApp(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("VisageVault")
        self.setWindowIcon(QIcon("visagevault.png"))
        self.setMinimumSize(QSize(900, 600))
        self.db = VisageVaultDB()
        self.current_directory = None
        self.photos_by_year_month = {}
        self.thread = None
        self.worker = None
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(os.cpu_count() or 4)
        self.thumb_signals = ThumbnailLoaderSignals()
        self.thumb_signals.thumbnail_loaded.connect(self._update_thumbnail)
        self.thumb_signals.load_failed.connect(self._handle_thumbnail_failed)
        self._setup_ui()
        QTimer.singleShot(100, self._initial_check)


    def _setup_ui(self):
        self.main_splitter = QSplitter(Qt.Horizontal)
        photo_area_widget = QWidget()
        self.photo_container_layout = QVBoxLayout(photo_area_widget)
        self.photo_container_layout.setSpacing(20)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(photo_area_widget)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._load_visible_thumbnails)
        self.main_splitter.addWidget(self.scroll_area)

        right_panel_widget = QWidget()
        right_panel_layout = QVBoxLayout(right_panel_widget)
        top_controls = QVBoxLayout()
        self.select_dir_button = QPushButton("Cambiar Directorio")
        self.select_dir_button.clicked.connect(self._open_directory_dialog)
        top_controls.addWidget(self.select_dir_button)
        self.path_label = QLabel("Ruta: No configurada")
        self.path_label.setWordWrap(True)
        top_controls.addWidget(self.path_label)
        right_panel_layout.addLayout(top_controls)
        
        # --- Reemplazar QListWidget por QTreeWidget ---
        year_label = QLabel("Navegación por Fecha:")
        right_panel_layout.addWidget(year_label)
        self.date_tree_widget = QTreeWidget()
        self.date_tree_widget.setHeaderHidden(True)
        self.date_tree_widget.currentItemChanged.connect(self._scroll_to_item)
        right_panel_layout.addWidget(self.date_tree_widget)

        self.status_label = QLabel("Estado: Inicializando...")
        right_panel_layout.addWidget(self.status_label)
        self.main_splitter.addWidget(right_panel_widget)
        self.setCentralWidget(self.main_splitter)
        self._set_status("Aplicación iniciada.")
        right_panel_widget.setMinimumWidth(180)
        self.main_splitter.splitterMoved.connect(self._save_splitter_state)
        self._load_splitter_state()

    # ----------------------------------------------------
    # Lógica de Inicio y Configuración
    # ----------------------------------------------------

    def _initial_check(self):
        """Comprueba la configuración al arrancar la app."""
        directory = config_manager.get_photo_directory()

        if directory and Path(directory).is_dir():
            self.current_directory = directory
            self.path_label.setText(f"Ruta: {Path(directory).name}")
            self._start_photo_search(directory)
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
            self._start_photo_search(directory)
        elif force_select:
             self._set_status("¡Debes seleccionar un directorio para comenzar!")

    # ----------------------------------------------------
    # Lógica de Hilos y Resultados
    # ----------------------------------------------------

    def _start_photo_search(self, directory):
        """Configura y lanza el trabajador de escaneo."""
        if self.thread and self.thread.isRunning():
            self._set_status("El escaneo anterior sigue en curso.")
            return

        self.thread = QThread()
        self.worker = PhotoFinderWorker(directory, self.db)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._handle_search_finished)
        self.worker.progress.connect(self._set_status)

        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._on_scan_thread_finished)

        self.select_dir_button.setEnabled(False)
        self.thread.start()

    @Slot(dict)
    def _handle_search_finished(self, photos_by_year):
        """Recibe las fotos agrupadas y actualiza la GUI."""
        self.photos_by_year = photos_by_year
        self.select_dir_button.setEnabled(True)

        num_fotos = sum(len(p) for p in photos_by_year.values())
        self._set_status(f"Escaneo y metadatos finalizados. {num_fotos} fotos encontradas.")

        self._display_photos()

    # ----------------------------------------------------
    # Lógica de Visualización y Miniaturas
    # ----------------------------------------------------

    def _display_photos(self):
        # Limpiar Vistas
        while self.photo_container_layout.count() > 0:
            item = self.photo_container_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.date_tree_widget.clear()
        
        self.group_widgets = {} # Almacenará { 'year-month': widget }

        # Ordenar años (descendente) y meses (ascendente)
        sorted_years = sorted(self.photos_by_year_month.keys(), reverse=True)

        for year in sorted_years:
            if year == "Sin Fecha": continue # Opcional: saltar fechas no válidas
            year_item = QTreeWidgetItem(self.date_tree_widget, [str(year)])
            self.group_widgets[year] = None # Placeholder para el grupo del año

            sorted_months = sorted(self.photos_by_year_month[year].keys())
            
            year_group_box = QGroupBox(f"Año {year}")
            year_group_box.setObjectName(f"group_{year}")
            year_main_layout = QVBoxLayout(year_group_box)
            self.group_widgets[year] = year_group_box

            for month in sorted_months:
                if month == "00": continue # Saltar mes no válido
                photos = self.photos_by_year_month[year][month]
                if not photos: continue

                # Añadir mes al árbol
                try:
                    if month and month != "00":
                        month_name = datetime.datetime.strptime(month, "%m").strftime("%B").capitalize()
                    else:
                        month_name = "Mes Desconocido"
                except ValueError:
                    month_name = "Mes Desconocido"
                
                month_item = QTreeWidgetItem(year_item, [f"{month_name} ({len(photos)})"])
                month_item.setData(0, Qt.UserRole, (year, month)) # Guardar año y mes

                # Añadir separador y rejilla de fotos para el mes
                month_label = QLabel(month_name)
                month_label.setStyleSheet("font-size: 14pt; font-weight: bold; margin-top: 10px;")
                year_main_layout.addWidget(month_label)
                self.group_widgets[f"{year}-{month}"] = month_label

                photo_grid_widget = QWidget()
                photo_grid_layout = QGridLayout(photo_grid_widget)
                
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
                    row, col = i // 5, i % 5
                    photo_grid_layout.addWidget(photo_label, row, col)
                
                year_main_layout.addWidget(photo_grid_widget)

            self.photo_container_layout.addWidget(year_group_box)
            year_item.setExpanded(True)

        self.photo_container_layout.addStretch(1)
        QTimer.singleShot(100, self._load_visible_thumbnails)

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _scroll_to_item(self, current_item: QTreeWidgetItem, previous_item: QTreeWidgetItem):
        if not current_item: return

        # Si es un item de mes (tiene padre)
        if current_item.parent():
            year, month = current_item.data(0, Qt.UserRole)
            target_key = f"{year}-{month}"
        # Si es un item de año (no tiene padre)
        else:
            year = current_item.text(0)
            target_key = year
        
        target_widget = self.group_widgets.get(target_key)
        if target_widget:
            self.scroll_area.ensureWidgetVisible(target_widget, 50, 50)
            QTimer.singleShot(200, self._load_visible_thumbnails)

    @Slot(dict)
    def _handle_search_finished(self, photos_by_year_month):
        self.photos_by_year_month = photos_by_year_month
        self.select_dir_button.setEnabled(True)
        num_fotos = sum(len(photos) for months in photos_by_year_month.values() for photos in months.values())
        self._set_status(f"Escaneo finalizado. {num_fotos} fotos encontradas.")
        self._display_photos()

    def _set_status(self, message):
        self.status_label.setText(f"Estado: {message}")

    def _load_visible_thumbnails(self):
        viewport = self.scroll_area.viewport()
        preload_rect = viewport.rect().adjusted(0, -PRELOAD_MARGIN_PX, 0, PRELOAD_MARGIN_PX)
        for photo_label in self.scroll_area.widget().findChildren(QLabel):
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
    def _update_thumbnail(self, original_path: str, pixmap: QPixmap):
        for photo_label in self.scroll_area.widget().findChildren(QLabel):
            if photo_label.property("original_path") == original_path:
                photo_label.setPixmap(pixmap.scaled(THUMBNAIL_SIZE[0], THUMBNAIL_SIZE[1], Qt.KeepAspectRatio, Qt.SmoothTransformation))
                photo_label.setText("")
                photo_label.setProperty("loaded", True)
                break

    @Slot(str)
    def _handle_thumbnail_failed(self, original_path: str):
        """Maneja el caso en que la miniatura no se pudo cargar."""
        for photo_label in self.scroll_area.widget().findChildren(QLabel):
            if photo_label.property("original_path") == original_path:
                photo_label.setText("Error al cargar.")
                photo_label.setProperty("loaded", True) # Marcar como "terminado" para no reintentar
                break

    @Slot()
    def _save_splitter_state(self):
        """Guarda las posiciones del splitter en la configuración."""
        sizes = self.main_splitter.sizes()
        config_data = config_manager.load_config()
        config_data['splitter_sizes'] = sizes
        config_manager.save_config(config_data)

    def _load_splitter_state(self):
        """Carga las posiciones del splitter desde la configuración."""
        config_data = config_manager.load_config()
        sizes = config_data.get('splitter_sizes')

        # Definir el ancho mínimo (DEBE SER EL MISMO que en _setup_ui)
        min_right_width = 150

        if sizes and len(sizes) == 2:
            # Asegurarse de que el tamaño cargado respeta el mínimo
            if sizes[1] < min_right_width:
                # Ajusta el tamaño izquierdo para compensar
                sizes[0] = sizes[0] + (sizes[1] - min_right_width)
                # Forza el tamaño mínimo derecho
                sizes[1] = min_right_width

            self.main_splitter.setSizes(sizes)
        else:
            # Si no hay configuración, establecemos un 80% / 20% por defecto
            default_width = self.width()
            default_sizes = [int(default_width * 0.8), int(default_width * 0.2)]

            # Asegurarse de que el valor por defecto respeta el mínimo
            if default_sizes[1] < min_right_width:
                 default_sizes[1] = min_right_width
                 default_sizes[0] = default_width - min_right_width

            self.main_splitter.setSizes(default_sizes)

    @Slot()
    def _on_scan_thread_finished(self):
        """
        Slot de limpieza que se llama cuando el QThread ha terminado.
        Resetea las variables de Python.
        """
        self.thread = None
        self.worker = None

    @Slot(str)
    def _open_photo_detail(self, original_path):
        """Abre la ventana de detalle de la foto."""
        self._set_status(f"Abriendo detalle para: {Path(original_path).name}")

        dialog = PhotoDetailDialog(original_path, self.db, self)
        dialog.metadata_changed.connect(self._handle_photo_date_changed)
        dialog.exec()

        self._set_status("Detalle cerrado.")

    @Slot()
    def _handle_photo_date_changed(self):
        """
        Actualiza la vista reconstruyendo todo cuando una fecha cambia.
        """
        self._set_status("Metadatos cambiados. Reconstruyendo vista...")
        if self.current_directory:
            self._start_photo_search(self.current_directory)


def run_visagevault():
    """Función para iniciar la aplicación gráfica."""
    app = QApplication(sys.argv)
    window = VisageVaultApp()
    window.showMaximized()
    sys.exit(app.exec())

if __name__ == "__main__":
    run_visagevault()
