# drive_manager.py
import io
import threading
import time
from googleapiclient.http import MediaIoBaseDownload
from drive_auth import DriveAuthenticator, DriveAuthError

FOLDER_MIME = "application/vnd.google-apps.folder"

# El cliente de la API de Google no es seguro entre hilos, pero crearlo cuesta
# (lee el token y monta el servicio): cada hilo reutiliza el suyo.
_thread_local = threading.local()

def thread_manager():
    """DriveManager del hilo actual, autenticado. Lanza DriveAuthError sin sesión."""
    manager = getattr(_thread_local, "manager", None)
    if manager is None or manager.service is None:
        manager = DriveManager()
        manager.authenticate()
        _thread_local.manager = manager
    return manager

def reset_thread_managers():
    """Olvida el servicio del hilo actual (p. ej. al cerrar sesión)."""
    _thread_local.manager = None

def visible_folders(folders):
    """Quita las carpetas ocultas ('.algo') y ordena por nombre."""
    folders = [f for f in folders if not f.get('name', '').startswith('.')]
    folders.sort(key=lambda f: f.get('name', '').lower())
    return folders

class DriveManager:
    def __init__(self):
        self.auth = DriveAuthenticator()
        self.service = None

    def authenticate(self):
        """
        Obtiene el servicio con la sesión guardada. Nunca abre el navegador:
        se usa desde hilos en segundo plano. El inicio de sesión lo hace
        DriveLoginWorker cuando el usuario lo pide.
        """
        self.service = self.auth.get_service(silent=True)
        if self.service is None:
            raise DriveAuthError("La sesión de Google ha caducado. Vuelve a conectar desde la pestaña Nube.")
        return True

    def list_folders(self, parent_id='root'):
        """Devuelve carpetas."""
        if not self.service:
            self.authenticate()

        # CASO ESPECIAL: Buscar los Ordenadores
        if parent_id == 'computers':
            # ... (Lógica igual, solo necesitamos el servicio) ...
            query = "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            fields = "nextPageToken, files(id, name, parents, ownedByMe)"

            all_folders = []
            page_token = None

            while True:
                try:
                    results = self.service.files().list(
                        q=query, pageSize=1000, pageToken=page_token, fields=fields
                    ).execute()
                    all_folders.extend(results.get('files', []))
                    page_token = results.get('nextPageToken')
                    if not page_token: break
                except Exception as e:
                    print(f"⚠️ Error buscando ordenadores: {e}")
                    break

            computer_roots = []
            for f in all_folders:
                if not f.get('parents') and f.get('name') != 'Sin Nombre' and not f.get('name', '').startswith('.'):
                    if f.get('ownedByMe', False):
                         computer_roots.append(f)

            computer_roots.sort(key=lambda x: x.get('name', '').lower())
            return computer_roots

        else:
            # Búsqueda normal
            return self.list_subfolders_of_many([parent_id])[parent_id]

    def list_subfolders_of_many(self, parent_ids):
        """
        Subcarpetas de varias carpetas con una sola consulta por cada bloque de
        ids (en vez de una por carpeta): {parent_id: [carpetas]}, también las
        vacías. Sirve para tener listo el siguiente nivel del árbol.
        """
        if not self.service:
            self.authenticate()
        result = {pid: [] for pid in parent_ids}
        ids = list(result)
        for start in range(0, len(ids), 40):  # Que la consulta no sea demasiado larga
            chunk = ids[start:start + 40]
            parents_q = " or ".join(f"'{pid}' in parents" for pid in chunk)
            query = f"({parents_q}) and mimeType = '{FOLDER_MIME}' and trashed = false"
            page_token = None
            while True:
                results = self.service.files().list(
                    q=query, pageSize=1000, pageToken=page_token,
                    fields="nextPageToken, files(id, name, parents)"
                ).execute()
                for f in results.get('files', []):
                    for pid in f.get('parents', []):
                        if pid in result:
                            result[pid].append({'id': f['id'], 'name': f.get('name', '')})
                page_token = results.get('nextPageToken')
                if not page_token:
                    break
        # 'root' es un alias: Drive devuelve el id real en parents
        if 'root' in result and not result['root']:
            results = self.service.files().list(
                q=f"'root' in parents and mimeType = '{FOLDER_MIME}' and trashed = false",
                pageSize=1000, fields="files(id, name)").execute()
            result['root'] = results.get('files', [])
        return {pid: visible_folders(folders) for pid, folders in result.items()}

    def get_thumbnail_link(self, file_id):
        """Enlace de miniatura actual de un archivo (los guardados caducan)."""
        if not self.service:
            self.authenticate()
        return self.service.files().get(fileId=file_id, fields="thumbnailLink").execute().get('thumbnailLink')

    def list_images_recursively(self, folder_id, on_folders=None):
        """
        Generador recursivo de imágenes. Si se indica, on_folders(folder_id,
        subcarpetas) recibe las subcarpetas de cada carpeta recorrida, para
        guardar el árbol de carpetas sin consultarlo otra vez.
        """
        if not self.service:
            self.authenticate()

        page_token = None
        while True:
            query = f"'{folder_id}' in parents and mimeType contains 'image/' and trashed = false"
            try:
                results = self.service.files().list(
                    q=query, pageSize=1000, pageToken=page_token,
                    fields="nextPageToken, files(id, name, mimeType, thumbnailLink, webContentLink, createdTime, parents)"
                ).execute()
            except Exception:
                break

            files = results.get('files', [])
            if files:
                yield files

            page_token = results.get('nextPageToken')
            if not page_token: break

        # Subcarpetas (todas las páginas antes de recorrerlas)
        page_token = None
        subfolders = []
        while True:
            query = f"'{folder_id}' in parents and mimeType = '{FOLDER_MIME}' and trashed = false"
            try:
                results = self.service.files().list(
                    q=query, pageSize=1000, pageToken=page_token, fields="nextPageToken, files(id, name)"
                ).execute()
            except Exception:
                return  # Listado incompleto: no se guarda como si lo fuera
            subfolders.extend(results.get('files', []))
            page_token = results.get('nextPageToken')
            if not page_token: break

        if on_folders:
            on_folders(folder_id, visible_folders(list(subfolders)))
        if subfolders:
            time.sleep(0.1) # Freno de emergencia
        for sub in subfolders:
            yield from self.list_images_recursively(sub['id'], on_folders)

    def download_file(self, file_id, local_path):
        if not self.service:
            self.authenticate()
        request = self.service.files().get_media(fileId=file_id)
        with io.FileIO(local_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
