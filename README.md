<p align="center">
    <img src="https://raw.githubusercontent.com/anabasasoft/visagevault/master/AnabasaSoft.png" width="600" alt="AnabasaSoft Logo">
  </p>

  <br><br>

<p align="center">
  <img src="https://github.com/anabasasoft/visagevault/raw/master/visagevault.png" alt="Logo de VisageVault">
</p>

# 📸 VisageVault

**VisageVault** es un gestor de fotografías y vídeos inteligente, local, privado y ahora con soporte para **Google Drive**. Organiza tu colección multimedia por fechas automáticamente y utiliza reconocimiento facial avanzado para agrupar a las personas, permitiéndote etiquetar y encontrar recuerdos rápidamente.

---

## ✨ Novedades de la Versión

Esta actualización transforma VisageVault en un gestor híbrido (Local + Nube) y mejora la estructura interna:

* **☁️ Integración con Google Drive:** Nueva pestaña **"Nube"**. Navega por tus copias de seguridad en la nube (incluyendo la sección "Ordenadores" de Google Fotos/Drive) sin descargar todos los archivos.
* **📅 Organización Temporal en la Nube:** Visualiza tus fotos de Drive organizadas automáticamente por **Año y Mes**, igual que en tu disco local.
* **🚀 Caché Unificada e Inteligente:** Nuevo sistema de archivos centralizado en `visagevault_cache`.
    * **Caché de Miniaturas de Drive:** Las miniaturas de la nube se guardan en disco (`drive_snapshot_cache`) para que la carga sea **instantánea** en futuras sesiones y no consuma internet.
    * **Limpieza Automática:** Sistema de auto-reparación de descargas corruptas.
* **🔍 Navegación Mejorada:**
    * **Vista Previa Rápida:** Doble clic para ver fotos (Local y Nube) en pantalla completa.
    * **Cierre Rápido:** Tecla `ESC` para cerrar vistas previas.
    * **Filtro de Carpetas Propias:** Algoritmo inteligente para encontrar tu carpeta "Mi Ordenador" en Drive filtrando carpetas compartidas no deseadas.
* **🖱️ Interacción Unificada:** La selección múltiple, el zoom con `Ctrl`+`Rueda` y la navegación funcionan idéntico en Local y Nube.
* Añadido buscador de fotografías duplicadas
* Añadido caja fuerte
* **🔄 Auto-Refresco (Watchdog):** La aplicación detecta automáticamente si añades, borras 
    o modificas fotos en tu carpeta mientras está abierta y actualiza la galería al instante 
    sin reiniciar.
* **👁️ Corrección de Ojos Rojos:** Nueva herramienta en el menú contextual (clic derecho) 
    para detectar y corregir ojos rojos en tus fotos automáticamente.
* **⚡ Rendimiento en Personas:** Implementado un sistema de **caché de caras en disco**. 
    La primera vez detecta las caras, pero las siguientes veces la carga de la pestaña 
    "Personas" es instantánea, incluso con archivos RAW pesados.
* **Soporte RAW Avanzado:** Visualización, carga de miniaturas y reconocimiento facial en 
    archivos RAW comunes (.NEF, .CR2, .ARW, etc.) gracias a `rawpy`.
* **Gestión de Metadatos Persistente:** Opción de **Cambiar Fecha (Mover)** que guarda el 
  cambio en el archivo físico (EXIF para JPG, fecha de modificación para Vídeos/RAW).
* **Gestión de Visibilidad:** Opción para **Ocultar/Restaurar** archivos de la vista 
  principal y **Eliminar** archivos físicamente del disco.
* **Selección Robusta:** Selección de rango con **Shift + Clic**, selección múltiple con 
    **Ctrl + Clic**, y selección por arrastre.

---

## 📜 Licencia

Este proyecto se ofrece bajo un modelo de **Doble Licencia (Dual License)**:

1.  **LGPLv3:** Ideal para proyectos de código abierto. Si usas esta biblioteca (especialmente 
  si la modificas), debes cumplir con las obligaciones de la LGPLv3.
2.  **Comercial (Privativa):** Si los términos de la LGPLv3 no se ajustan a tus necesidades 
  (por ejemplo, para software propietario de código cerrado), por favor contacta al autor para 
  adquirir una licencia comercial.

Para más detalles, consulta el archivo `LICENSE` o la cabecera de `visagevault.py`.

---

## 🛠️ Requisitos del Sistema

Para ejecutar VisageVault, necesitas **Python 3.11 o superior**.

### Dependencias de Sistema (Compilación)

La librería `face_recognition` y `rawpy` requieren herramientas de compilación de C++ 
  instaladas:

* **Windows:** Visual Studio con "Desarrollo para el escritorio con C++".
* **Linux:** `cmake`, `gcc`, `libarchive-tools` (para empaquetado).
  ```bash
  sudo apt install build-essential cmake libopenblas-dev liblapack-dev ffmpeg libarchive-tools
  ```
* **Mac:** Xcode command line tools.

---

### Librerías Python

Asegúrate de que tu `requirements.txt` esté actualizado. Las dependencias clave son:

  * `PySide6` (Interfaz gráfica)
  * `face_recognition` (IA Facial)
  * `scikit-learn` (Clustering de caras)
  * `watchdog` (Monitorización de archivos)
  * `rawpy` (Soporte RAW)
  * `opencv-python-headless` (Miniaturas de vídeo y Ojos Rojos)
  * `piexif` (Escritura EXIF)
  * **Google API Client** (NUEVO: `google-api-python-client`, `google-auth-oauthlib`)
  * `numpy`, `Pillow`, `requests`

