# ==============================================================================
# PROYECTO: VisageVault - Gestor de Fotografías Inteligente
# VERSIÓN: 0.2 pre-release
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
# Este proyecto se ofrece bajo un modelo de Doble Licencia (Dual License), brindando máxima flexibilidad:
#
# 1. Licencia Pública (LGPLv3)
#
# Este software está disponible bajo la GNU Lesser General Public License v3.0 (LGPLv3).
# Puedes usarlo libremente de acuerdo con los términos de la LGPLv3, lo cual es ideal para proyectos de código abierto. En resumen, esto significa que si usas esta biblioteca
# (especialmente si la modificas), debes cumplir con las obligaciones de la LGPLv3, como publicar el código fuente de tus modificaciones a esta biblioteca y permitir que los usuarios
# la reemplacen.
# Puedes encontrar el texto completo de la licencia en el archivo LICENSE de este repositorio.
#
# 2. Licencia Comercial (Privativa)
#
# Si los términos de la LGPLv3 no se ajustan a tus necesidades, ofrezco una licencia comercial alternativa.
# Necesitarás una licencia comercial si, por ejemplo:
#
#    Deseas incluir el código en un software propietario (código cerrado) sin tener que publicar tus modificaciones.
#    Necesitas enlazar estáticamente (static linking) la biblioteca con tu aplicación propietaria.
#    Prefieres no estar sujeto a las obligaciones y restricciones de la LGPLv3.
#
# La licencia comercial te otorga el derecho a usar el código en tus aplicaciones comerciales de código cerrado sin las restricciones de la LGPLv3, a cambio de una tarifa.
# Para adquirir una licencia comercial o para más información, por favor, pónte en contacto conmigo en:
#
# dani.eus79@gmail.com
#
#
# ==============================================================================

import sys
import os
from pathlib import Path
import datetime
import locale
import warnings


# --- Silenciar solo el aviso de pkg_resources ---
warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API",
    category=UserWarning,
)


from PySide6.QtWidgets import (
    QDialog, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QDialogButtonBox, QTreeWidget, QTreeWidgetItem,
    QComboBox
)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QStyle, QFileDialog,
    QScrollArea, QGridLayout, QLabel, QGroupBox, QSpacerItem, QSizePolicy,
    QSplitter, QTabWidget
)
from PySide6.QtCore import (
    Qt, QSize, QObject, Signal, QThread, Slot, QTimer,
    QRunnable, QThreadPool, QPropertyAnimation, QEasingCurve, QRect, QPoint, QRectF,
    QPointF, QBuffer, QIODevice
)
from PySide6.QtGui import (
    QPixmap, QIcon, QCursor, QTransform, QPainter, QPaintEvent,
    QPainterPath
)

from photo_finder import find_photos
import config_manager
from metadata_reader import get_photo_date
from thumbnail_generator import generate_thumbnail, THUMBNAIL_SIZE
import metadata_reader
import piexif.helper
import re
import db_manager
from db_manager import VisageVaultDB
import face_recognition
from PIL import Image
import ast
import pickle

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
    Un QDialog sin marco que usa ZoomableClickableLabel para mostrar una
    imagen con zoom y animación.
    """
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

        # Establecer el tamaño de la ventana
        self.resize(target_size)

        # Calcular posición centrada
        center_x = screen_geom.x() + (screen_geom.width() - target_size.width()) // 2
        center_y = screen_geom.y() + (screen_geom.height() - target_size.height()) // 2

        # Mover la ventana a la posición centrada
        self.move(center_x, center_y)

        self.show()

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
        """Resetea el flag y cierra el diálogo."""
        ImagePreviewDialog.is_showing = False
        self.accept()

    def resizeEvent(self, event):
        """Reescala el pixmap para que se ajuste si no estamos zoomeados."""
        if self.label._current_scale == 1.0:
            self.label.fitToWindow()
        super().resizeEvent(event)

# =================================================================
# CLASE PARA MOSTRAR CARAS RECORTADAS (CIRCULAR Y CLICABLE)
# =================================================================
class CircularFaceLabel(QLabel):
    """
    Un QLabel que muestra un QPixmap recortado en forma de círculo
    y emite una señal 'clicked' cuando se presiona.
    """
    # --- NUEVA SEÑAL ---
    clicked = Signal()

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.setFixedSize(100, 100) # Tamaño fijo para la cuadrícula de caras

        # Escala la imagen para que "rellene" el círculo
        self._pixmap = pixmap.scaled(100, 100, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.setToolTip("Cara detectada (Haz clic para etiquetar)")
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event: QPaintEvent):
        """Pinta la imagen de forma circular."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing) # Suavizado de bordes

        path = QPainterPath()
        # Crea un círculo/elipse del tamaño del widget
        path.addEllipse(0, 0, self.width(), self.height())

        # Establece el círculo como la "máscara" de recorte
        painter.setClipPath(path)

        # Dibuja la imagen
        painter.drawPixmap(0, 0, self._pixmap)

        painter.end()

    # --- NUEVO MÉTODO ---
    def mousePressEvent(self, event):
        """Emite la señal 'clicked' al hacer clic."""
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

