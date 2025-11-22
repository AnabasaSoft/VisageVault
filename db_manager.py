# ==============================================================================
# ARCHIVO: db_manager.py
# DESCRIPCIÓN: Gestor de base de datos SQLite para VisageVault
# INCLUYE: Migraciones automáticas, soporte para Ocultar/Borrar y optimización.
# ==============================================================================

import sqlite3
import os
import pickle
import datetime

class VisageVaultDB:
    def __init__(self, db_name="visagevault.db", is_worker=False):
        """
        Inicializa la conexión a la base de datos.
        Si is_worker=True, evita crear tablas/migraciones para prevenir conflictos en hilos.
        """
        # Guardar la BD en el mismo directorio que el script
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.db_path = os.path.join(base_dir, db_name)

        # check_same_thread=False es necesario para aplicaciones GUI con hilos (QThread)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Permite acceder a columnas por nombre

        # --- OPTIMIZACIÓN CLAVE: WAL MODE ---
        # Permite lecturas y escrituras concurrentes sin bloqueo total
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;") # Un poco menos seguro ante cortes de luz, pero mucho más rápido

        # Solo el hilo principal debe gestionar la estructura de la BD
        if not is_worker:
            self._create_tables()
            self._check_migrations()

    def _create_tables(self):
        """Crea la estructura inicial de tablas si no existe."""
        with self.conn:
            # 1. Tabla de FOTOS
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filepath TEXT UNIQUE,
                    year TEXT,
                    month TEXT,
                    scanned_for_faces INTEGER DEFAULT 0,
                    is_hidden INTEGER DEFAULT 0
                )
            """)

            # 2. Tabla de VÍDEOS
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filepath TEXT UNIQUE,
                    year TEXT,
                    month TEXT,
                    is_hidden INTEGER DEFAULT 0
                )
            """)

            # 3. Tabla de PERSONAS
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS people (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE
                )
            """)

            # 4. Tabla de CARAS (Relacionada con Fotos y Personas)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS faces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    photo_id INTEGER,
                    encoding BLOB,
                    location TEXT,
                    person_id INTEGER DEFAULT NULL,
                    is_deleted INTEGER DEFAULT 0,
                    FOREIGN KEY(photo_id) REFERENCES photos(id),
                    FOREIGN KEY(person_id) REFERENCES people(id)
                )
            """)

            # 5. Tabla de GOOGLE DRIVE
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS drive_photos (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    created_time TEXT,
                    mime_type TEXT,
                    thumbnail_link TEXT,
                    web_content_link TEXT,
                    parent_id TEXT
                )
            """)

            # 6. Tabla de CAJA FUERTE
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS safe_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_path TEXT,     -- Ruta original para restaurar
                    encrypted_path TEXT,    -- Dónde está ahora (visagevault_safe/...)
                    media_type TEXT,        -- 'photo' o 'video'
                    original_date TEXT      -- Para re-ordenar al restaurar
                )
            """)

    def _check_migrations(self):
        """
        Verifica si la base de datos existente necesita actualizaciones de estructura
        (por ejemplo, si el usuario viene de una versión anterior).
        """
        try:
            with self.conn:
                # --- Migración FOTOS (Añadir is_hidden) ---
                cursor = self.conn.execute("PRAGMA table_info(photos)")
                columns_photos = [col['name'] for col in cursor.fetchall()]

                if 'is_hidden' not in columns_photos:
                    print("INFO: Migrando base de datos... Añadiendo columna 'is_hidden' a photos.")
                    self.conn.execute("ALTER TABLE photos ADD COLUMN is_hidden INTEGER DEFAULT 0")

                # --- Migración VÍDEOS (Añadir is_hidden) ---
                cursor = self.conn.execute("PRAGMA table_info(videos)")
                columns_videos = [col['name'] for col in cursor.fetchall()]

                if 'is_hidden' not in columns_videos:
                    print("INFO: Migrando base de datos... Añadiendo columna 'is_hidden' a videos.")
                    self.conn.execute("ALTER TABLE videos ADD COLUMN is_hidden INTEGER DEFAULT 0")

                # --- Migración DRIVE (Añadir root_folder_id) ---
                # Primero verificamos si la tabla drive_photos existe (puede que sea una instalación nueva)
                cursor = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='drive_photos'")
                if cursor.fetchone():
                    cursor = self.conn.execute("PRAGMA table_info(drive_photos)")
                    columns_drive = [col['name'] for col in cursor.fetchall()]

                    if 'root_folder_id' not in columns_drive:
                        print("INFO: Migrando BD Drive... Añadiendo columna 'root_folder_id' a drive_photos.")
                        self.conn.execute("ALTER TABLE drive_photos ADD COLUMN root_folder_id TEXT")

        except Exception as e:
            print(f"ERROR en migraciones de BD: {e}")

    # =========================================================================
    # GESTIÓN DE FOTOS
    # =========================================================================

    def load_all_photo_dates(self):
        """Carga todas las fechas de fotos para el escaneo inicial."""
        # Solo cargamos las que NO están ocultas para el mapa visual normal,
        # o cargamos todas y filtramos luego. Para sincronizar es mejor cargar todo.
        cursor = self.conn.execute("SELECT filepath, year, month FROM photos")
        return {row['filepath']: (row['year'], row['month']) for row in cursor.fetchall()}

    def bulk_upsert_photos(self, photos_list):
        """Inserta o actualiza muchas fotos de golpe (optimización)."""
        with self.conn:
            self.conn.executemany("""
                INSERT INTO photos (filepath, year, month)
                VALUES (?, ?, ?)
                ON CONFLICT(filepath) DO UPDATE SET
                year=excluded.year,
                month=excluded.month
            """, photos_list)

    def bulk_delete_photos(self, paths_list):
        """Elimina fotos que ya no existen en disco de la BD."""
        if not paths_list:
            return
        with self.conn:
            # Convertir lista a lista de tuplas para executemany
            tuples = [(p,) for p in paths_list]
            self.conn.executemany("DELETE FROM photos WHERE filepath = ?", tuples)

    def get_photo_date(self, filepath):
        cursor = self.conn.execute("SELECT year, month FROM photos WHERE filepath = ?", (filepath,))
        row = cursor.fetchone()
        if row:
            return row['year'], row['month']
        return None, None

    def update_photo_date(self, filepath, year, month):
        with self.conn:
            self.conn.execute("UPDATE photos SET year = ?, month = ? WHERE filepath = ?", (year, month, filepath))

    # --- Funciones de Ocultar/Borrar Fotos ---

    def hide_photo(self, photo_path):
        with self.conn:
            self.conn.execute("UPDATE photos SET is_hidden = 1 WHERE filepath = ?", (photo_path,))

    def unhide_photo(self, photo_path):
        with self.conn:
            self.conn.execute("UPDATE photos SET is_hidden = 0 WHERE filepath = ?", (photo_path,))

    def get_hidden_photos(self):
        """Devuelve lista de rutas de fotos ocultas."""
        cursor = self.conn.execute("SELECT filepath FROM photos WHERE is_hidden = 1")
        return [row['filepath'] for row in cursor.fetchall()]

    def delete_photo_permanently(self, photo_path):
        """Borra la foto de la BD y sus caras asociadas."""
        with self.conn:
            # 1. Obtener ID para borrar caras
            cur = self.conn.execute("SELECT id FROM photos WHERE filepath = ?", (photo_path,))
            row = cur.fetchone()
            if row:
                photo_id = row['id']
                self.conn.execute("DELETE FROM faces WHERE photo_id = ?", (photo_id,))

            # 2. Borrar la entrada de la foto
            self.conn.execute("DELETE FROM photos WHERE filepath = ?", (photo_path,))

    # =========================================================================
    # GESTIÓN DE VÍDEOS
    # =========================================================================

    def load_all_video_dates(self):
        cursor = self.conn.execute("SELECT filepath, year, month FROM videos")
        return {row['filepath']: (row['year'], row['month']) for row in cursor.fetchall()}

    def get_video_date(self, filepath):
        cursor = self.conn.execute("SELECT year, month FROM videos WHERE filepath = ?", (filepath,))
        row = cursor.fetchone()
        if row:
            return row['year'], row['month']
        return None, None

    def bulk_upsert_videos(self, videos_list):
        with self.conn:
            self.conn.executemany("""
                INSERT INTO videos (filepath, year, month)
                VALUES (?, ?, ?)
                ON CONFLICT(filepath) DO UPDATE SET
                year=excluded.year,
                month=excluded.month
            """, videos_list)

    def bulk_delete_videos(self, paths_list):
        if not paths_list:
            return
        with self.conn:
            tuples = [(p,) for p in paths_list]
            self.conn.executemany("DELETE FROM videos WHERE filepath = ?", tuples)

    # --- Funciones de Ocultar/Borrar Vídeos ---

    def hide_video(self, video_path):
        with self.conn:
            self.conn.execute("UPDATE videos SET is_hidden = 1 WHERE filepath = ?", (video_path,))

    def unhide_video(self, video_path):
        with self.conn:
            self.conn.execute("UPDATE videos SET is_hidden = 0 WHERE filepath = ?", (video_path,))

    def get_hidden_videos(self):
        cursor = self.conn.execute("SELECT filepath FROM videos WHERE is_hidden = 1")
        return [row['filepath'] for row in cursor.fetchall()]

    def delete_video_permanently(self, video_path):
        with self.conn:
            self.conn.execute("DELETE FROM videos WHERE filepath = ?", (video_path,))

    def update_video_date(self, filepath, year, month):
        with self.conn:
            self.conn.execute("UPDATE videos SET year = ?, month = ? WHERE filepath = ?", (year, month, filepath))

    # =========================================================================
    # GESTIÓN DE CARAS (Reconocimiento Facial)
    # =========================================================================

    def get_unscanned_photos(self):
        """Devuelve fotos que aún no han sido escaneadas en busca de caras y no están ocultas."""
        cursor = self.conn.execute("""
            SELECT id, filepath FROM photos
            WHERE scanned_for_faces = 0 AND is_hidden = 0
        """)
        return cursor.fetchall()

    def mark_photo_as_scanned(self, photo_id):
        with self.conn:
            self.conn.execute("UPDATE photos SET scanned_for_faces = 1 WHERE id = ?", (photo_id,))

    def add_face(self, photo_id, encoding_blob, location_str):
        with self.conn:
            cursor = self.conn.execute("""
                INSERT INTO faces (photo_id, encoding, location)
                VALUES (?, ?, ?)
            """, (photo_id, encoding_blob, location_str))
            return cursor.lastrowid

    def get_unknown_faces(self):
        """Obtiene caras no asignadas a ninguna persona y no eliminadas."""
        cursor = self.conn.execute("""
            SELECT f.id, f.location, p.filepath
            FROM faces f
            JOIN photos p ON f.photo_id = p.id
            WHERE f.person_id IS NULL AND f.is_deleted = 0 AND p.is_hidden = 0
        """)
        return cursor.fetchall()

    def get_unknown_face_encodings(self):
        """Obtiene encodings de caras desconocidas para el clustering."""
        cursor = self.conn.execute("""
            SELECT id, encoding FROM faces
            WHERE person_id IS NULL AND is_deleted = 0
        """)
        data = []
        for row in cursor.fetchall():
            try:
                encoding = pickle.loads(row['encoding'])
                data.append((row['id'], encoding))
            except:
                pass
        return data

    def get_face_info(self, face_id):
        """Obtiene ruta y ubicación para recortar la miniatura de la cara."""
        cursor = self.conn.execute("""
            SELECT f.location, p.filepath
            FROM faces f
            JOIN photos p ON f.photo_id = p.id
            WHERE f.id = ?
        """, (face_id,))
        row = cursor.fetchone()
        if row:
            return {'location': row['location'], 'filepath': row['filepath']}
        return None

    def soft_delete_face(self, face_id):
        """Marca una cara como eliminada (falso positivo)."""
        with self.conn:
            self.conn.execute("UPDATE faces SET is_deleted = 1, person_id = NULL WHERE id = ?", (face_id,))

    def restore_face(self, face_id):
        """Restaura una cara eliminada."""
        with self.conn:
            self.conn.execute("UPDATE faces SET is_deleted = 0 WHERE id = ?", (face_id,))

    def get_deleted_faces(self):
        """Devuelve caras marcadas como eliminadas (papelera de caras)."""
        cursor = self.conn.execute("""
            SELECT f.id, f.location, p.filepath
            FROM faces f
            JOIN photos p ON f.photo_id = p.id
            WHERE f.is_deleted = 1 AND p.is_hidden = 0
        """)
        return cursor.fetchall()

    # =========================================================================
    # GESTIÓN DE PERSONAS
    # =========================================================================

    def add_person(self, name):
        try:
            with self.conn:
                cursor = self.conn.execute("INSERT INTO people (name) VALUES (?)", (name,))
                return cursor.lastrowid
        except sqlite3.IntegrityError:
            return -1 # Ya existe

    def get_all_people(self):
        cursor = self.conn.execute("SELECT id, name FROM people ORDER BY name ASC")
        return cursor.fetchall()

    def get_person_by_name(self, name):
        cursor = self.conn.execute("SELECT id, name FROM people WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            return {'id': row['id'], 'name': row['name']}
        return None

    def link_face_to_person(self, face_id, person_id):
        with self.conn:
            self.conn.execute("UPDATE faces SET person_id = ? WHERE id = ?", (person_id, face_id))

    def get_faces_for_person(self, person_id):
        """Obtiene todas las fotos donde aparece esta persona."""
        cursor = self.conn.execute("""
            SELECT p.filepath, p.year, p.month, f.location
            FROM faces f
            JOIN photos p ON f.photo_id = p.id
            WHERE f.person_id = ? AND f.is_deleted = 0 AND p.is_hidden = 0
            ORDER BY p.year DESC, p.month DESC
        """, (person_id,))
        return cursor.fetchall()

    def get_all_drive_photos(self, root_folder_id=None):
        """Recupera fotos de Drive, opcionalmente filtradas por carpeta raíz."""
        if root_folder_id:
            # Si nos pasan un ID, filtramos solo las fotos de esa carpeta
            cursor = self.conn.execute("SELECT * FROM drive_photos WHERE root_folder_id = ?", (root_folder_id,))
        else:
            # Si no (comportamiento antiguo), devolvemos todo
            cursor = self.conn.execute("SELECT * FROM drive_photos")

        return [dict(row) for row in cursor.fetchall()]

    def bulk_upsert_drive_photos(self, photos_list, root_folder_id=None):
        """Guarda fotos de Drive vinculadas a una carpeta raíz."""
        if not photos_list: return

        data_to_insert = []
        for p in photos_list:
            # Extraer padre (Drive lo da como lista, cogemos el primero o string vacío)
            parent = p.get('parents', [''])[0] if p.get('parents') else ''

            data_to_insert.append((
                p.get('id'),
                p.get('name'),
                p.get('createdTime'),
                p.get('mimeType'),
                p.get('thumbnailLink'),
                p.get('webContentLink'),
                parent,
                root_folder_id
            ))

        with self.conn:
            self.conn.executemany("""
                INSERT INTO drive_photos (id, name, created_time, mime_type, thumbnail_link, web_content_link, parent_id, root_folder_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                thumbnail_link=excluded.thumbnail_link,
                root_folder_id=excluded.root_folder_id,
                parent_id=excluded.parent_id  -- <--- ¡ESTA LÍNEA ES NUEVA Y CRÍTICA!
            """, data_to_insert)


    def clear_drive_data(self):
        """
        SEGURIDAD: Elimina todos los registros de fotos de la nube de la base de datos local.
        """
        with self.conn:
            self.conn.execute("DELETE FROM drive_photos")
            # Opcional: VACUUM para reducir tamaño del archivo, aunque puede ser lento
            # self.conn.execute("VACUUM")

    def get_drive_photos_by_parent(self, parent_id):
        # IMPORTANTE: Esta consulta busca fotos cuyo PADRE DIRECTO sea la carpeta clickeada
        cursor = self.conn.execute("SELECT * FROM drive_photos WHERE parent_id = ?", (parent_id,))
        return [dict(row) for row in cursor.fetchall()]

    def update_drive_photo_date(self, file_id, new_iso_date):
        """
        Actualiza la fecha de una foto de Drive localmente para reorganizarla.
        """
        with self.conn:
            self.conn.execute("UPDATE drive_photos SET created_time = ? WHERE id = ?", (new_iso_date, file_id))

    def add_to_safe(self, original_path, encrypted_path, media_type, date_str):
        with self.conn:
            self.conn.execute("""
                INSERT INTO safe_files (original_path, encrypted_path, media_type, original_date)
                VALUES (?, ?, ?, ?)
            """, (original_path, encrypted_path, media_type, date_str))

    def get_safe_files(self):
        cursor = self.conn.execute("SELECT * FROM safe_files")
        return cursor.fetchall()

    def remove_from_safe(self, encrypted_path):
        with self.conn:
            self.conn.execute("DELETE FROM safe_files WHERE encrypted_path = ?", (encrypted_path,))
