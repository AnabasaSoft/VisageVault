# metadata_reader.py
"""
Fecha (año, mes) de una foto o un vídeo al indexarlo. Es RÁPIDO: no se abre
el archivo ni se lee el EXIF.
Prioridad:
1. Patrón de fecha en el nombre del archivo (IMG-20250402-..., 2023-11-01_Foto.jpg...).
2. Fecha de modificación del archivo (sistema de archivos).
"""
import os
import re
from datetime import datetime

NO_DATE = ("Sin Fecha", "00")

def parse_date_from_filename(filepath):
    """
    Intenta extraer la fecha (Año, Mes) basándose exclusivamente en el nombre del archivo.
    Soporta: YYYYMMDD, DD-MM-YYYY, YYYY-MM-DD, DDMMYYYY e IMG-YYYYMMDD.
    Devuelve (None, None) si no encuentra ninguna.
    """
    filename = os.path.basename(filepath)

    # 1. Patrón YYYYMMDD (Ej: IMG-20250304-..., VID-20240411..., 20231005.jpg)
    # Busca 20xx seguido de mes (01-12) y día (01-31)
    match = re.search(r'(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])', filename)
    if match:
        return match.group(1), match.group(2) # Retorna (Año, Mes)

    # 2. Patrón DD-MM-YYYY o DD.MM.YYYY o DD_MM_YYYY (Ej: 07-10-2023.jpg)
    match = re.search(r'(0[1-9]|[12]\d|3[01])[-._](0[1-9]|1[0-2])[-._](20\d{2})', filename)
    if match:
        return match.group(3), match.group(2) # Retorna (Año, Mes)

    # 3. Patrón YYYY-MM-DD (Ej: 2023-11-01_Foto.jpg)
    match = re.search(r'(20\d{2})[-._](0[1-9]|1[0-2])[-._](0[1-9]|[12]\d|3[01])', filename)
    if match:
        return match.group(1), match.group(2)

    # 4. Patrón DDMMYYYY Compacto (Ej: IMG-04122021.jpg -> 04/12/2021)
    # Asume formato europeo DDMMYYYY si no hay separadores
    match = re.search(r'(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])(20\d{2})', filename)
    if match:
        return match.group(3), match.group(2)

    # 5. IMG-YYYYMMDD con cualquier año (ej: escaneos IMG-19981225), validado como fecha
    match = re.search(r'IMG-(\d{8})', filename)
    if match:
        try:
            dt = datetime.strptime(match.group(1), '%Y%m%d')
            return str(dt.year), f"{dt.month:02d}"
        except ValueError:
            pass

    return None, None

def _modification_date(filepath):
    """(año, mes) de la fecha de modificación, o NO_DATE si no se puede leer."""
    try:
        dt_mod = datetime.fromtimestamp(os.stat(filepath).st_mtime)
        return str(dt_mod.year), f"{dt_mod.month:02d}"
    except OSError:
        return NO_DATE

def get_photo_date(filepath: str) -> tuple[str, str]:
    """Fecha de una foto: por el nombre y, si no, por la fecha de modificación."""
    year, month = parse_date_from_filename(filepath)
    if year:
        return year, month
    return _modification_date(filepath)

def get_video_date(filepath: str) -> tuple[str, str]:
    """Fecha de un vídeo: por el nombre y, si no, por la fecha de modificación."""
    return get_photo_date(filepath)