# =================================================================
# CLASE: ZoomableClickableLabel (CON ZOOM AL PUNTERO)
# =================================================================
class ZoomableClickableLabel(QLabel):
    """
    Un QLabel que emite una señal de doble clic, maneja la vista previa
    (Ctrl+Rueda) y permite un zoom dinámico al puntero y arrastre (panning)
    en la vista de detalle.
    """
    doubleClickedPath = Signal(str)

    def __init__(self, original_path=None, parent=None):
        super().__init__(parent)
        self.original_path = original_path
        self.setAlignment(Qt.AlignCenter)
        self.setMouseTracking(True)

        # --- Atributos de Zoom y Panning ---
        self._original_pixmap = QPixmap()
        self._current_scale = 1.0
        self._scale_factor = 1.15
        self._view_offset = QPointF(0.0, 0.0)
        self._panning = False
        self._last_mouse_pos = QPoint()
        self.is_thumbnail_view = False # Por defecto, NO es miniatura
        self.setCursor(Qt.OpenHandCursor)

    def setOriginalPixmap(self, pixmap: QPixmap):
        """Establece la imagen original y reinicia el zoom."""
        if pixmap.isNull():
            self._original_pixmap = QPixmap()
        else:
            self._original_pixmap = pixmap

        self._current_scale = 1.0
        self._view_offset = QPointF(0.0, 0.0)
        self.fitToWindow()

    def fitToWindow(self):
        """Ajusta la imagen para que quepa en el label (resetea el zoom)."""
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

        # --- !! ESTA ES LA CORRECCIÓN !! ---
        # En lugar de resetear el offset a (0,0), llamamos a _clamp_view_offset.
        # _clamp_view_offset detectará que la imagen es más pequeña que
        # la ventana y calculará el offset negativo necesario para centrarla.
        self._clamp_view_offset()
        # ---------------------------------

        self.update() # Repintar

    def wheelEvent(self, event):
        """Gestiona el zoom con la rueda del ratón."""

        # --- LÓGICA DE CIERRE/APERTURA (CON CTRL) ---
        if event.modifiers() == Qt.ControlModifier:
            if self.is_thumbnail_view:
                # Si es miniatura, Ctrl+Rueda Abajo abre la vista previa
                if event.angleDelta().y() < 0:
                    self._open_preview()
                else:
                    # Si es Ctrl+Rueda Arriba, la ignoramos y pasamos al scroll
                    super().wheelEvent(event)
            else:
                # Si NO es miniatura (es vista previa o detalle),
                # Ctrl+Rueda Arriba CIERRA
                if event.angleDelta().y() > 0:
                    parent_dialog = self.window()
                    if isinstance(parent_dialog, ImagePreviewDialog):
                        parent_dialog.close_with_animation()
                # Si es Ctrl+Rueda Arriba, la ignoramos (no hace zoom, no cierra)

            return # Evento consumido

        # --- LÓGICA DE SCROLL/ZOOM (SIN CTRL) ---

        # 1. Si es miniatura, pasa el evento al ScrollArea
        if self.is_thumbnail_view:
            super().wheelEvent(event)
            return

        # 2. Si es vista previa/detalle, hace zoom al puntero
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
        """Inicia el arrastre de la imagen (panning)."""
        if event.button() == Qt.LeftButton and not self.is_thumbnail_view:
            self._panning = True
            self._last_mouse_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Mueve la imagen al arrastrar."""
        if self._panning and not self.is_thumbnail_view:
            delta = event.position().toPoint() - self._last_mouse_pos
            self._view_offset -= QPointF(delta.x() / self._current_scale, delta.y() / self._current_scale)
            self._last_mouse_pos = event.position().toPoint()
            self._clamp_view_offset()
            self.update()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Termina el arrastre."""
        if event.button() == Qt.LeftButton and not self.is_thumbnail_view:
            self._panning = False
            self.setCursor(Qt.OpenHandCursor)

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Maneja el doble clic."""
        if self.is_thumbnail_view and self.original_path:
            self.doubleClickedPath.emit(self.original_path)

        if not self.is_thumbnail_view:
            self.fitToWindow() # Doble clic en detalle resetea el zoom

        super().mouseDoubleClickEvent(event)

    def _clamp_view_offset(self):
        """Ajusta el offset para que la vista no se salga de la imagen."""
        if self._original_pixmap.isNull() or self._current_scale == 0: return

        scaled_img_width = self._original_pixmap.width() * self._current_scale
        scaled_img_height = self._original_pixmap.height() * self._current_scale

        # Si la imagen es más pequeña que la ventana, el offset es 0 (se centrará en paintEvent)
        if scaled_img_width < self.width():
            self._view_offset.setX(0)
        else:
            # Limitar bordes (no ir más allá de 0 o el máximo)
            max_x_offset = self._original_pixmap.width() - (self.width() / self._current_scale)
            self._view_offset.setX(max(0.0, min(self._view_offset.x(), max_x_offset)))

        if scaled_img_height < self.height():
            self._view_offset.setY(0)
        else:
            # Limitar bordes
            max_y_offset = self._original_pixmap.height() - (self.height() / self._current_scale)
            self._view_offset.setY(max(0.0, min(self._view_offset.y(), max_y_offset)))

    def paintEvent(self, event: QPaintEvent):
        """Dibuja la porción visible de la imagen."""

        if self.is_thumbnail_view:
            super().paintEvent(event)
            return

        if self._original_pixmap.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # --- LÓGICA DE DIBUJADO Y CENTRADO ---

        # 1. Calcular el tamaño de la imagen escalada
        scaled_width = self._original_pixmap.width() * self._current_scale
        scaled_height = self._original_pixmap.height() * self._current_scale

        # 2. Calcular dónde dibujar en la pantalla (Target Rect)
        #    Si la imagen es más pequeña que la ventana, la centramos.

        target_x = 0.0
        target_y = 0.0

        if scaled_width < self.width():
            target_x = (self.width() - scaled_width) / 2.0

        if scaled_height < self.height():
            target_y = (self.height() - scaled_height) / 2.0

        # El rectángulo de destino en la pantalla
        target_rect = QRectF(target_x, target_y, scaled_width, scaled_height)

        # 3. Calcular qué parte de la imagen original vamos a dibujar (Source Rect)
        src_x = self._view_offset.x()
        src_y = self._view_offset.y()

        # El ancho/alto de la fuente es el ancho/alto de la VISTA (self) / escala
        src_width = self.width() / self._current_scale
        src_height = self.height() / self._current_scale

        # Si la imagen es más pequeña que la vista (zoom out),
        # usamos la imagen completa como fuente y ajustamos el offset.
        if scaled_width < self.width():
            src_width = self._original_pixmap.width()
            # (src_x ya es 0.0 gracias a _clamp_view_offset)

        if scaled_height < self.height():
            src_height = self._original_pixmap.height()
            # (src_y ya es 0.0 gracias a _clamp_view_offset)

        source_rect = QRectF(src_x, src_y, src_width, src_height)

        # 4. Dibujar
        painter.drawPixmap(target_rect, self._original_pixmap, source_rect)
        painter.end()

    def resizeEvent(self, event):
        """Gestiona el redimensionamiento del label."""
        if not self.is_thumbnail_view:
            self.fitToWindow()
        super().resizeEvent(event)

    def _open_preview(self):
        """Abre el diálogo de vista previa a pantalla completa (Ctrl+Rueda)."""
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
# CLASE MODIFICADA: PhotoDetailDialog (con Splitter y guardado de año/mes)
# -----------------------------------------------------------------
class PhotoDetailDialog(QDialog):
    """
    Ventana de detalle con splitter vertical, zoom y edición de metadatos.
    """
    # Señal para notificar a la ventana principal que los datos cambiaron
    metadata_changed = Signal(str, str, str)

    def _setup_ui(self):
        # --- Diseño principal ---
        main_layout = QVBoxLayout(self)
        self.main_splitter = QSplitter(Qt.Horizontal) # Splitter horizontal
        main_layout.addWidget(self.main_splitter)

        # --- 1. Panel Izquierdo (Imagen con Zoom) ---
        # Usamos el ZoomableClickableLabel que ya está definido
        self.image_label = ZoomableClickableLabel(self.original_path, self)
        self.image_label.is_thumbnail_view = False # IMPORTANTE: Habilitar zoom/pan
        self.main_splitter.addWidget(self.image_label)

        # --- 2. Panel Derecho (Metadatos y Edición) ---
        right_panel_widget = QWidget()
        right_panel_layout = QVBoxLayout(right_panel_widget)
        right_panel_widget.setMinimumWidth(300) # Darle un ancho mínimo
        right_panel_widget.setMaximumWidth(450) # Y un máximo

        # Grupo de Edición de Fecha
        date_group = QGroupBox("Fecha (Base de Datos)")
        date_layout = QGridLayout(date_group)

        date_layout.addWidget(QLabel("Año:"), 0, 0)
        self.year_edit = QLineEdit()
        self.year_edit.setPlaceholderText("Ej: 2024 o 'Sin Fecha'")
        date_layout.addWidget(self.year_edit, 0, 1)

        date_layout.addWidget(QLabel("Mes:"), 1, 0)
        self.month_combo = QComboBox()
        # Llenar el combo de meses
        self.month_combo.addItem("Mes Desconocido", "00")
        for i in range(1, 13):
            month_str = str(i).zfill(2)
            try:
                month_name = datetime.datetime.strptime(month_str, "%m").strftime("%B").capitalize()
            except ValueError:
                month_name = datetime.date(2000, i, 1).strftime("%B").capitalize()
            self.month_combo.addItem(month_name, month_str)
        date_layout.addWidget(self.month_combo, 1, 1)

        # Grupo de Metadatos EXIF (Tabla)
        exif_group = QGroupBox("Datos EXIF (Solo Lectura)")
        exif_layout = QVBoxLayout(exif_group)

        self.metadata_table = QTableWidget()
        self.metadata_table.setColumnCount(2)
        self.metadata_table.setHorizontalHeaderLabels(["Campo", "Valor"])
        self.metadata_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.metadata_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.metadata_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers) # Solo lectura

        exif_layout.addWidget(self.metadata_table)

        # Añadimos el grupo de fecha (stretch 0 = tamaño fijo)
        right_panel_layout.addWidget(date_group)

        # Añadimos el grupo EXIF con un factor de estiramiento de 1
        # para que ocupe todo el espacio vertical restante.
        right_panel_layout.addWidget(exif_group, 1)

        # (Línea eliminada) right_panel_layout.addStretch(1)

        self.main_splitter.addWidget(right_panel_widget)

        # --- Botones (Aceptar/Cancelar) ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self._save_metadata)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

        # --- Configuración del Splitter ---
        # Establecemos un tamaño por defecto (70% imagen, 30% datos)
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
        # 1. Cargar la fecha guardada en la Base de Datos
        current_year, current_month = self.db.get_photo_date(self.original_path)

        # 2. Si falta algún dato (es None), intentar rellenarlo desde EXIF
        if current_year is None or current_month is None:
            exif_year, exif_month = metadata_reader.get_photo_date(self.original_path)

            # Rellenar solo los huecos, priorizando la BD
            if current_year is None:
                current_year = exif_year
            if current_month is None:
                current_month = exif_month

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
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self,
                                    "Datos Inválidos",
                                    "El Año debe ser 'Sin Fecha' o un número de 4 dígitos (ej: 2024).")
                return

            old_year, old_month = self.db.get_photo_date(self.original_path)

            if old_year != new_year_str or old_month != new_month_str:
                self.db.update_photo_date(self.original_path, new_year_str, new_month_str)
                # Emite los datos nuevos
                self.metadata_changed.emit(self.original_path, new_year_str, new_month_str)

            self.accept()

        except Exception as e:
            print(f"Error al guardar la fecha en la BD: {e}")

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
        # 1. Llama a find_photos UNA SOLA VEZ
        photo_paths_on_disk = find_photos(self.directory_path)

        # 2. Crea el set a partir de la lista (rápido, en memoria)
        photo_paths_on_disk_set = set(photo_paths_on_disk)

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

        self.progress.emit("Buscando fotos eliminadas...")
        db_paths_set = set(db_dates.keys())
        paths_to_delete = list(db_paths_set - photo_paths_on_disk_set)

        if paths_to_delete:
            self.progress.emit(f"Eliminando {len(paths_to_delete)} fotos de la BD...")
            self.db.bulk_delete_photos(paths_to_delete) # (Necesitarías crear este método en db_manager)

        if photos_to_upsert_in_db:
            self.progress.emit(f"Guardando {len(photos_to_upsert_in_db)} fotos nuevas en la BD...")
            self.db.bulk_upsert_photos(photos_to_upsert_in_db)

        self.progress.emit(f"Escaneo finalizado. Encontradas {len(photo_paths_on_disk)} fotos.")
        self.finished.emit(photos_by_year_month)

# =================================================================
# CLASE TRABAJADORA DEL ESCANEO DE CARAS (QThread)
# =================================================================
class FaceScanSignals(QObject):
    """Señales para el trabajador de escaneo de caras."""
    scan_progress = Signal(str)
    scan_percentage = Signal(int)
    scan_finished = Signal() # Se emite cuando todo el lote ha terminado

class FaceScanWorker(QObject):
    """
    Escanea fotos no procesadas en un hilo separado para encontrar caras.
    """
    def __init__(self, db_manager: VisageVaultDB):
        super().__init__()
        self.db = db_manager
        self.signals = FaceScanSignals()

    @Slot()
    def run(self):
        """
        Bucle principal del trabajador.
        """
        try:
            self.signals.scan_progress.emit("Buscando fotos sin escanear...")
            unscanned_photos = self.db.get_unscanned_photos()
            total = len(unscanned_photos)
            if total == 0:
                self.signals.scan_progress.emit("No hay fotos nuevas que escanear.")
                self.signals.scan_percentage.emit(100)
                self.signals.scan_finished.emit()
                return

            self.signals.scan_progress.emit(f"Escaneando {total} fotos nuevas para caras...")

            for i, row in enumerate(unscanned_photos):
                photo_id = row['id']
                photo_path = row['filepath']

                self.signals.scan_progress.emit(f"Procesando ({i+1}/{total}): {Path(photo_path).name}")
                # Calcular porcentaje y emitirlo
                percentage = (i + 1) * 100 // total
                self.signals.scan_percentage.emit(percentage)

                try:
                    # Cargar imagen
                    image = face_recognition.load_image_file(photo_path)

                    # 1. Encontrar ubicaciones
                    locations = face_recognition.face_locations(image)

                    if not locations:
                        # Si no hay caras, marcarla y continuar
                        self.db.mark_photo_as_scanned(photo_id)
                        continue

                    # 2. Encontrar "encodings" (datos de la cara)
                    encodings = face_recognition.face_encodings(image, locations)

                    # 3. Guardar cada cara en la BD
                    for loc, enc in zip(locations, encodings):
                        location_str = str(loc) # Guardamos la tupla (top, right, bottom, left) como string
                        encoding_blob = pickle.dumps(enc) # Serializamos el array numpy

                        self.db.add_face(photo_id, encoding_blob, location_str)

                    # 4. Marcar la foto como procesada
                    self.db.mark_photo_as_scanned(photo_id)

                except Exception as e:
                    print(f"Error procesando caras en {photo_path}: {e}")
                    # Marcamos como escaneada igualmente para no reintentar
                    self.db.mark_photo_as_scanned(photo_id)

            self.signals.scan_progress.emit("Escaneo de caras finalizado.")
            self.signals.scan_finished.emit()

        except Exception as e:
            print(f"Error crítico en el hilo de escaneo de caras: {e}")
            self.signals.scan_progress.emit(f"Error: {e}")
            self.signals.scan_finished.emit() # Emitir para desbloquear la UI

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
        self.face_scan_thread = None
        self.face_scan_worker = None
        self.face_loading_label = None
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(os.cpu_count() or 4)
        self.thumb_signals = ThumbnailLoaderSignals()
        self.thumb_signals.thumbnail_loaded.connect(self._update_thumbnail)
        self.thumb_signals.load_failed.connect(self._handle_thumbnail_failed)
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(200) # 200ms de espera
        self.resize_timer.timeout.connect(self._handle_resize_timeout)
        self._setup_ui()
        QTimer.singleShot(100, self._initial_check)


    def _setup_ui(self):
        # 1. Crear el QTabWidget
        self.tab_widget = QTabWidget()

        # 2. Crear la Pestaña "Fotos" (Contendrá el splitter actual)
        fotos_tab_widget = QWidget()
        fotos_layout = QVBoxLayout(fotos_tab_widget)
        fotos_layout.setContentsMargins(0, 0, 0, 0) # Sin márgenes

        # 3. Crear el Splitter (como antes, pero lo añadiremos al fotos_layout)
        self.main_splitter = QSplitter(Qt.Horizontal)

        # --- (Inicio: Código del Splitter - Lado Izquierdo: Fotos) ---
        photo_area_widget = QWidget()
        self.photo_container_layout = QVBoxLayout(photo_area_widget)
        self.photo_container_layout.setSpacing(20)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(photo_area_widget)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._load_visible_thumbnails)
        self.main_splitter.addWidget(self.scroll_area)
        # --- (Fin: Lado Izquierdo: Fotos) ---

        # --- (Inicio: Código del Splitter - Lado Derecho: Navegación) ---
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

        year_label = QLabel("Navegación por Fecha:")
        right_panel_layout.addWidget(year_label)
        self.date_tree_widget = QTreeWidget()
        self.date_tree_widget.setHeaderHidden(True)
        self.date_tree_widget.currentItemChanged.connect(self._scroll_to_item)
        right_panel_layout.addWidget(self.date_tree_widget)

        self.status_label = QLabel("Estado: Inicializando...")
        right_panel_layout.addWidget(self.status_label)
        self.main_splitter.addWidget(right_panel_widget)
        # --- (Fin: Lado Derecho: Navegación) ---

        # 4. Añadir el splitter al layout de la Pestaña "Fotos"
        fotos_layout.addWidget(self.main_splitter)

        # 5. Crear la Pestaña "Personas" (Interfaz real)
        self.personas_tab_widget = QWidget()
        personas_layout = QVBoxLayout(self.personas_tab_widget)
        personas_layout.setContentsMargins(0, 0, 0, 0)

        # 5a. Crear el Splitter para la pestaña "Personas"
        self.people_splitter = QSplitter(Qt.Horizontal)

        # 5b. Panel Izquierdo (Cuadrícula de Caras)
        face_area_widget = QWidget()
        self.face_container_layout = QVBoxLayout(face_area_widget)

        # Aquí crearemos la cuadrícula, pero la pondremos dentro de un GroupBox
        # Empezamos con las caras "Sin Asignar"
        self.unknown_faces_group = QGroupBox("Caras Sin Asignar")
        self.unknown_faces_layout = QGridLayout(self.unknown_faces_group)
        self.unknown_faces_layout.setSpacing(10)
        self.face_container_layout.addWidget(self.unknown_faces_group)

        self.face_container_layout.addStretch(1) # Empuja todo hacia arriba

        self.face_scroll_area = QScrollArea()
        self.face_scroll_area.setWidgetResizable(True)
        self.face_scroll_area.setWidget(face_area_widget)
        self.people_splitter.addWidget(self.face_scroll_area)

        # 5c. Panel Derecho (El "Cajón" de Nombres de Personas)
        people_panel_widget = QWidget()
        people_panel_layout = QVBoxLayout(people_panel_widget)
        people_panel_widget.setMinimumWidth(180) # Igual que el panel de navegación
        people_panel_widget.setMaximumWidth(450)

        people_label = QLabel("Navegación por Personas:")
        people_panel_layout.addWidget(people_label)

        self.people_tree_widget = QTreeWidget()
        self.people_tree_widget.setHeaderHidden(True)
        # self.people_tree_widget.currentItemChanged.connect(self._scroll_to_person)
        people_panel_layout.addWidget(self.people_tree_widget)

        # Botones de acción (ej: "Nueva Persona")
        self.add_person_button = QPushButton("Añadir Persona")
        # self.add_person_button.clicked.connect(self._add_new_person)
        people_panel_layout.addWidget(self.add_person_button)

        self.people_splitter.addWidget(people_panel_widget)

        # 5d. Añadir el splitter de personas al layout de la pestaña
        personas_layout.addWidget(self.people_splitter)

        # 5e. Ajustar tamaños del splitter de personas
        self.people_splitter.setSizes([int(self.width() * 0.8), int(self.width() * 0.2)])

        # 6. Añadir las pestañas al TabWidget
        self.tab_widget.addTab(fotos_tab_widget, "Fotos")
        self.tab_widget.addTab(self.personas_tab_widget, "Personas")

        # 7. Establecer el TabWidget como el Widget Central
        self.setCentralWidget(self.tab_widget)

        # 8. Cargar el estado del splitter (como antes)
        right_panel_widget.setMinimumWidth(180)
        self.main_splitter.splitterMoved.connect(self._save_splitter_state)
        self._load_splitter_state()
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

    # ----------------------------------------------------
    # Escaneo de caras
    # ----------------------------------------------------
    def _start_face_scan(self):
        """Configura y lanza el trabajador de escaneo de caras."""
        if self.face_scan_thread and self.face_scan_thread.isRunning():
            self._set_status("El escaneo de caras ya está en curso.")
            return

        self.face_scan_thread = QThread()
        self.face_scan_worker = FaceScanWorker(self.db)
        self.face_scan_worker.moveToThread(self.face_scan_thread)

        # Conectar señales del worker
        self.face_scan_worker.signals.scan_progress.connect(self._set_status)
        self.face_scan_worker.signals.scan_percentage.connect(self._update_face_scan_percentage)
        self.face_scan_worker.signals.scan_finished.connect(self._load_faces_to_grid)

        # Conectar control del hilo
        self.face_scan_thread.started.connect(self.face_scan_worker.run)
        self.face_scan_worker.signals.scan_finished.connect(self.face_scan_thread.quit)
        self.face_scan_worker.signals.scan_finished.connect(self.face_scan_worker.deleteLater)
        self.face_scan_thread.finished.connect(self.face_scan_thread.deleteLater)

        self._set_status("Iniciando escaneo de caras...")
        self.face_scan_thread.start()

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

        # --- INICIO DE LA LÓGICA RESPONSIVE ---

        # 1. Calcular el ancho disponible.
        #    Restamos 30px para dar margen al borde y la barra de scroll.
        viewport_width = self.scroll_area.viewport().width() - 30

        # 2. Calcular el ancho de cada miniatura
        #    (Tu código usa 128px + 10px de padding = 138px)
        thumb_width = THUMBNAIL_SIZE[0] + 10

        # 3. Calcular cuántas columnas caben (asegurando un mínimo de 1)
        num_cols = max(1, viewport_width // thumb_width)

        # --- FIN DE LA LÓGICA RESPONSIVE ---

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

                # --- NUEVO: Añadir espacio entre las miniaturas ---
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

                    # --- MODIFICADO: Usamos 'num_cols' en lugar de '5' ---
                    row, col = i // num_cols, i % num_cols

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
        min_right_width = 180

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

    def resizeEvent(self, event):
        """Se llama cada vez que la ventana cambia de tamaño."""
        # Reinicia el temporizador cada vez que nos movemos
        self.resize_timer.start()
        # Llama al evento original
        super().resizeEvent(event)

    @Slot()
    def _handle_resize_timeout(self):
        """
        Se llama 200ms después de que el usuario DEJA de redimensionar.
        Vuelve a dibujar la cuadrícula con el nuevo tamaño.
        """
        # Si no hay fotos cargadas, no hagas nada
        if not self.photos_by_year_month:
            return

        print(f"Redibujando layout para el nuevo ancho.")
        self._display_photos()

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
    def _handle_photo_date_changed(self, photo_path: str, new_year: str, new_month: str):
        """
        Actualiza la vista moviendo la foto en la estructura de datos
        en memoria y reconstruyendo la UI.
        """
        self._set_status("Metadatos cambiados. Reconstruyendo vista...")

        # 1. Encontrar y eliminar la foto de su antigua ubicación en memoria
        path_found_and_removed = False
        for year, months in self.photos_by_year_month.items():
            for month, photos in months.items():
                if photo_path in photos:
                    photos.remove(photo_path)
                    path_found_and_removed = True
                    # Opcional: limpiar claves vacías
                    if not photos:
                        del self.photos_by_year_month[year][month]
                    if not self.photos_by_year_month[year]:
                        del self.photos_by_year_month[year]
                    break
            if path_found_and_removed:
                break

        # 2. Añadir la foto a su nueva ubicación en memoria
        if new_year not in self.photos_by_year_month:
            self.photos_by_year_month[new_year] = {}
        if new_month not in self.photos_by_year_month[new_year]:
            self.photos_by_year_month[new_year][new_month] = []

        self.photos_by_year_month[new_year][new_month].append(photo_path)

        # 3. Reconstruir la UI (esto es rápido, es solo UI)
        self._display_photos()

    @Slot(int)
    def _on_tab_changed(self, index):
        """
        Se llama cuando el usuario cambia de pestaña (Fotos <-> Personas).
        """
        # Obtenemos el nombre de la pestaña
        tab_name = self.tab_widget.tabText(index)

        if tab_name == "Personas":
            self._set_status("Cargando vista de personas...")
            self._load_people_list()

            # --- INICIO DE LA MODIFICACIÓN ---

            # Comprobar SI YA hay un escaneo en curso ANTES de tocar la UI
            if self.face_scan_thread and self.face_scan_thread.isRunning():
                # Ya hay un escaneo. No hacer nada.
                # El label de porcentaje que ya existía seguirá actualizándose.
                # No limpiamos la cuadrícula, no ponemos un nuevo label de "0%".
                self._set_status("Escaneo de caras en curso...")
            else:
                # No hay escaneo. Este es un inicio limpio.

                # 1. Limpiar la cuadrícula inmediatamente
                while self.unknown_faces_layout.count() > 0:
                    item = self.unknown_faces_layout.takeAt(0)
                    if item.widget(): item.widget().deleteLater()

                # 2. Mostrar el mensaje y GUARDAR la referencia
                self.face_loading_label = QLabel("Buscando caras de personas... 0%")
                self.face_loading_label.setAlignment(Qt.AlignCenter)
                self.face_loading_label.setStyleSheet("font-size: 14pt;")

                self.unknown_faces_layout.addWidget(self.face_loading_label, 0, 0, Qt.AlignCenter)

                # 3. Iniciar el escaneo (ahora sí)
                self._start_face_scan()

            # --- FIN DE LA MODIFICACIÓN ---

            # La llamada a _load_people_list() ya la hicimos arriba
            # La llamada a _load_faces_to_grid() sigue comentada (¡correcto!)

    def _load_people_list(self):
        """
        (Próximamente) Carga la lista de nombres en el árbol/cajón derecho.
        """
        self.people_tree_widget.clear()
        # Aquí cargaremos de self.db.get_all_people()
        # Por ahora, un placeholder:
        unknown_item = QTreeWidgetItem(self.people_tree_widget, ["Caras Sin Asignar"])
        self.people_tree_widget.setCurrentItem(unknown_item)

    def _load_faces_to_grid(self):
        """
        Carga las caras "Sin Asignar" desde la BD y las muestra en la cuadrícula.
        """
        self.face_loading_label = None
        # 1. Limpiar la cuadrícula actual
        while self.unknown_faces_layout.count() > 0:
            item = self.unknown_faces_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        # 2. Cargar las caras de la BD
        unknown_faces = self.db.get_unknown_faces()

        if not unknown_faces:
            placeholder_label = QLabel("No se han encontrado caras nuevas sin asignar.")
            placeholder_label.setAlignment(Qt.AlignCenter)
            self.unknown_faces_layout.addWidget(placeholder_label, 0, 0)
            return

        # 3. Calcular el ancho para la cuadrícula responsive
        #    Restamos 30px para dar margen al borde y la barra de scroll.
        viewport_width = self.face_scroll_area.viewport().width() - 30

        #    (Ancho del widget 100px + 10px de espacio entre ellos)
        widget_width = 100 + 10

        # 4. Calcular cuántas columnas caben (asegurando un mínimo de 1)
        num_cols = max(1, viewport_width // widget_width)

        # 5. Iterar y mostrar las caras
        for i, face_row in enumerate(unknown_faces):
            try:
                face_id = face_row['id']
                photo_path = face_row['filepath']
                location_str = face_row['location']

                # Convertir el string "(top, right, bottom, left)" a tupla
                location = ast.literal_eval(location_str)
                (top, right, bottom, left) = location

                # Recortar la cara desde la imagen original usando PIL
                img = Image.open(photo_path)
                face_image_pil = img.crop((left, top, right, bottom))

                # Convertir la imagen PIL a QPixmap (en memoria, sin guardar)
                pixmap = QPixmap()
                buffer = QBuffer()
                buffer.open(QIODevice.OpenModeFlag.ReadWrite)
                # Guardamos como PNG para mantener la calidad
                face_image_pil.save(buffer, "PNG")
                pixmap.loadFromData(buffer.data())
                buffer.close()

                if pixmap.isNull():
                    raise Exception("QPixmap nulo después de la conversión.")

                # Crear el widget circular
                face_widget = CircularFaceLabel(pixmap)
                face_widget.setProperty("face_id", face_id)
                face_widget.setProperty("photo_path", photo_path)

                # Conectar el clic (para el próximo paso)
                face_widget.clicked.connect(self._on_face_clicked)

                # Añadir a la cuadrícula
                row, col = i // num_cols, i % num_cols
                self.unknown_faces_layout.addWidget(face_widget, row, col, Qt.AlignTop)

            except Exception as e:
                print(f"Error al cargar/recortar la cara ID {face_id} de {photo_path}: {e}")
                # Si falla, mostramos un placeholder de error
                error_label = QLabel(f"Error\nCara ID: {face_id}")
                error_label.setFixedSize(100, 100)
                error_label.setAlignment(Qt.AlignCenter)
                row, col = i // num_cols, i % num_cols
                self.unknown_faces_layout.addWidget(error_label, row, col, Qt.AlignTop)

        # Añadir un stretch al final para que todo se alinee arriba
        self.unknown_faces_layout.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding), len(unknown_faces) // num_cols + 1, 0)

    @Slot()
    def _on_face_clicked(self):
        """
        Se llama cuando el usuario hace clic en una 'CircularFaceLabel'.
        """
        # Obtenemos el widget que emitió la señal
        sender_widget = self.sender()

        face_id = sender_widget.property("face_id")
        photo_path = sender_widget.property("photo_path")

        self._set_status(f"Clic en Cara ID: {face_id} (de la foto: {Path(photo_path).name})")

        # PRÓXIMO PASO:
        # Aquí es donde abriremos un diálogo para preguntar:
        # 1. ¿Quién es esta persona? (Seleccionar de una lista)
        # 2. O, crear una "Nueva Persona".
        print(f"Clic en Cara ID: {face_id}")

    @Slot(int)
    def _update_face_scan_percentage(self, percentage):
        """
        Actualiza el label de carga en la pestaña 'Personas' con el porcentaje.
        """
        # Solo actualiza si el label de carga todavía existe
        # (no se ha terminado y borrado por _load_faces_to_grid)
        if self.face_loading_label:
            self.face_loading_label.setText(f"Buscando caras de personas... {percentage}%")

def run_visagevault():
    """Función para iniciar la aplicación gráfica."""
    app = QApplication(sys.argv)
    window = VisageVaultApp()
    window.showMaximized()
    sys.exit(app.exec())

if __name__ == "__main__":
    run_visagevault()
