# drive_manager.py
import io
from googleapiclient.http import MediaIoBaseDownload
from drive_auth import DriveAuthenticator, DriveAuthError

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
            query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            fields = "files(id, name)"
            results = self.service.files().list(q=query, pageSize=1000, orderBy="name", fields=fields).execute()
            all_folders = results.get('files', [])
            return [f for f in all_folders if not f.get('name', '').startswith('.')]

    def list_images_recursively(self, folder_id):
        """Generador recursivo de imágenes."""
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

        # Subcarpetas
        page_token = None
        while True:
            query = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            try:
                results = self.service.files().list(
                    q=query, pageSize=1000, pageToken=page_token, fields="nextPageToken, files(id, name)"
                ).execute()
            except Exception:
                break

            subfolders = results.get('files', [])
            if subfolders:
                import time
                time.sleep(0.1) # Freno de emergencia

            for sub in subfolders:
                yield from self.list_images_recursively(sub['id'])

            page_token = results.get('nextPageToken')
            if not page_token: break

    def download_file(self, file_id, local_path):
        if not self.service:
            self.authenticate()
        request = self.service.files().get_media(fileId=file_id)
        with io.FileIO(local_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
