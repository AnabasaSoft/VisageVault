# redeye.py
"""
Corrección automática de ojos rojos.

- Los ojos se localizan con los puntos faciales de face_recognition (ya usado
  por la app). Antes se usaba un clasificador Haar de OpenCV sobre toda la
  imagen: daba falsos positivos (labios, ropa roja...) y OpenCV 5 lo eliminó.
- La imagen se lee con PIL aplicando la orientación EXIF, para detectar las
  caras derechas, y se guarda con Orientation=1 conservando el resto del EXIF
  (fecha, cámara, GPS...), el perfil de color y la calidad JPEG original.
- La escritura es atómica (temporal oculto + os.replace) y conserva las
  fechas del archivo.
"""
import os

import cv2
import numpy as np
import fr_compat  # noqa: F401  Antes de face_recognition (ver fr_compat.py)
import face_recognition
from PIL import Image, ImageOps, JpegImagePlugin

MAX_DETECTION_WIDTH = 1600   # Se detecta sobre una copia reducida (rapidez)
EXIF_ORIENTATION = 0x0112
EXIF_IFD = 0x8769
EXIF_PIXEL_X = 0xA002
EXIF_PIXEL_Y = 0xA003


def _eye_boxes(rgb):
    """Rectángulos (x0, y0, x1, y1) alrededor de cada ojo detectado."""
    height, width = rgb.shape[:2]
    scale = 1.0
    small = rgb
    if width > MAX_DETECTION_WIDTH:
        scale = MAX_DETECTION_WIDTH / width
        small = cv2.resize(rgb, (MAX_DETECTION_WIDTH, int(height * scale)), interpolation=cv2.INTER_AREA)

    boxes = []
    for face in face_recognition.face_landmarks(small):
        for eye in ("left_eye", "right_eye"):
            points = np.array(face.get(eye, []), dtype=np.float32)
            if len(points) == 0:
                continue
            points /= scale
            x0, y0 = points.min(axis=0)
            x1, y1 = points.max(axis=0)
            # Los puntos rodean el párpado: ampliamos para abarcar toda la pupila
            margin = max(x1 - x0, y1 - y0) * 0.3
            boxes.append((
                max(0, int(x0 - margin)), max(0, int(y0 - margin)),
                min(width, int(x1 + margin) + 1), min(height, int(y1 + margin) + 1),
            ))
    return boxes


def _fix_eye_region(rgb, box):
    """Sustituye el rojo de la pupila por la media de verde y azul. True si cambia algo."""
    x0, y0, x1, y1 = box
    roi = rgb[y0:y1, x0:x1].astype(np.int16)
    if roi.size == 0:
        return False
    r, g, b = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]

    mask = ((r > 150) & (r > g + b)).astype(np.uint8)
    if not mask.any():
        return False
    mask = cv2.dilate(mask, None, iterations=1).astype(bool)

    roi[:, :, 0][mask] = ((g + b) // 2)[mask]
    rgb[y0:y1, x0:x1] = roi.astype(np.uint8)
    return True


def _save_kwargs(original, corrected):
    """Parámetros de guardado que conservan metadatos y calidad del original."""
    kwargs = {}
    icc = original.info.get("icc_profile")
    if icc:
        kwargs["icc_profile"] = icc

    exif = original.getexif()
    if exif:
        exif[EXIF_ORIENTATION] = 1  # Los píxeles ya se guardan derechos
        exif_ifd = exif.get_ifd(EXIF_IFD)
        if EXIF_PIXEL_X in exif_ifd:
            exif_ifd[EXIF_PIXEL_X], exif_ifd[EXIF_PIXEL_Y] = corrected.size
        kwargs["exif"] = exif.tobytes()

    if original.format == "JPEG":
        # Mismas tablas de cuantización y submuestreo: mínima pérdida al recomprimir
        kwargs["qtables"] = original.quantization
        sampling = JpegImagePlugin.get_sampling(original)
        if sampling != -1:
            kwargs["subsampling"] = sampling
    return kwargs


def remove_red_eyes(image_path):
    """
    Corrige los ojos rojos de la imagen sobrescribiendo el archivo.
    Devuelve True si se ha modificado algo.
    """
    with Image.open(image_path) as original:
        original.load()
        if original.mode not in ("RGB", "RGBA"):
            return False  # Escala de grises, CMYK, paleta...

        upright = ImageOps.exif_transpose(original)
        alpha = upright.getchannel("A") if upright.mode == "RGBA" else None
        rgb = np.array(upright.convert("RGB"))

        changed = False
        for box in _eye_boxes(rgb):
            changed |= _fix_eye_region(rgb, box)
        if not changed:
            return False

        corrected = Image.fromarray(rgb)
        if alpha is not None:
            corrected.putalpha(alpha)
        kwargs = _save_kwargs(original, corrected)
        image_format = original.format

    stat = os.stat(image_path)
    folder, name = os.path.split(image_path)
    temp_path = os.path.join(folder, f".{name}.redeye-tmp")
    try:
        corrected.save(temp_path, format=image_format, **kwargs)
        os.replace(temp_path, image_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    # Conservar las fechas: la app las usa para clasificar las fotos
    os.utime(image_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    return True
