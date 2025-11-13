# db_manager.py

import sqlite3
from pathlib import Path

class VisageVaultDB:
    """
    Clase que maneja la conexión y las operaciones de la base de datos SQLite.
    Cada método abre y cierra su propia conexión para ser seguro en múltiples hilos.
    """
    def __init__(self, db_file="visagevault.db"):
        self.db_file = db_file
        self.create_tables()

    def _get_connection(self):
        """Función auxiliar para obtener una conexión local al hilo."""
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        return conn

    def create_tables(self):
        """Define y crea las tablas si no existen, y añade la columna 'month' si es necesario."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # 1. Tabla PHOTOS (Añadida la columna 'month')
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS photos (
                    id INTEGER PRIMARY KEY,
                    filepath TEXT NOT NULL UNIQUE,
                    file_hash TEXT UNIQUE,
                    year TEXT,
                    month TEXT
                )
            """)

            # --- MIGRACIÓN: Añadir columna 'month' si no existe ---
            cursor.execute("PRAGMA table_info(photos)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'month' not in columns:
                print("Migrando base de datos: añadiendo columna 'month'...")
                cursor.execute("ALTER TABLE photos ADD COLUMN month TEXT")

            # 2. Tabla FACES (Datos de reconocimiento)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS faces (
                    id INTEGER PRIMARY KEY,
                    photo_id INTEGER NOT NULL,
                    encoding BLOB NOT NULL,
                    location TEXT,
                    FOREIGN KEY (photo_id) REFERENCES photos (id)
                )
            """)

            # 3. Tabla PEOPLE (Etiquetas de personas)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS people (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE
                )
            """)

            # 4. Tabla de Unión para etiquetar las caras
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS face_labels (
                    face_id INTEGER NOT NULL,
                    person_id INTEGER NOT NULL,
                    PRIMARY KEY (face_id, person_id),
                    FOREIGN KEY (face_id) REFERENCES faces (id),
                    FOREIGN KEY (person_id) REFERENCES people (id)
                )
            """)

            conn.commit()
            print("Tablas verificadas y listas.")
        except sqlite3.Error as e:
            print(f"Error al crear/migrar tablas: {e}")
        finally:
            conn.close()

    # --- Funciones de Lectura (Usadas por PhotoFinderWorker) ---

    def load_all_photo_dates(self) -> dict:
        """
        Carga todas las rutas, años y meses conocidos desde la BD a un diccionario.
        Devuelve: {'/ruta/foto1.jpg': ('2025', '08'), ...}
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT filepath, year, month FROM photos")
            return {row['filepath']: (row['year'], row['month']) for row in cursor.fetchall()}
        except sqlite3.Error as e:
            print(f"Error al cargar fechas de la BD: {e}")
            return {}
        finally:
            conn.close()

    def bulk_upsert_photos(self, photos_data: list[tuple[str, str, str]]):
        """
        Inserta o reemplaza una lista de fotos con su año y mes.
        (photos_data es una lista de tuplas: (filepath, year, month))
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO photos (filepath, year, month)
                VALUES (?, ?, ?)
            """, photos_data)
            conn.commit()
        except sqlite3.Error as e:
            print(f"Error en bulk_upsert_photos: {e}")
        finally:
            conn.close()

    # --- Funciones de Edición (Usadas por PhotoDetailDialog) ---

    def update_photo_date(self, filepath: str, new_year: str, new_month: str):
        """Actualiza el año y mes de una foto específica."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE photos SET year = ?, month = ? WHERE filepath = ?", (new_year, new_month, filepath))
            conn.commit()
        except sqlite3.Error as e:
            print(f"Error al actualizar la fecha: {e}")
        finally:
            conn.close()

    def get_photo_date(self, filepath: str) -> tuple[str, str] | None:
        """Obtiene el año y mes guardados para una sola foto."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT year, month FROM photos WHERE filepath = ?", (filepath,))
            result = cursor.fetchone()
            return (result['year'], result['month']) if result else None
        except sqlite3.Error:
            return None
        finally:
            conn.close()

    def close(self):
        pass

if __name__ == "__main__":
    # Ejemplo de uso:
    db = VisageVaultDB(db_file="test_visagevault.db")
    print("\nPrueba de carga:")
    print(db.load_all_photo_dates())

    # Pruebas de inserción
    test_data = [
        ("/home/test/foto1.jpg", "2024", "01"),
        ("/home/test/foto2.jpg", "2025", "12"),
    ]
    db.bulk_upsert_photos(test_data)
    print(db.load_all_photo_dates())

    # Prueba de actualización
    db.update_photo_date("/home/test/foto1.jpg", "2023", "05")
    print(db.get_photo_date("/home/test/foto1.jpg"))
    db.close()
