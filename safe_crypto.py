# safe_crypto.py
"""
Cifrado de la caja fuerte.

Formato actual (VVAES1): AES-256-GCM por bloques de 4 MiB.
    MAGIC (6) + prefijo de nonce aleatorio (8)
    y por cada bloque: longitud (4, big-endian) + texto cifrado con etiqueta.
    El nonce de cada bloque es prefijo + índice; los datos autenticados
    (AAD) incluyen la cabecera, el índice y si es el último bloque, de modo
    que se detectan bloques alterados, reordenados o un archivo truncado.

La clave se deriva de la contraseña con scrypt y una sal aleatoria guardada
en la configuración. La contraseña se comprueba con un verificador HMAC
derivado de la clave, que no permite reconstruir la clave.

Formato antiguo (legado): XOR con sha256(contraseña). Solo se lee, para
poder migrar las cajas fuertes creadas con versiones anteriores.
"""
import base64
import hashlib
import hmac
import os

import numpy as np
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"VVAES1"
NONCE_PREFIX_SIZE = 8
HEADER_SIZE = len(MAGIC) + NONCE_PREFIX_SIZE
CHUNK_SIZE = 4 * 1024 * 1024  # Múltiplo de 32: alineado también con el XOR legado

_VERIFIER_LABEL = b"visagevault-safe-verifier"


# =============================================================================
# CLAVES
# =============================================================================

def new_kdf_params():
    """Parámetros scrypt nuevos (con sal aleatoria) para guardar en la config."""
    return {
        "salt": base64.b64encode(os.urandom(16)).decode("ascii"),
        "n": 2 ** 15,
        "r": 8,
        "p": 1,
    }


def derive_key(password, kdf):
    """Deriva la clave AES de 32 bytes a partir de la contraseña."""
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=base64.b64decode(kdf["salt"]),
        n=kdf["n"], r=kdf["r"], p=kdf["p"],
        maxmem=128 * 1024 * 1024,
        dklen=32,
    )


def make_verifier(key):
    return hmac.new(key, _VERIFIER_LABEL, hashlib.sha256).hexdigest()


def check_verifier(key, verifier):
    return hmac.compare_digest(make_verifier(key), verifier)


def legacy_key(password):
    """Clave del formato antiguo (XOR). Solo para migrar archivos viejos."""
    return hashlib.sha256(password.encode()).digest()


# =============================================================================
# ARCHIVOS
# =============================================================================

def is_legacy_file(path):
    """True si el archivo no tiene la cabecera del formato actual."""
    with open(path, "rb") as f:
        return f.read(len(MAGIC)) != MAGIC


def _read_chunks(path):
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                return
            yield chunk


def _legacy_chunks(path, legacy_key_bytes):
    key_tile = np.resize(np.frombuffer(legacy_key_bytes, dtype=np.uint8), CHUNK_SIZE)
    for chunk in _read_chunks(path):
        arr = np.frombuffer(chunk, dtype=np.uint8)
        yield np.bitwise_xor(arr, key_tile[:len(arr)]).tobytes()


def _aad(header, index, last):
    return header + index.to_bytes(4, "big") + (b"\x01" if last else b"\x00")


def _encrypt_chunks(chunks, f_out, key):
    aes = AESGCM(key)
    prefix = os.urandom(NONCE_PREFIX_SIZE)
    header = MAGIC + prefix
    f_out.write(header)

    chunks = iter(chunks)
    current = next(chunks, b"")  # Un archivo vacío produce un único bloque vacío
    index = 0
    while True:
        following = next(chunks, None)
        last = following is None
        nonce = prefix + index.to_bytes(4, "big")
        ciphertext = aes.encrypt(nonce, current, _aad(header, index, last))
        f_out.write(len(ciphertext).to_bytes(4, "big"))
        f_out.write(ciphertext)
        if last:
            return
        current = following
        index += 1


def _decrypt_chunks(path, key):
    with open(path, "rb") as f:
        header = f.read(HEADER_SIZE)
        if len(header) != HEADER_SIZE or not header.startswith(MAGIC):
            raise ValueError("No es un archivo cifrado de VisageVault")
        prefix = header[len(MAGIC):]
        aes = AESGCM(key)

        index = 0
        length = f.read(4)
        while True:
            if len(length) != 4:
                raise ValueError("Archivo cifrado truncado")
            size = int.from_bytes(length, "big")
            ciphertext = f.read(size)
            if len(ciphertext) != size:
                raise ValueError("Archivo cifrado truncado")

            next_length = f.read(4)
            last = not next_length
            nonce = prefix + index.to_bytes(4, "big")
            try:
                yield aes.decrypt(nonce, ciphertext, _aad(header, index, last))
            except InvalidTag:
                raise ValueError("Contraseña incorrecta o archivo dañado") from None

            if last:
                return
            length = next_length
            index += 1


def _plain_chunks(path, key, legacy_key_bytes=None):
    """Bloques en claro de un archivo cifrado, sea del formato actual o legado."""
    if not is_legacy_file(path):
        return _decrypt_chunks(path, key)
    if legacy_key_bytes is None:
        raise ValueError("Archivo en formato antiguo: falta la clave de migración")
    return _legacy_chunks(path, legacy_key_bytes)


class CryptoManager:
    """Operaciones de alto nivel usadas por la aplicación."""

    @staticmethod
    def encrypt_file(input_path, output_path, key):
        """Cifra de disco a disco con el formato actual."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as f_out:
            _encrypt_chunks(_read_chunks(input_path), f_out, key)

    @staticmethod
    def decrypt_file(input_path, output_path, key, legacy_key_bytes=None):
        """Descifra de disco a disco (admite el formato antiguo para restaurar)."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as f_out:
            for chunk in _plain_chunks(input_path, key, legacy_key_bytes):
                f_out.write(chunk)

    @staticmethod
    def decrypt_to_bytes(input_path, key, legacy_key_bytes=None):
        """Descifra a MEMORIA (para previsualización). Devuelve None si falla."""
        if not os.path.exists(input_path):
            return None
        try:
            return b"".join(_plain_chunks(input_path, key, legacy_key_bytes))
        except Exception as e:
            print(f"Error desencriptando visualización: {e}")
            return None

    @staticmethod
    def migrate_legacy_file(path, key, legacy_key_bytes):
        """
        Convierte un archivo del formato antiguo (XOR) al actual, sin escribir
        nunca el contenido en claro a disco. Devuelve True si lo ha migrado.
        """
        if not os.path.exists(path) or not is_legacy_file(path):
            return False
        temp_path = path + ".migrating"
        try:
            with open(temp_path, "wb") as f_out:
                _encrypt_chunks(_legacy_chunks(path, legacy_key_bytes), f_out, key)
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        return True
