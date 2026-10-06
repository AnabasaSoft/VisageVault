import os
import pickle
import threading
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import paths

# Varios hilos (escaneo, árbol de carpetas, descargas) usan el mismo token:
# leerlo, renovarlo y guardarlo debe hacerse de uno en uno.
_token_lock = threading.Lock()


class DriveAuthError(Exception):
    """No hay una sesión de Google válida y no se permite abrir el navegador."""


class DriveAuthenticator:
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

    # --- MARCADORES DE POSICIÓN (PLACEHOLDERS) ---
    # GitHub Actions reemplazará esto automáticamente al crear la Release.
    # NO ESCRIBAS TUS CLAVES REALES AQUÍ.
    CLIENT_CONFIG = {
        "installed": {
            "client_id": "BUILD_TIME_CLIENT_ID",
            "project_id": "visagevault",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": "BUILD_TIME_CLIENT_SECRET",
            "redirect_uris": ["http://localhost"]
        }
    }
    # ---------------------------------------------------------

    def __init__(self):
        self.creds = None
        self.token_file = self._get_token_path()

    def _get_token_path(self):
        return os.path.join(paths.data_dir(), "token.json")

    def get_service(self, silent=False):
        """
        Devuelve el servicio de Drive. Si no hay sesión válida (ni se puede
        renovar): con silent=True devuelve None; si no, abre el navegador
        para iniciar sesión. Solo el inicio de sesión explícito del usuario
        debe usar silent=False.
        """
        with _token_lock:
            creds = self._load_valid_creds()

        if creds is None:
            if silent:
                return None
            # Fuera del cerrojo: el usuario puede tardar en el navegador
            creds = self._perform_login()
            with _token_lock:
                self._save_creds(creds)

        self.creds = creds
        return build('drive', 'v3', credentials=creds)

    def _load_valid_creds(self):
        """Lee el token y lo renueva si ha caducado. None si no hay sesión válida."""
        creds = None
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'rb') as token:
                    creds = pickle.load(token)
            except Exception as e:
                print(f"No se pudo leer el token de Google: {e}")

        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_creds(creds)
                return creds
            except Exception as e:
                print(f"No se pudo renovar la sesión de Google: {e}")
        return None

    def _save_creds(self, creds):
        """Guarda el token de forma atómica y solo legible por el usuario."""
        temp_path = self.token_file + ".tmp"
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'wb') as token:
            pickle.dump(creds, token)
        os.replace(temp_path, self.token_file)

    def _perform_login(self):
        """Login usando el diccionario incrustado en lugar de un archivo."""

        flow = InstalledAppFlow.from_client_config(
            self.CLIENT_CONFIG, self.SCOPES
        )
        return flow.run_local_server(port=0)

    def has_credentials(self):
        return os.path.exists(self.token_file)

    def logout(self):
        with _token_lock:
            if os.path.exists(self.token_file):
                os.remove(self.token_file)
                return True
            return False
