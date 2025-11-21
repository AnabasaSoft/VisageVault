# drive_manager.py
import os
import io
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import sys

# Si modificas estos scopes, borra el archivo user_token.pickle.
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def resource_path(relative_path):
    """Obtiene la ruta absoluta al recurso (compatible con PyInstaller)."""
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

class DriveManager:
    def __init__(self):
        self.creds = None
        self.service = None
        self.token_file = os.path.join(os.path.dirname(__file__), 'user_token.pickle')
        self.secrets_path = resource_path('client_secrets.json')

    def authenticate(self):
        """Maneja el flujo de autenticación OAuth2."""
        # 1. Cargar token guardado
        if os.path.exists(self.token_file):
            with open(self.token_file, 'rb') as token:
                self.creds = pickle.load(token)

        # 2. Si no hay credenciales válidas, pedir login
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                except Exception:
                    self._start_new_flow()
            else:
                self._start_new_flow()

            # 3. Guardar credenciales para la próxima
            with open(self.token_file, 'wb') as token:
                pickle.dump(self.creds, token)

        self.service = build('drive', 'v3', credentials=self.creds)
        return True

    def _start_new_flow(self):
        if not os.path.exists(self.secrets_path):
            raise FileNotFoundError("Falta el archivo 'client_secrets.json'.")

        flow = InstalledAppFlow.from_client_secrets_file(self.secrets_path, SCOPES)
        self.creds = flow.run_local_server(port=0)

    def list_folders(self, parent_id='root'):
        """
        Devuelve carpetas.
        - Si parent_id='root': Busca dentro de Mi Unidad.
        - Si parent_id='computers': Busca raíces de Ordenadores (filtrando basura compartida).
        - Si es otro ID: Busca dentro de esa carpeta.
        """
        if not self.service:
            self.authenticate()

        # CASO ESPECIAL: Buscar los Ordenadores
        if parent_id == 'computers':
            print("🔍 Buscando 'Mi Ordenador' y filtrando carpetas compartidas...")

            # IMPORTANTE: Solicitamos 'ownedByMe' para saber si la carpeta es tuya o compartida
            query = "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            fields = "nextPageToken, files(id, name, parents, ownedByMe)"

            all_folders = []
            page_token = None

            # Paginación para leer todo tu Drive
            while True:
                try:
                    results = self.service.files().list(
                        q=query,
                        pageSize=1000,
                        pageToken=page_token,
                        fields=fields
                    ).execute()

                    all_folders.extend(results.get('files', []))
                    page_token = results.get('nextPageToken')
                    if not page_token:
                        break
                except Exception as e:
                    print(f"⚠️ Error buscando página de ordenadores: {e}")
                    break

            print(f"   Total carpetas analizadas: {len(all_folders)}")

            computer_roots = []
            for f in all_folders:
                name = f.get('name', 'Sin Nombre')

                # 1. Ignorar carpetas de sistema (.) o sin nombre
                if name.startswith('.') or name == 'Sin Nombre':
                    continue

                # 2. BUSCAR RAÍCES: Si NO tiene padre...
                if not f.get('parents'):

                    # 3. FILTRO DE LIMPIEZA: Solo mostramos si es TUYA (ownedByMe).
                    # Esto elimina "Survival Books", "Neo geo" y otras carpetas compartidas.
                    if f.get('ownedByMe', False):
                         print(f"   ✅ RAÍZ VÁLIDA (TUYA): '{name}' (ID: {f['id']})")
                         computer_roots.append(f)
                    else:
                         # Esto filtra las carpetas compartidas que ensucian la lista
                         pass

            # Ordenar alfabéticamente
            computer_roots.sort(key=lambda x: x.get('name', '').lower())

            if not computer_roots:
                print("❌ No se encontraron carpetas raíz propias. Verifica si 'Mi Ordenador' es de tu propiedad.")

            return computer_roots

        else:
            # Búsqueda normal jerárquica (dentro de una carpeta específica)
            query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            fields = "files(id, name)"

            results = self.service.files().list(
                q=query,
                pageSize=1000,
                orderBy="name",
                fields=fields
            ).execute()

            all_folders = results.get('files', [])
            visible_folders = [f for f in all_folders if not f.get('name', '').startswith('.')]
            return visible_folders

    def list_images(self, folder_id=None, page_size=100, page_token=None):
        """Devuelve una lista de imágenes. Si folder_id existe, filtra por esa carpeta."""
        if not self.service:
            self.authenticate()

        query = "mimeType contains 'image/' and trashed = false"

        # --- FILTRO POR CARPETA ---
        if folder_id:
            query += f" and '{folder_id}' in parents"
        # --------------------------

        results = self.service.files().list(
            q=query,
            pageSize=page_size,
            pageToken=page_token,
            # Pedimos campos específicos: ID, nombre, thumbnail, enlace web
            fields="nextPageToken, files(id, name, mimeType, thumbnailLink, webContentLink, createdTime)"
        ).execute()

        items = results.get('files', [])
        next_token = results.get('nextPageToken')
        return items, next_token

    def download_file(self, file_id, local_path):
        """Descarga un archivo completo al disco local."""
        if not self.service:
            self.authenticate()

        request = self.service.files().get_media(fileId=file_id)
        fh = io.FileIO(local_path, 'wb')
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while done is False:
            status, done = downloader.next_chunk()

    def list_images_recursively(self, folder_id):
        """
        Generador recursivo que busca imágenes en todas las subcarpetas.
        INCLUYE UN FRENO (time.sleep) para evitar bloquear la interfaz por exceso de velocidad.
        """
        if not self.service:
            self.authenticate()

        # --- PARTE 1: BUSCAR IMÁGENES EN LA CARPETA ACTUAL ---
        page_token = None
        while True:
            query = f"'{folder_id}' in parents and mimeType contains 'image/' and trashed = false"
            try:
                results = self.service.files().list(
                    q=query,
                    pageSize=1000,
                    pageToken=page_token,
                    fields="nextPageToken, files(id, name, mimeType, thumbnailLink, webContentLink, createdTime)"
                ).execute()
            except Exception as e:
                print(f"⚠️ Error listando imágenes en {folder_id}: {e}")
                break

            files = results.get('files', [])
            if files:
                # Devuelve este lote de imágenes al Worker para que las guarde
                yield files

            page_token = results.get('nextPageToken')
            if not page_token:
                break

        # --- PARTE 2: BUSCAR SUBCARPETAS (RECURSIÓN) ---
        page_token = None
        while True:
            query = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            try:
                results = self.service.files().list(
                    q=query,
                    pageSize=1000,
                    pageToken=page_token,
                    fields="nextPageToken, files(id, name)"
                ).execute()
            except Exception as e:
                print(f"⚠️ Error listando subcarpetas en {folder_id}: {e}")
                break

            subfolders = results.get('files', [])

            # === AQUÍ ESTÁ EL FRENO DE EMERGENCIA ===
            if subfolders:
                # Importamos time aquí por seguridad si no está arriba
                import time

                # Pequeña pausa (0.1 segundos) antes de procesar las subcarpetas.
                # Esto evita que el script entre en 100 carpetas por segundo y sature la CPU.
                time.sleep(0.1)
            # ========================================

            for sub in subfolders:
                # Llamada recursiva: Entramos en la subcarpeta
                yield from self.list_images_recursively(sub['id'])

            page_token = results.get('nextPageToken')
            if not page_token:
                break
