# metadata_reader.py
import piexif
from PIL import Image
from PIL.ExifTags import TAGS
from datetime import datetime
from pathlib import Path

def get_photo_date(filepath: str) -> tuple[str, str] | None:
    """
    Lee la fecha de creación de una foto a partir de los metadatos EXIF.
    Devuelve una tupla (año, mes) o None.
    El mes es un string de dos dígitos (ej: "08").
    """
    try:
        img = Image.open(filepath)
        exif_data = img.getexif()

        if exif_data:
            # Buscar el campo "DateTimeOriginal" (código 36867) o "DateTime" (código 306)
            for tag_id, value in exif_data.items():
                if TAGS.get(tag_id) in ['DateTimeOriginal', 'DateTime']:
                    # El formato EXIF es 'YYYY:MM:DD HH:MM:SS'
                    try:
                        dt = datetime.strptime(value, '%Y:%m:%d %H:%M:%S')
                        return str(dt.year), f"{dt.month:02d}"
                    except ValueError:
                        pass # Si el formato es incorrecto, seguimos buscando

        # Si no hay EXIF o no encontramos la fecha, usamos la fecha de modificación del archivo
        stat = Path(filepath).stat()
        dt_mod = datetime.fromtimestamp(stat.st_mtime)
        return str(dt_mod.year), f"{dt_mod.month:02d}"

    except Exception:
        # Puede fallar si no es un formato de imagen válido o el archivo está corrupto
        return "Sin Fecha", "00"

def get_exif_dict(filepath: str) -> dict:
    """
    Lee todos los metadatos EXIF de una imagen usando piexif.
    Devuelve un diccionario (puede estar vacío).
    """
    try:
        exif_dict = piexif.load(filepath)
        return exif_dict
    except Exception:
        # Si no hay EXIF o el formato no es compatible (ej. PNG)
        return {}

def save_exif_dict(filepath: str, exif_dict: dict):
    """
    Guarda el diccionario de metadatos EXIF en el archivo de imagen.
    """
    try:
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, filepath)
        print(f"Metadatos guardados en: {filepath}")
    except Exception as e:
        print(f"Error al guardar metadatos en {filepath}: {e}")
