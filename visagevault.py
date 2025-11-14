# ==============================================================================
# PROYECTO: VisageVault - Gestor de Fotografías Inteligente
# VERSIÓN: 1.0 First Relaese!!!
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

import numpy as np
from sklearn.cluster import DBSCAN
import sklearn

from PySide6.QtWidgets import (
    QDialog, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QDialogButtonBox, QTreeWidget, QTreeWidgetItem,
    QComboBox, QMenu
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
    QPointF, QBuffer, QIODevice
)
from PySide6.QtGui import (
    QPixmap, QIcon, QCursor, QTransform, QPainter, QPaintEvent,
    QPainterPath, QKeyEvent
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
# SEÑALES Y WORKER PARA CARGAR Y RECORTAR CARAS
# =================================================================
class FaceLoaderSignals(QObject):
    """Contenedor de señales para el FaceLoader QRunnable."""
    face_loaded = Signal(int, QPixmap, str) # face_id, pixmap, photo_path
    face_load_failed = Signal(int) # face_id

class FaceLoader(QRunnable):
    """QRunnable para cargar y CORTAR una cara de forma asíncrona."""

    def __init__(self, signals: FaceLoaderSignals, face_id: int, photo_path: str, location_str: str):
        super().__init__()
        self.signals = signals
        self.face_id = face_id
        self.photo_path = photo_path
        self.location_str = location_str

    @Slot()
    def run(self):
        """Ejecuta la tarea de recorte en el hilo del pool."""
        try:
            # --- Lógica de recorte (la parte LENTA) ---
            location = ast.literal_eval(self.location_str)
            (top, right, bottom, left) = location
            img = Image.open(self.photo_path)
            face_image_pil = img.crop((left, top, right, bottom))

            pixmap = QPixmap()
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.ReadWrite)
            face_image_pil.save(buffer, "PNG")
            pixmap.loadFromData(buffer.data())
            buffer.close()
            # --- Fin de la lógica de recorte ---

            if pixmap.isNull():
                raise Exception("QPixmap nulo después de la conversión.")

            # Emitir el resultado
            self.signals.face_loaded.emit(self.face_id, pixmap, self.photo_path)

        except Exception as e:
            print(f"Error en FaceLoader (ID: {self.face_id}): {e}")
            self.signals.face_load_failed.emit(self.face_id)

# =================================================================
# SEÑALES Y WORKER PARA AGRUPAR CARAS (CLUSTERING)
# =================================================================
class ClusterSignals(QObject):
    """Contenedor de señales para el ClusterWorker QRunnable."""
    # Señal que emite los grupos encontrados
    # Formato: [[face_id_1, face_id_5], [face_id_2, face_id_10, face_id_12], ...]
    clusters_found = Signal(list)

    # Señal para actualizar la UI (ej: "Procesando... 0/150")
    clustering_progress = Signal(str)

    # Señal para cuando todo el proceso termina
    clustering_finished = Signal()

