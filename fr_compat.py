# fr_compat.py
"""
face_recognition_models (los modelos de face_recognition) localiza sus ficheros
con pkg_resources.resource_filename. setuptools 81 eliminó pkg_resources, y
entonces face_recognition dice "Please install `face_recognition_models`" y
cierra el programa aunque el paquete esté instalado.

Si pkg_resources no está, se registra uno mínimo con solo esa función, que es
lo único que usa. Hay que importar este módulo antes que face_recognition.
"""
import os
import sys
import types

try:
    import pkg_resources  # noqa: F401  (setuptools < 81)
except ImportError:
    def resource_filename(package, resource):
        """Ruta de resource dentro del paquete (también en el ejecutable de PyInstaller)."""
        module = sys.modules.get(package) or __import__(package)
        return os.path.join(os.path.dirname(module.__file__), resource)

    _shim = types.ModuleType("pkg_resources")
    _shim.resource_filename = resource_filename
    sys.modules["pkg_resources"] = _shim