---

## 🚀 Instalación

1.  **Clonar el repositorio:**

    ```bash
    git clone https://github.com/anabasasoft/visagevault.git
    cd visagevault
    ```

2.  **Instalar dependencias:**
    Se recomienda usar un entorno virtual (`venv`).

    ```bash
    pip install -r requirements.txt
    ```

3.  **Configurar Google Drive (Opcional):**
    Para usar la pestaña Nube, necesitarás un archivo `client_secrets.json` en la raíz del proyecto (obtenido de Google Cloud Console).

4.  **Ejecutar la aplicación:**

    ```bash
    python visagevault.py
    ```

### 🔏 Verificar la firma de los paquetes (Linux)

Los paquetes `.deb` y `.rpm` publicados en cada release están firmados con la clave GPG oficial de AnabasaSoft. Para verificarlos antes de instalar:

1. Descarga la clave pública del repositorio ([`firma/anabasasoft_public.asc`](firma/anabasasoft_public.asc)) a un fichero (**no uses `curl | rpm --import -`**, algunas versiones de `rpm` no admiten leer la clave por la entrada estándar y fallan con `falló la lectura para importar`):
   ```bash
   curl -sL https://raw.githubusercontent.com/AnabasaSoft/VisageVault/master/firma/anabasasoft_public.asc -o /tmp/anabasasoft_public.asc
   ```

2. Importa la clave (solo hace falta una vez por equipo):
   ```bash
   # Fedora, openSUSE, RHEL... (paquete .rpm)
   sudo rpm --import /tmp/anabasasoft_public.asc

   # Debian, Ubuntu... (paquete .deb, requiere dpkg-sig)
   gpg --import /tmp/anabasasoft_public.asc
   ```

3. Comprueba que la clave se ha importado correctamente:
   ```bash
   rpm -qa gpg-pubkey* --qf '%{name}-%{version}-%{release} --> %{summary}\n' | grep -i anabasasoft
   ```

4. Verifica la firma del paquete descargado:
   ```bash
   # RPM
   rpm --checksig visagevault-*.rpm

   # DEB
   dpkg-sig --verify visagevault_*.deb
   ```
   Una firma correcta muestra `OK` (o `BIEN` con el sistema en español) en la línea de la firma, en vez de `NOKEY`, `MISSING KEYS` o `NO ESTA BIEN`.

Una firma válida confirma que el paquete procede de AnabasaSoft y no ha sido modificado.

---

## 📖 Guía de Uso Rápida

### Navegación y Vistas

  * **Árbol de Fechas:** Las secciones de **Años/Meses** muestran solo archivos visibles. La sección
    **Ocultas** muestra los archivos que has archivado y permite Restaurarlos o Eliminarlos.
  * **Auto-Refresco:** Si copias fotos nuevas a tu carpeta vigilada, aparecerán automáticamente en la
    aplicación tras unos segundos.
  * **Pestaña Nube:** Inicia sesión con Google para explorar tus copias de seguridad. Usa el botón "Cambiar Carpeta" para seleccionar "Mi Ordenador" u otras carpetas de Drive.

### Menú Contextual (Clic Derecho)

Selecciona uno o varios elementos y haz clic derecho para acceder a las opciones:

| Opción | Función |
| :--- | :--- |
| **Cambiar Fecha (Mover)** | Abre un diálogo para reasignar la fecha. Actualiza la BD y los metadatos del archivo. |
| **Corregir Ojos Rojos** | Detecta y corrige automáticamente los ojos rojos en las fotos seleccionadas. |
| **Ocultar de la vista** | Archiva los archivos en la sección "Ocultas" sin borrarlos del disco. |
| **Restaurar a la galería** | Devuelve los archivos ocultos a la vista principal (Años/Meses). |
| **Eliminar del disco** | Borra permanentemente los archivos del disco duro y de la base de datos. |

### Controles de Miniaturas

| Acción | Comando |
| :--- | :--- |
| **Zoom Miniaturas** | `Ctrl` + `+`/`-` |
| **Vista Previa Grande** | **Doble Clic** |
| **Cerrar Vista Previa** | Tecla `ESC`  |
| **Selección Múltiple** | `Ctrl` + `Clic` |
| **Selección de Rango** | `Shift` + `Clic` |
| **Selección por Arrastre** | Clic izquierdo y arrastrar sobre el fondo gris |

---

## 📬 Contacto y Autor

Este proyecto ha sido desarrollado con ❤️ y mucho café por:

**Daniel Serrano Armenta (AnabasaSoft)**

* 📧 **Email:** [anabasasoft@gmail.com](mailto:anabasasoft@gmail.com)
* 🐙 **GitHub:** [github.com/danitxu79](https://github.com/danitxu79/)
* 🌐 **Portafolio:** [danitxu79.github.io](https://danitxu79.github.io/)

---

*Si encuentras útil este proyecto, ¡no olvides darle una ⭐ en GitHub!*

<div align="center">
  <br/>
  <p><code>>_ sudo buy-me-a-coffee --theme=dark --force</code></p>
  <a href="https://www.buymeacoffee.com/danitxu" target="_blank">
    <img src="https://cdn.buymeacoffee.com/buttons/v2/default-black.png" alt="Buy Me A Coffee" style="height: 50px !important;width: 180px !important; box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;">
  </a>
  <br/>
</div>
