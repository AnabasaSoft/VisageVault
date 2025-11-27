import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

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
        base_dir = os.path.dirname(os.path.abspath(__file__))
        filename = "token.json"
        # Si no podemos escribir aquí (instalación en /usr/share), vamos a ~/.local
        if not os.access(base_dir, os.W_OK):
            user_dir = os.path.join(os.path.expanduser("~"), ".local", "share", "visagevault")
            os.makedirs(user_dir, exist_ok=True)
            return os.path.join(user_dir, filename)
        return os.path.join(base_dir, filename)

    def get_service(self, silent=False):
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'rb') as token:
                    self.creds = pickle.load(token)
            except Exception: pass

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                except Exception:
                    if silent: return None
                    self._perform_login()
            else:
                if silent: return None
                self._perform_login()

            # Guardar sesión
            with open(self.token_file, 'wb') as token:
                pickle.dump(self.creds, token)

        return build('drive', 'v3', credentials=self.creds)

    def _perform_login(self):
        """Login usando el diccionario incrustado en lugar de un archivo."""

        flow = InstalledAppFlow.from_client_config(
            self.CLIENT_CONFIG, self.SCOPES
        )
        self.creds = flow.run_local_server(port=0)

    def has_credentials(self):
        return os.path.exists(self.token_file)

    def logout(self):
        if os.path.exists(self.token_file):
            os.remove(self.token_file)
            return True
        return False