class ClusterWorker(QRunnable):
    """
    QRunnable que ejecuta el clustering DBSCAN en los encodings faciales
    en un hilo separado del pool.
    """
    def __init__(self, signals: ClusterSignals, db_manager: VisageVaultDB):
        super().__init__()
        self.signals = signals
        self.db = db_manager

    @Slot()
    def run(self):
        """Ejecuta la tarea de clustering en el hilo del pool."""
        try:
            self.signals.clustering_progress.emit("Cargando datos de caras...")

            # 1. Obtener todos los encodings de la BD
            face_data = self.db.get_unknown_face_encodings()

            if len(face_data) < 2:
                self.signals.clustering_progress.emit("No hay suficientes caras para comparar.")
                self.signals.clusters_found.emit([]) # Emitir lista vacía
                self.signals.clustering_finished.emit()
                return

            self.signals.clustering_progress.emit(f"Comparando {len(face_data)} caras...")

            # 2. Preparar los datos para DBSCAN
            # 'face_ids' se mantiene en el mismo orden que 'encodings'
            face_ids = [data[0] for data in face_data]
            encodings = np.array([data[1] for data in face_data])

            # 3. Ejecutar el clustering
            # eps=0.4 es una buena "tolerancia" para face_recognition.
            # min_samples=2 significa que se necesitan al menos 2 caras para formar un grupo.
            clt = DBSCAN(eps=0.4, min_samples=2, metric="euclidean")
            clt.fit(encodings)

            # 4. Procesar los resultados
            clusters = {} # Un diccionario para agrupar los IDs por etiqueta

            # clt.labels_ es una lista: [0, 1, 0, -1, 1, 2, -1, ...]
            # Mismo orden que 'face_ids'
            for face_id, label in zip(face_ids, clt.labels_):

                # Ignorar el "ruido" (etiqueta -1)
                if label == -1:
                    continue

                # Añadir el face_id al grupo correspondiente
                if label not in clusters:
                    clusters[label] = []
                clusters[label].append(face_id)

            # 5. Convertir el diccionario a la lista que queremos emitir
            # (Solo nos interesan los valores, no las etiquetas)
            final_clusters_list = list(clusters.values())

            self.signals.clustering_progress.emit(f"Se encontraron {len(final_clusters_list)} grupos.")
            self.signals.clusters_found.emit(final_clusters_list)

        except Exception as e:
            print(f"Error crítico en el ClusterWorker: {e}")
            self.signals.clustering_progress.emit(f"Error: {e}")

        finally:
            self.signals.clustering_finished.emit()

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

    def keyPressEvent(self, event: QKeyEvent):
        """Cierra la ventana si se presiona la tecla ESC."""
        if event.key() == Qt.Key_Escape:
            self.close_with_animation()
        else:
            super().keyPressEvent(event)

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
    clicked = Signal()
    rightClicked = Signal(QPoint)

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.setFixedSize(100, 100)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Cara detectada (Haz clic para etiquetar)")
        self.setAlignment(Qt.AlignCenter) # Centrar el texto "..."

        self._pixmap = QPixmap() # Empezar vacío
        if pixmap and not pixmap.isNull():
            self.setPixmap(pixmap) # Establecer la imagen inicial si se proporciona

    def setPixmap(self, pixmap: QPixmap):
        """Establece el pixmap y lo escala para rellenar el círculo."""
        if pixmap.isNull():
            self._pixmap = QPixmap()
        else:
            self._pixmap = pixmap.scaled(100, 100, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.update() # Forzar repintado

    def paintEvent(self, event: QPaintEvent):
        """Pinta la imagen de forma circular."""
        if self._pixmap.isNull():
            # Si el pixmap está vacío, deja que QLabel dibuje el texto ("...")
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
        """Emite la señal 'clicked' al hacer clic izquierdo y 'rightClicked' con el derecho."""
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        elif event.button() == Qt.RightButton:
            self.rightClicked.emit(event.globalPos())
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
# CLASE: DIÁLOGO DE ETIQUETADO DE GRUPOS (CLUSTERS)
# =================================================================
class FaceClusterDialog(QDialog):
    """
    Un QDialog que muestra un grupo de caras (IDs) y permite asignarlas
    a una persona (nueva o existente).
    """
    SkipRole = QDialog.Accepted + 1
    DeleteRole = QDialog.Accepted + 2

    def __init__(self, db: VisageVaultDB, threadpool: QThreadPool,
                 face_ids: list, parent=None):

        super().__init__(parent)
        self.db = db
        self.threadpool = threadpool
        self.face_ids = face_ids # <-- Ahora 'face_ids' es la lista

        # NO aceptamos 'face_loader_signals', creamos las nuestras
        self.local_face_signals = FaceLoaderSignals()

        # Conectamos la señal a un *nuevo slot* local
        self.local_face_signals.face_loaded.connect(self._on_dialog_face_loaded)

        # Esta línea AHORA funcionará
        self.setWindowTitle(f"Agrupar {len(self.face_ids)} Caras")
        self.setMinimumSize(600, 400)
        self.person_id_to_save = None

        self._setup_ui()
        self._load_people_combo()
        self._load_faces_async()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)

        # 1. ScrollArea para las caras
        face_scroll_area = QScrollArea()
        face_scroll_area.setWidgetResizable(True)

        face_widget = QWidget()
        self.face_grid_layout = QGridLayout(face_widget)
        self.face_grid_layout.setSpacing(10)

        face_scroll_area.setWidget(face_widget)
        main_layout.addWidget(face_scroll_area, 1) # Darle stretch

        # 2. GroupBox para asignar persona
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

        # 3. Botones
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        # Añadimos el botón "Siguiente" manualmente
        self.skip_button = self.button_box.addButton("Siguiente", QDialogButtonBox.ButtonRole.ActionRole)
        self.skip_button.clicked.connect(self._skip) # Conectar al nuevo slot

        # Añadimos el botón de eliminar
        self.delete_button = self.button_box.addButton("Eliminar caras", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.delete_button.clicked.connect(self._delete_and_reject)


        self.button_box.accepted.connect(self._save_and_accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

    def _load_people_combo(self):
        """Carga la lista de personas conocidas en el ComboBox."""
        self.people_combo.addItem("--- Seleccionar ---", -1) # item -1: sin selección

        people = self.db.get_all_people() # Asume que esto devuelve (id, name)
        for person_row in people:
            person_id = person_row['id']
            person_name = person_row['name']
            self.people_combo.addItem(person_name, person_id)

    def _load_faces_async(self):
        """
        Pone placeholders y lanza FaceLoaders al threadpool para
        cargar las caras de este cluster.
        """
        # (Usamos self.face_loader_signals, que es la señal *global*
        # de la app principal)

        num_cols = max(1, (self.width() - 50) // 110)

        for i, face_id in enumerate(self.face_ids):
            # 1. Crear un placeholder
            face_widget = CircularFaceLabel(QPixmap()) # Vacío
            face_widget.setText("...")
            face_widget.setProperty("face_id", face_id)
            face_widget.clicked.connect(self._show_face_preview)

            # 2. Añadir placeholder al grid
            row, col = i // num_cols, i % num_cols
            self.face_grid_layout.addWidget(face_widget, row, col, Qt.AlignTop)

            # 3. Pedir al FaceLoader que cargue esta cara
            # (El FaceLoader necesita info de la BD que no tenemos aquí...
            # ... ¡Ah! El FaceLoader necesita (face_id, photo_path, location_str)
            # ... y solo tenemos face_id. Necesitamos modificar la BD.)

            # --- CORRECCIÓN DE LÓGICA RÁPIDA ---
            # Vamos a pedirle a la BD la info que falta
            face_info = self.db.get_face_info(face_id) # NECESITAREMOS CREAR ESTA FUNCIÓN
            if face_info:
                # Pasa las señales locales, no las globales
                loader = FaceLoader(
                    self.local_face_signals,
                    face_id,
                    face_info['filepath'],
                    face_info['location']
                )
                self.threadpool.start(loader)

    @Slot()
    def _on_combo_changed(self):
        """Si se selecciona una persona, borra el texto de 'nueva persona'."""
        if self.people_combo.currentIndex() > 0:
            self.new_person_edit.clear()

    @Slot()
    def _on_text_changed(self, text):
        """Si se escribe un nombre nuevo, resetea el combo."""
        if text:
            self.people_combo.setCurrentIndex(0) # Volver a "--- Seleccionar ---"

    @Slot()
    def _save_and_accept(self):
        """Valida, guarda la persona/etiquetas y cierra."""
        try:
            new_name = self.new_person_edit.text().strip()
            selected_id = self.people_combo.currentData()

            if new_name:
                # Usuario creó una persona nueva
                person_id = self.db.add_person(new_name)
                if person_id == -1:
                    # El nombre probablemente ya existía
                    existing = self.db.get_person_by_name(new_name)
                    person_id = existing['id']
                self.person_id_to_save = person_id

            elif selected_id != -1:
                # Usuario seleccionó una persona existente
                self.person_id_to_save = selected_id

            else:
                # No se seleccionó nada
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Acción Requerida",
                                    "Por favor, selecciona una persona existente o escribe un nombre nuevo.")
                return

            # --- Guardado en la BD ---
            if self.person_id_to_save:
                for face_id in self.face_ids:
                    # --- INICIO DE LA MODIFICACIÓN ---
                    # 1. Restaurar la cara (set is_deleted = 0)
                    self.db.restore_face(face_id)
                    # 2. Enlazar la cara a la persona
                    self.db.link_face_to_person(face_id, self.person_id_to_save)
                    # --- FIN DE LA MODIFICACIÓN ---

                self.accept() # Cierra el diálogo con éxito

        except Exception as e:
            print(f"Error al guardar el cluster: {e}")

    @Slot(int, QPixmap, str)
    def _on_dialog_face_loaded(self, face_id: int, pixmap: QPixmap, photo_path: str):
        """
        Recibe un pixmap CORTADO desde el QThreadPool y actualiza
        el placeholder *dentro* de este diálogo.
        """
        # Buscar el placeholder en la cuadrícula de *este* diálogo
        for i in range(self.face_grid_layout.count()):
            widget = self.face_grid_layout.itemAt(i).widget()

            # Comprobar si es un widget válido y tiene la propiedad
            if widget and hasattr(widget, 'property') and widget.property("face_id") == face_id:
                widget.setPixmap(pixmap)
                widget.setText("") # Borrar el "..."
                widget.setProperty("photo_path", photo_path)
                break

    @Slot()
    def _show_face_preview(self):
        """
        Se llama cuando se hace clic en una cara del diálogo de cluster.
        Abre la vista previa de la imagen completa.
        """
        sender_widget = self.sender()
        if not sender_widget:
            return

        # Obtenemos la ruta de la foto que guardamos en la propiedad
        photo_path = sender_widget.property("photo_path")

        if not photo_path:
            # Esto pasa si la cara aún está cargando ("...") y no tiene la ruta
            print("Por favor, espera a que la cara termine de cargar.")
            return

        # Cargar la imagen completa
        full_pixmap = QPixmap(photo_path)
        if full_pixmap.isNull():
            print(f"Error: No se pudo cargar la imagen completa de {photo_path}")
            return

        # Crear y mostrar el diálogo de vista previa
        preview_dialog = ImagePreviewDialog(full_pixmap, self)

        # ¡Importante! Lo hacemos "Modal" para que bloquee este diálogo
        # y no puedas hacer clic en "Guardar" mientras ves la foto.
        preview_dialog.setModal(True)
        preview_dialog.show_with_animation()

    @Slot()
    def _skip(self):
        """Cierra el diálogo con el código 'SkipRole'."""
        # Usamos .done() para cerrar el diálogo y devolver nuestro código (2)
        self.done(self.SkipRole)

    @Slot()
    def _delete_and_reject(self):
        """Marca todas las caras del diálogo como eliminadas y cierra."""
        # --- INICIO DE LA CORRECCIÓN ---
        # Usamos soft_delete_face en lugar de bulk_soft_delete_faces
        # para asegurar que la cara aparezca en la vista "Eliminadas".
        if self.face_ids:
            for face_id in self.face_ids:
                self.db.soft_delete_face(face_id)
        # --- FIN DE LA CORRECCIÓN ---
        self.done(self.DeleteRole)

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
        self.is_running = True

    @Slot()
    def run(self):
        # Definir fuera del 'try' para que 'finally' pueda acceder a ella
        photos_by_year_month = {}

        try:
            self.progress.emit("Cargando fechas conocidas desde la BD...")
            db_dates = self.db.load_all_photo_dates()

            self.progress.emit("Escaneando archivos en el directorio...")
            # 1. Llama a find_photos UNA SOLA VEZ
            photo_paths_on_disk = find_photos(self.directory_path)

            # 2. Crea el set a partir de la lista (rápido, en memoria)
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
                self.db.bulk_delete_photos(paths_to_delete)

            if photos_to_upsert_in_db:
                self.progress.emit(f"Guardando {len(photos_to_upsert_in_db)} fotos nuevas en la BD...")
                self.db.bulk_upsert_photos(photos_to_upsert_in_db)

            self.progress.emit(f"Escaneo finalizado. Encontradas {len(photo_paths_on_disk)} fotos.")

        except Exception as e:
            print(f"Error crítico en el hilo PhotoFinderWorker: {e}")
            self.progress.emit(f"Error en escaneo de fotos: {e}")
            # photos_by_year_month se quedará vacío o parcialmente lleno

        finally:
            # ¡MUY IMPORTANTE! Emitir 'finished' siempre,
            # para que el hilo se limpie y la UI se desbloquee.
            self.finished.emit(photos_by_year_month)

# =================================================================
# CLASE TRABAJADORA DEL ESCANEO DE CARAS (QThread)
# =================================================================
class FaceScanSignals(QObject):
    """Señales para el trabajador de escaneo de caras."""
    scan_progress = Signal(str)
    scan_percentage = Signal(int)
    face_found = Signal(int, str, str) # face_id, photo_path, location_str
    scan_finished = Signal() # Se emite cuando todo el lote ha terminado

class FaceScanWorker(QObject):
    """
    Escanea fotos no procesadas en un hilo separado para encontrar caras.
    """
    def __init__(self, db_manager: VisageVaultDB):
        super().__init__()
        self.db = db_manager
        self.signals = FaceScanSignals()
        self.is_running = True

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
                if not self.is_running:
                    break
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

                        face_id = self.db.add_face(photo_id, encoding_blob, location_str)
                        # Emitir la cara que acabamos de encontrar
                        self.signals.face_found.emit(face_id, photo_path, location_str)

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
        self.current_face_count = 0
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(os.cpu_count() or 4)
        self.thumb_signals = ThumbnailLoaderSignals()
        self.thumb_signals.thumbnail_loaded.connect(self._update_thumbnail)
        self.thumb_signals.load_failed.connect(self._handle_thumbnail_failed)
        self.face_loader_signals = FaceLoaderSignals()
        self.face_loader_signals.face_loaded.connect(self._handle_face_loaded)
        self.face_loader_signals.face_load_failed.connect(self._handle_face_load_failed)
        self.cluster_queue = [] # Cola para procesar clusters uno por uno
        self.cluster_signals = ClusterSignals()
        self.cluster_signals.clusters_found.connect(self._handle_clusters_found)
        self.cluster_signals.clustering_progress.connect(self._set_status)
        self.cluster_signals.clustering_finished.connect(self._handle_clustering_finished)

        # --- LÍNEA RESTAURADA ---
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(200) # 200ms de espera
        self.resize_timer.timeout.connect(self._handle_resize_timeout)
        # --- FIN DE LA RESTAURACIÓN ---

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
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._load_main_visible_thumbnails)
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

        # 5b. Panel Izquierdo (Contenedor "Stack")
        #    Usamos un QStackedWidget para intercambiar las vistas de
        #    "Caras Sin Asignar" y "Fotos de Persona".
        self.left_people_stack = QStackedWidget()

        # --- Pagina 0: Cuadrícula de Caras ---
        face_area_widget = QWidget()
        self.face_container_layout = QVBoxLayout(face_area_widget)

        self.unknown_faces_group = QGroupBox("Caras Sin Asignar")
        self.unknown_faces_layout = QGridLayout(self.unknown_faces_group)
        self.unknown_faces_layout.setSpacing(10)
        self.face_container_layout.addWidget(self.unknown_faces_group)

        self.face_container_layout.addStretch(1) # Empuja todo hacia arriba

        self.face_scroll_area = QScrollArea()
        self.face_scroll_area.setWidgetResizable(True)
        self.face_scroll_area.setWidget(face_area_widget)

        # Añadir al stack en el índice 0
        self.left_people_stack.addWidget(self.face_scroll_area)

        # --- Pagina 1: Cuadrícula de Fotos de Persona ---
        self.person_photo_scroll_area = QScrollArea()
        self.person_photo_scroll_area.setWidgetResizable(True)

        person_photo_widget = QWidget()
        self.person_photo_layout = QVBoxLayout(person_photo_widget)
        self.person_photo_scroll_area.setWidget(person_photo_widget)

        self.person_photo_scroll_area.verticalScrollBar().valueChanged.connect(self._load_person_visible_thumbnails)

        # Añadir al stack en el índice 1
        self.left_people_stack.addWidget(self.person_photo_scroll_area)

        # --- Fin de las Páginas del Stack ---

        # Añadimos el STACK (índice 0) al splitter
        self.people_splitter.addWidget(self.left_people_stack)

        # 5c. Panel Derecho (El "Cajón" de Nombres de Personas)
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

        # Botón "Añadir Persona" eliminado

        # Añadimos el CAJÓN (índice 1) al splitter
        self.people_splitter.addWidget(people_panel_widget)

        # 5d. Añadir el splitter de personas al layout de la pestaña
        personas_layout.addWidget(self.people_splitter)

        # 5e. Ajustar tamaños del splitter (AHORA SOLO TIENE 2 WIDGETS)
        default_width = self.width()
        min_right_width = 180

        left_width = default_width - min_right_width
        if left_width < 100: left_width = 100

        # [0] self.left_people_stack
        # [1] people_panel_widget (el "cajón")
        self.people_splitter.setSizes([left_width, min_right_width])

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
        #self.thread.finished.connect(self.thread.deleteLater)
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
        self.face_scan_worker.signals.face_found.connect(self._handle_face_found)
        self.face_scan_worker.signals.scan_finished.connect(self._handle_scan_finished)

        # Conectar control del hilo
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
        QTimer.singleShot(100, self._load_main_visible_thumbnails)

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
            QTimer.singleShot(200, self._load_main_visible_thumbnails)

    @Slot(dict)
    def _handle_search_finished(self, photos_by_year_month):
        self.photos_by_year_month = photos_by_year_month
        self.select_dir_button.setEnabled(True)
        num_fotos = sum(len(photos) for months in photos_by_year_month.values() for photos in months.values())
        self._set_status(f"Escaneo finalizado. {num_fotos} fotos encontradas.")
        self._display_photos()

    def _set_status(self, message):
        self.status_label.setText(f"Estado: {message}")

    def _load_main_visible_thumbnails(self):
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

    @Slot()
    def _load_person_visible_thumbnails(self):
        """
        Carga las miniaturas visibles en el QScrollArea de la
        pestaña "PERSONAS".
        """
        viewport = self.person_photo_scroll_area.viewport()
        preload_rect = viewport.rect().adjusted(0, -PRELOAD_MARGIN_PX, 0, PRELOAD_MARGIN_PX)

        # Buscar labels dentro del widget contenedor (person_photo_layout)
        person_photo_widget = self.person_photo_scroll_area.widget()
        if not person_photo_widget:
            return

        # Buscar todos los ZoomableClickableLabel que son miniaturas
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
    def _update_thumbnail(self, original_path: str, pixmap: QPixmap):
        # Helper function to find and update ALL matching labels in a given container
        def update_in_container(container_widget):
            if not container_widget:
                return

            # Using ZoomableClickableLabel is more specific
            for label in container_widget.findChildren(ZoomableClickableLabel):
                # Update if path matches and it's not already loaded
                if label.property("original_path") == original_path and label.property("loaded") is not True:
                    label.setPixmap(pixmap.scaled(THUMBNAIL_SIZE[0], THUMBNAIL_SIZE[1], Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    label.setText("")
                    label.setProperty("loaded", True)
                    # Don't return, in case the same photo appears multiple times

        # Update all matching labels in the "Fotos" tab
        update_in_container(self.scroll_area.widget())
        # Update all matching labels in the "Personas" tab
        update_in_container(self.person_photo_scroll_area.widget())

    @Slot(str)
    def _handle_thumbnail_failed(self, original_path: str):
        """Maneja el caso en que la miniatura no se pudo cargar."""
        # Helper function to find and update ALL matching labels in a given container
        def fail_in_container(container_widget):
            if not container_widget:
                return
            for label in container_widget.findChildren(ZoomableClickableLabel):
                if label.property("original_path") == original_path and label.property("loaded") is not True:
                    label.setText("Error al cargar.")
                    label.setProperty("loaded", True) # Mark as "done" to avoid retrying

        # Update all matching labels in the "Fotos" tab
        fail_in_container(self.scroll_area.widget())
        # Update all matching labels in the "Personas" tab
        fail_in_container(self.person_photo_scroll_area.widget())

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
        tab_name = self.tab_widget.tabText(index)

        if tab_name == "Personas":
            self._set_status("Cargando vista de personas...")
            self._load_people_list()

            # Si ya hay un escaneo, nos vamos. La UI ya está en modo "streaming".
            if self.face_scan_thread and self.face_scan_thread.isRunning():
                self._set_status("Escaneo de caras en curso...")
                return

            # --- Si no hay escaneo, preparamos la UI ---

            # 1. Limpiar la cuadrícula y resetear el contador
            while self.unknown_faces_layout.count() > 0:
                item = self.unknown_faces_layout.takeAt(0)
                if item.widget(): item.widget().deleteLater()
            self.current_face_count = 0
            if self.face_loading_label:
                self.face_loading_label.deleteLater()
                self.face_loading_label = None

            # --- LÍNEA MODIFICADA ---
            # 2. Cargar las caras existentes de forma ASÍNCRONA
            self._load_existing_faces_async()
            # --- FIN DE MODIFICACIÓN ---

            # 3. Iniciar un *nuevo* escaneo (que streameará nuevas caras)
            self._start_face_scan()

    def _load_people_list(self):
        """
        Carga la lista de personas desde la BD y las muestra
        en el árbol de navegación de personas.
        """
        self.people_tree_widget.clear()

        # 1. Añadir el item raíz "Caras Sin Asignar"
        # Guardamos un 'id' especial (-1) para saber qué es
        unknown_item = QTreeWidgetItem(self.people_tree_widget, ["Caras Sin Asignar"])
        unknown_item.setData(0, Qt.UserRole, -1) # -1 significa "sin asignar"

        # Item para caras eliminadas
        deleted_item = QTreeWidgetItem(self.people_tree_widget, ["Caras Eliminadas"])
        deleted_item.setData(0, Qt.UserRole, -2) # -2 significa "eliminadas"


        # 2. Cargar las personas de la BD
        people = self.db.get_all_people() #

        if people:
            # 3. Crear un item "padre" para agruparlas
            people_root_item = QTreeWidgetItem(self.people_tree_widget, ["Personas"])

            # 4. Añadir cada persona como "hijo"
            for person_row in people:
                person_id = person_row['id']
                person_name = person_row['name']

                person_item = QTreeWidgetItem(people_root_item, [person_name])
                # Guardamos el ID de la BD dentro del item
                person_item.setData(0, Qt.UserRole, person_id)

            people_root_item.setExpanded(True) # Expandir la lista de "Personas"

        # Seleccionar "Caras Sin Asignar" por defecto
        self.people_tree_widget.setCurrentItem(unknown_item)

    def _populate_face_grid_async(self, face_list: list, is_deleted_view: bool = False):
        """
        (Función Helper) Limpia el grid y lo puebla asíncronamente
        con la lista de caras (rows) proporcionada.
        """
        # 1. Limpiar la cuadrícula y resetear el contador
        while self.unknown_faces_layout.count() > 0:
            item = self.unknown_faces_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.current_face_count = 0

        if not face_list:
            # Si la lista está vacía, mostrar un placeholder
            placeholder = QLabel("No se han encontrado caras.")
            placeholder.setAlignment(Qt.AlignCenter)
            self.unknown_faces_layout.addWidget(placeholder, 0, 0, Qt.AlignCenter)
            return

        self.current_face_count = len(face_list)

        # 2. Calcular el grid
        # Obtenemos el ancho del panel 0 del splitter (que es 'face_scroll_area')
        viewport_width = self.left_people_stack.width() - 30
        num_cols = max(1, viewport_width // 110)

        # 3. Volver a poblar la cuadrícula solo con los placeholders
        for i, face_row in enumerate(face_list):
            face_id = face_row['id']

            # Crear un *placeholder*
            face_widget = CircularFaceLabel(QPixmap()) # Pixmap vacío
            face_widget.setText("...") # Pone "..."
            face_widget.setProperty("face_id", face_id)
            face_widget.setProperty("is_deleted_view", is_deleted_view)
            face_widget.rightClicked.connect(self._on_face_right_clicked)
            face_widget.clicked.connect(self._on_face_clicked)


            # Añadir placeholder al grid
            row, col = i // num_cols, i % num_cols
            self.unknown_faces_layout.addWidget(face_widget, row, col, Qt.AlignTop)

            # Iniciar el worker para este placeholder
            loader = FaceLoader(
                self.face_loader_signals,
                face_id,
                face_row['filepath'],
                face_row['location']
            )
            self.threadpool.start(loader)

    def _load_existing_faces_async(self):
        """
        Carga las caras SIN ASIGNAR.
        (Ahora solo es un contenedor para el helper)
        """
        # 1. Cambiar el título del GroupBox
        self.unknown_faces_group.setTitle("Caras Sin Asignar")

        # 2. Activar el botón de duplicados
        self.cluster_faces_button.setEnabled(True)
        self.show_deleted_faces_button.setEnabled(True)


        # 3. Obtener datos y llamar al helper
        unknown_faces = self.db.get_unknown_faces() #
        self._populate_face_grid_async(unknown_faces, is_deleted_view=False)

    @Slot()
    def _on_face_clicked(self):
        """
        Se llama cuando el usuario hace clic en una 'CircularFaceLabel'
        en la cuadrícula principal de "Caras Sin Asignar".
        """
        sender_widget = self.sender()
        if not sender_widget:
            return

        # --- INICIO DE LA MODIFICACIÓN ---
        # Guardamos el estado (si estaba eliminada) ANTES de abrir el diálogo
        is_deleted_view = sender_widget.property("is_deleted_view")
        # --- FIN DE LA MODIFICACIÓN ---

        face_id = sender_widget.property("face_id")
        photo_path = sender_widget.property("photo_path")

        if not face_id or not photo_path:
            # Esto puede pasar si la cara aún está cargando ("...")
            print("Clic en una cara que aún no tiene datos (cargando).")
            return

        self._set_status(f"Etiquetando Cara ID: {face_id}...")

        # 1. Reutilizamos el diálogo de "Agrupar Caras", pero
        #    pasándole una lista con UN SOLO face_id.
        dialog = FaceClusterDialog(
            self.db,
            self.threadpool,
            [face_id],  # Pasamos la cara como una lista de un solo ítem
            self
        )

        result = dialog.exec()

        # --- INICIO DE LA MODIFICACIÓN ---
        # Refrescar la vista correcta basándose en el estado anterior
        if result == QDialog.Accepted:
            self._set_status("Cara etiquetada. Refrescando...")
            self._load_people_list()

            # Si estábamos en "Eliminadas", refrescamos esa vista
            if is_deleted_view:
                self._show_deleted_faces()
            else:
                self._load_existing_faces_async()

        elif result == FaceClusterDialog.DeleteRole:
            self._set_status("Cara eliminada. Refrescando...")

            # Si estábamos en "Eliminadas", refrescamos esa vista
            if is_deleted_view:
                self._show_deleted_faces()
            else:
                self._load_existing_faces_async()

        else: # Incluye Cancel y Skip
            self._set_status("Etiquetado cancelado.")
        # --- FIN DE LA MODIFICACIÓN ---

    @Slot(QPoint)
    def _on_face_right_clicked(self, pos):
        """Muestra un menú contextual al hacer clic derecho en una cara."""
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
        """Marca una cara como eliminada y la quita de la UI."""
        self.db.soft_delete_face(face_id)
        widget.deleteLater()
        self._set_status(f"Cara ID {face_id} eliminada.")
        self._load_existing_faces_async()

    def _restore_face(self, face_id: int, widget: QWidget):
        """Restaura una cara y la quita de la vista de eliminados."""
        self.db.restore_face(face_id)
        widget.deleteLater()
        self._set_status(f"Cara ID {face_id} restaurada.")
        self._show_deleted_faces()

    @Slot()
    def _show_deleted_faces(self):
        """Carga y muestra las caras marcadas como eliminadas."""
        self.left_people_stack.setCurrentIndex(0)
        self.unknown_faces_group.setTitle("Caras Eliminadas")
        self.cluster_faces_button.setEnabled(False)
        self.show_deleted_faces_button.setEnabled(False)


        deleted_faces = self.db.get_deleted_faces()
        self._populate_face_grid_async(deleted_faces, is_deleted_view=True)
        self._set_status(f"Mostrando {len(deleted_faces)} caras eliminadas.")

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _on_person_selected(self, current_item: QTreeWidgetItem, previous_item: QTreeWidgetItem):
        """
        Se llama cuando el usuario selecciona un item en el árbol de personas.
        """
        if not current_item:
            return

        person_id = current_item.data(0, Qt.UserRole)

        # --- Lógica para cambiar la vista ---

        # ID -1: Caras Sin Asignar
        if person_id == -1:
            self.left_people_stack.setCurrentIndex(0)
            self._load_existing_faces_async()

        # ID -2: Caras Eliminadas
        elif person_id == -2:
            self.left_people_stack.setCurrentIndex(0)
            self._show_deleted_faces()

        # ID >= 0: Una persona real
        elif person_id >= 0:
            self.left_people_stack.setCurrentIndex(1)
            person_name = current_item.text(0)
            self._load_photos_for_person(person_id, person_name)

    @Slot(int)
    def _update_face_scan_percentage(self, percentage):
        """
        Actualiza el label de carga. Si no existe, lo crea
        DEBAJO del group box de caras.
        """
        if not self.face_loading_label:
            # Si el label no existe, lo creamos
            self.face_loading_label = QLabel(f"Buscando caras de personas... {percentage}%")
            self.face_loading_label.setAlignment(Qt.AlignCenter)
            self.face_loading_label.setStyleSheet("font-size: 14pt;")

            # --- MODIFICACIÓN CLAVE ---
            # Lo añadimos al layout VERTICAL (face_container_layout),
            # no al grid (unknown_faces_layout).
            # Lo insertamos en la posición 1 (después del GroupBox [0]
            # y antes del stretch [2]).
            self.face_container_layout.insertWidget(1, self.face_loading_label, 0, Qt.AlignCenter)
            # --- FIN DE MODIFICACIÓN ---
        else:
            # Si ya existe, solo actualizamos el texto
            self.face_loading_label.setText(f"Buscando caras de personas... {percentage}%")

    @Slot(int, str, str)
    def _handle_face_found(self, face_id: int, photo_path: str, location_str: str):
        """
        Recibe una *NUEVA* cara del worker (FaceScanWorker),
        y lanza un task al QThreadPool para cortarla y añadirla.
        NO bloquea la UI.
        """

        # Iniciar el worker para esta *nueva* cara
        # Usamos el *mismo* FaceLoader que para las caras existentes
        loader = FaceLoader(
            self.face_loader_signals,
            face_id,
            photo_path,
            location_str
        )
        self.threadpool.start(loader)

        # NO incrementamos self.current_face_count aquí.
        # Lo incrementamos en el slot que recibe el pixmap final.

    @Slot()
    def _handle_scan_finished(self):
        """
        Limpia el label de "Loading..." cuando el escaneo termina.
        """
        if self.face_loading_label:
            # Si el escaneo terminó (100%) y no encontró nada,
            # el label "Loading 100%" sigue ahí. Lo borramos.
            self.face_loading_label.deleteLater()
            self.face_loading_label = None

        # Si no había caras y no se encontró ninguna, ponemos el mensaje
        if self.current_face_count == 0:
            placeholder = QLabel("No se han encontrado caras.")
            placeholder.setAlignment(Qt.AlignCenter)
            self.unknown_faces_layout.addWidget(placeholder, 0, 0, Qt.AlignCenter)

    @Slot()
    def _on_scan_thread_finished(self):
        """
        Slot de limpieza que se llama cuando el QThread ha terminado.
        Resetea las variables de Python.
        """
        # Primero, nos aseguramos de que el hilo (que ya ha terminado)
        # se elimine de forma segura.
        if self.thread:
            self.thread.deleteLater()
        self.thread = None
        self.worker = None

    @Slot()
    def _on_face_scan_thread_finished(self):
        """
        Slot de limpieza que se llama cuando el QThread de CARAS ha terminado.
        Resetea las variables de Python.
        """
        self.face_scan_thread = None
        self.face_scan_worker = None

    @Slot(int, QPixmap, str)
    def _handle_face_loaded(self, face_id: int, pixmap: QPixmap, photo_path: str):
        """
        Recibe un pixmap CORTADO desde el QThreadPool (FaceLoader).
        Puede ser una cara 'existente' o una 'nueva'.
        Esta función SÍ se ejecuta en el hilo principal y es segura.
        """
        # Buscar si hay un placeholder para esta cara
        placeholder = None
        for i in range(self.unknown_faces_layout.count()):
            widget = self.unknown_faces_layout.itemAt(i).widget()
            if widget and widget.property("face_id") == face_id:
                placeholder = widget
                break

        if placeholder:
            # Es una cara 'existente', actualizamos el placeholder
            placeholder.setPixmap(pixmap)
            placeholder.setText("") # Borrar el "..."
            placeholder.setProperty("photo_path", photo_path)
            #placeholder.clicked.connect(self._on_face_clicked) # La conexión ya se hizo en _populate_face_grid_async
        else:
            # Es una cara 'nueva' (del FaceScanWorker), la añadimos al final

            # Comprobar si estamos en la vista de "Sin Asignar"
            # (No queremos añadir una cara nueva si el usuario está viendo "Eliminadas")
            if self.unknown_faces_group.title() != "Caras Sin Asignar":
                return # Estamos en otra vista (ej: Eliminadas), no añadirla visualmente

            face_widget = CircularFaceLabel(pixmap)
            face_widget.setProperty("face_id", face_id)
            face_widget.setProperty("photo_path", photo_path)
            face_widget.setProperty("is_deleted_view", False)
            face_widget.clicked.connect(self._on_face_clicked)
            face_widget.rightClicked.connect(self._on_face_right_clicked)

            # Añadir al grid en la siguiente posición
            num_cols = max(1, (self.face_scroll_area.viewport().width() - 30) // 110)
            row = self.current_face_count // num_cols
            col = self.current_face_count % num_cols
            self.unknown_faces_layout.addWidget(face_widget, row, col, Qt.AlignTop)

            # Incrementar el contador global
            self.current_face_count += 1

    @Slot(int)
    def _handle_face_load_failed(self, face_id: int):
        """Maneja el fallo de carga de una cara."""
        placeholder = None
        for i in range(self.unknown_faces_layout.count()):
            widget = self.unknown_faces_layout.itemAt(i).widget()
            if widget and widget.property("face_id") == face_id:
                placeholder = widget
                break
        if placeholder:
            placeholder.setText("Error")

    def closeEvent(self, event):
        """
        Se ejecuta al cerrar la ventana principal (ej: clic en 'X').
        Limpia de forma segura todos los hilos antes de salir.
        """
        print("Cerrando aplicación... Por favor, espere.")
        self._set_status("Cerrando... esperando a que terminen las tareas de fondo.")

        # 1. Detener el hilo de escaneo de fotos (si está activo)
        if self.thread and self.thread.isRunning():
            print("Deteniendo el hilo de escaneo de fotos...")
            # Desconectar señales para evitar que actualicen la UI mientras se cierra
            if self.worker:
                self.worker.is_running = False
                try: self.worker.finished.disconnect()
                except RuntimeError: pass # Ignora si ya estaba desconectado

            self.thread.quit() # Pide al hilo que termine
            self.thread.wait(3000)  # Espera hasta 3 segundos

        # 2. Detener el hilo de escaneo de caras (si está activo)
        if self.face_scan_thread and self.face_scan_thread.isRunning():
            print("Deteniendo el hilo de escaneo de caras...")
            if self.face_scan_worker:
                self.face_scan_worker.is_running = False
                try: self.face_scan_worker.signals.scan_finished.disconnect()
                except RuntimeError: pass # Ignora si ya estaba desconectado

            self.face_scan_thread.quit() # Pide al hilo que termine
            self.face_scan_thread.wait(3000) # Espera hasta 3 segundos

        # 3. Esperar a que el pool de QRunnables termine
        print("Esperando tareas del ThreadPool (miniaturas/caras)...")
        self.threadpool.clear() # Cancela tareas encoladas que no hayan empezado
        self.threadpool.waitForDone(3000)

        print("Todos los hilos finalizados. Saliendo.")
        event.accept()

    @Slot()
    def _start_clustering(self):
        """
        Se llama al pulsar el botón "Buscar Duplicados".
        Inicia el ClusterWorker en el QThreadPool.
        """
        # Desactivar botones para evitar clics múltiples
        self.cluster_faces_button.setText("Procesando...")
        self.cluster_faces_button.setEnabled(False)
        self._set_status("Iniciando búsqueda de duplicados...")

        # Crear e iniciar el worker
        worker = ClusterWorker(self.cluster_signals, self.db)
        self.threadpool.start(worker)

    @Slot(list)
    def _handle_clusters_found(self, clusters: list):
        """
        Recibe los grupos de face_ids desde el ClusterWorker.
        Los añade a la cola y empieza a procesarlos.
        """
        if not clusters:
            self._set_status("No se encontraron nuevos duplicados.")
            return

        self.cluster_queue = clusters
        self._set_status(f"¡Encontrados {len(self.cluster_queue)} grupos! Procesando...")

        # Iniciar el procesamiento del primer grupo de la cola
        self._process_cluster_queue()

    @Slot()
    def _handle_clustering_finished(self):
        """
        Se llama cuando el ClusterWorker ha terminado.
        Reactiva los botones de la UI.
        """
        self.cluster_faces_button.setText("Buscar Duplicados")
        self.cluster_faces_button.setEnabled(True)

        # Si la cola está vacía, significa que no se encontró nada
        if not self.cluster_queue:
             self._set_status("Búsqueda de duplicados finalizada. No se encontraron grupos.")

    @Slot()
    def _process_cluster_queue(self):
        """
        Procesa el siguiente grupo de caras en la cola.
        Muestra el FaceClusterDialog.
        """
        if not self.cluster_queue:
            self._set_status("¡Etiquetado de grupos completado!")
            # Ya que hemos etiquetado caras, refrescamos la cuadrícula
            self._load_existing_faces_async()
            return

        # Sacar el primer grupo de la cola
        next_cluster_ids = self.cluster_queue.pop(0)

        self._set_status(f"Procesando grupo... quedan {len(self.cluster_queue)} grupos.")

        # Crear y mostrar el diálogo
        dialog = FaceClusterDialog(
            self.db,
            self.threadpool,
            next_cluster_ids,
            self
        )

        result = dialog.exec()

        if result == QDialog.Accepted:
            # (GUARDAR)
            # El usuario guardó, refrescamos la lista de personas
            print(f"Grupo guardado. Quedan {len(self.cluster_queue)}.")
            self._load_people_list() # Recargar el árbol de personas

        elif result == FaceClusterDialog.SkipRole:
            # (SIGUIENTE)
            # El usuario omitió. No hacemos nada, solo continuamos.
            print(f"Grupo omitido. Quedan {len(self.cluster_queue)}.")

        elif result == FaceClusterDialog.DeleteRole:
            # (ELIMINAR GRUPO)
            print(f"Grupo eliminado. Quedan {len(self.cluster_queue)}.")
            # No es necesario refrescar el grid aquí, se refrescará al final

        else:
            # (CANCELAR o 'X')
            # El usuario canceló, vaciamos la cola para detener
            print("Cancelado el etiquetado de grupos.")
            self.cluster_queue = []
            self._set_status("Etiquetado cancelado.")
            # Refrescar la cuadrícula igualmente
            self._load_existing_faces_async()
            return # <-- DETENER la recursión/cola

        # Llamada recursiva para el siguiente grupo
        QTimer.singleShot(100, self._process_cluster_queue)

    def _load_photos_for_person(self, person_id: int, person_name: str):
        """
        Carga las fotos de una persona específica y las muestra.
        """
        self._set_status(f"Mostrando caras de {person_name}.")

        # Desactivar botones (no aplican aquí)
        self.cluster_faces_button.setEnabled(False)
        self.show_deleted_faces_button.setEnabled(True)


        # Obtener las fotos de la persona
        person_photos = self.db.get_faces_for_person(person_id)

        # Llamar al nuevo método para dibujar las fotos
        self._display_person_photos(person_photos, person_name)


    def _display_person_photos(self, photos_list: list, person_name: str):
        """
        Toma una lista de fotos (con 'filepath', 'year', 'month')
        y las dibuja agrupadas en 'self.person_photo_layout'.
        """
        # 1. Limpiar el contenedor
        while self.person_photo_layout.count() > 0:
            item = self.person_photo_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        if not photos_list:
            placeholder = QLabel(f"No se encontraron fotos para {person_name}.")
            placeholder.setAlignment(Qt.AlignCenter)
            self.person_photo_layout.addWidget(placeholder)
            return

        # 2. Procesar la lista y agruparla en un diccionario
        # (Esto es lo que hace PhotoFinderWorker internamente)
        photos_by_year_month = {}
        for row in photos_list:
            path, year, month = row['filepath'], row['year'], row['month']

            if year not in photos_by_year_month:
                photos_by_year_month[year] = {}
            if month not in photos_by_year_month[year]:
                photos_by_year_month[year][month] = []
            # Evitar duplicados de la *misma foto* en la vista
            if path not in photos_by_year_month[year][month]:
                photos_by_year_month[year][month].append(path)

        # 3. Calcular columnas (igual que en _display_photos)
        # Obtenemos el ancho del panel 1 del splitter (que es 'person_photo_scroll_area')
        viewport_width = self.left_people_stack.width() - 30
        thumb_width = THUMBNAIL_SIZE[0] + 10
        num_cols = max(1, viewport_width // thumb_width)

        # 4. Dibujar los grupos (lógica copiada de _display_photos)
        sorted_years = sorted(photos_by_year_month.keys(), reverse=True)

        for year in sorted_years:
            sorted_months = sorted(photos_by_year_month[year].keys(), reverse=True)

            for month in sorted_months:
                photos = photos_by_year_month[year][month]
                if not photos: continue

                # Añadir separador de Mes/Año
                try:
                    month_name = datetime.datetime.strptime(month, "%m").strftime("%B").capitalize()
                except ValueError:
                    month_name = "Mes Desconocido"

                group_label = QLabel(f"{month_name} {year}")
                group_label.setStyleSheet("font-size: 14pt; font-weight: bold; margin-top: 10px;")
                self.person_photo_layout.addWidget(group_label)

                # Añadir rejilla de fotos para el mes
                photo_grid_widget = QWidget()
                photo_grid_layout = QGridLayout(photo_grid_widget)
                photo_grid_layout.setSpacing(5)

                for i, photo_path in enumerate(photos):
                    photo_label = ZoomableClickableLabel(photo_path)
                    photo_label.is_thumbnail_view = True # Es una miniatura
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
        # 5. Cargar las miniaturas visibles
        QTimer.singleShot(100, self._load_person_visible_thumbnails)

def run_visagevault():
    """Función para iniciar la aplicación gráfica."""
    app = QApplication(sys.argv)
    window = VisageVaultApp()
    window.showMaximized()
    sys.exit(app.exec())

if __name__ == "__main__":
    run_visagevault()
