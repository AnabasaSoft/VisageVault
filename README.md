<p align="center">
    <img src="https://raw.githubusercontent.com/AnabasaSoft/VisageVault/master/AnabasaSoft.png" width="600" alt="AnabasaSoft Logo">
  </p>

  <br><br>

<p align="center">
  <img src="https://raw.githubusercontent.com/AnabasaSoft/VisageVault/master/visagevault.png" alt="Logo de VisageVault">
</p>

# 📸 VisageVault

**VisageVault** es un gestor de fotografías y vídeos inteligente, local y privado, con soporte para **Google Drive**. Organiza tu colección multimedia por fechas automáticamente y utiliza reconocimiento facial para agrupar a las personas, permitiéndote etiquetar y encontrar recuerdos rápidamente.

Todo el análisis (caras, fechas, duplicados) se hace **en tu ordenador**: tus fotos nunca se suben a ningún servidor.

---

## ✨ Características

* **📅 Organización automática por fechas:** Fotos y vídeos agrupados por **Año y Mes**, a partir del nombre del archivo o de su fecha. Los archivos sin fecha aparecen en su propio grupo al final.
* **👥 Reconocimiento facial:** Detecta las caras de tus fotos, agrupa las que se parecen y te permite etiquetar a cada persona para ver todas sus fotos.
* **🔒 Caja fuerte cifrada:** Guarda fotos y vídeos privados cifrados con **AES-256-GCM** y protegidos por contraseña. Se ven sin descifrarlos en el disco.
* **☁️ Google Drive:** Pestaña **"Nube"** para explorar tus copias de seguridad (incluida la sección "Ordenadores") organizadas por fecha, sin descargar todos los archivos. El acceso es de **solo lectura**: VisageVault nunca modifica ni borra nada en tu Drive.
* **🔍 Buscador de duplicados:** Encuentra la misma foto guardada varias veces, aunque tenga otra resolución, compresión u orientación, y te deja elegir cuál conservar.
* **🎞️ Soporte RAW:** Visualización, miniaturas y reconocimiento facial en archivos RAW (.NEF, .CR2, .CR3, .ARW, .DNG, .ORF, .RW2, .RAF…) gracias a `rawpy`.
* **👁️ Corrección de ojos rojos:** Detecta los ojos con el reconocimiento facial y conserva intactos el EXIF, la orientación, la calidad y las fechas del archivo.
* **📝 Cambio de fecha:** Mueve fotos y vídeos a otra fecha; se guarda en la base de datos y en el propio archivo (EXIF en JPG, fecha de modificación en vídeos y RAW).
* **🗑️ Papelera:** Lo que eliminas va a la papelera del sistema y se puede recuperar.
* **🔄 Auto-refresco:** Detecta las fotos y vídeos que añades, borras o renombras en tu carpeta y actualiza la galería sin reiniciar.
* **🛡️ Protección de la biblioteca:** Si desconectas el disco o el NAS, no se pierde nada; si la base de datos se daña, se repara sola restaurando tus fechas y archivos ocultos.
* **🔔 Actualizaciones:** Avisa cuando hay una versión nueva (se puede desactivar en la Ayuda).

> Consulta los cambios de cada versión en la página de [Releases](https://github.com/AnabasaSoft/VisageVault/releases).

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

## 📥 Descarga e Instalación

Descarga el paquete de tu sistema desde la [última release](https://github.com/AnabasaSoft/VisageVault/releases/latest):

| Sistema | Archivo | Instalación |
| :--- | :--- | :--- |
| **Linux (cualquier distribución)** | `VisageVault-*.AppImage` | `chmod +x VisageVault-*.AppImage && ./VisageVault-*.AppImage` |
| **Debian, Ubuntu, Linux Mint…** | `visagevault_*_amd64.deb` | `sudo apt install ./visagevault_*_amd64.deb` |
| **Fedora, RHEL, Rocky Linux, AlmaLinux…** | `visagevault-*.x86_64.rpm` | `sudo dnf install ./visagevault-*.x86_64.rpm` |
| **openSUSE (Tumbleweed y Leap)** | `visagevault-*.x86_64.rpm` | `sudo zypper install ./visagevault-*.x86_64.rpm` |
| **Arch Linux / Manjaro** | AUR: [`visagevault`](https://aur.archlinux.org/packages/visagevault) | `yay -S visagevault` o `paru -S visagevault` |
| **Windows** | `VisageVault.exe` | Ejecutable directo, no requiere instalación. |
| **macOS** | `VisageVault-macOS.dmg` | Abre el `.dmg` y arrastra VisageVault a Aplicaciones. |

Los paquetes `.deb` y `.rpm` instalan la aplicación en `/opt/visagevault` y añaden el comando `visagevault` y su entrada en el menú de aplicaciones.

> En **openSUSE** y **Fedora**, importa antes la clave pública (paso 2 de la sección siguiente): así `zypper` y `dnf` comprueban la firma del paquete al instalarlo y no muestran el aviso de clave desconocida.

### 🔏 Verificar la firma de los paquetes (Linux)

Los paquetes `.deb` y `.rpm` publicados en cada release están firmados con la clave GPG oficial de AnabasaSoft (huella `11C7 C6C8 127D FE48 33DE  30EF 9D7A AEC8 1842 C199`). Para verificarlos antes de instalar:

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
   rpm -qa 'gpg-pubkey*' --qf '%{name}-%{version}-%{release} --> %{summary}\n' | grep -i anabasasoft
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

### 💾 Dónde se guardan tus datos

La base de datos, la configuración, la caja fuerte y las cachés se guardan en las carpetas estándar de cada sistema. Haz copia de seguridad de la carpeta de **datos** para conservar tus fechas, personas y caja fuerte.

| Sistema | Datos (base de datos, caja fuerte) | Configuración | Caché (miniaturas, caras) |
| :--- | :--- | :--- | :--- |
| **Linux** | `~/.local/share/visagevault` | `~/.config/visagevault` | `~/.cache/visagevault` |
| **Windows** | `%APPDATA%\VisageVault` | `%APPDATA%\VisageVault` | `%LOCALAPPDATA%\VisageVault\Cache` |
| **macOS** | `~/Library/Application Support/VisageVault` | ídem | `~/Library/Caches/VisageVault` |

Si ejecutas VisageVault desde el código fuente en una carpeta con permisos de escritura, todo se guarda junto al programa (modo portable).

---

## 🛠️ Ejecutar desde el Código Fuente

Necesitas **Python 3.11 o superior**.

### Dependencias de Sistema (Compilación)

Las librerías `face_recognition` (`dlib`) y `rawpy` requieren herramientas de compilación de C++:

* **Windows:** Visual Studio con "Desarrollo para el escritorio con C++".
* **Linux:**
  ```bash
  sudo apt install build-essential cmake libopenblas-dev liblapack-dev ffmpeg
  ```
* **Mac:** Xcode command line tools.

### Librerías Python

Todas están en `requirements.txt`. Las principales son:

  * `PySide6` (interfaz gráfica)
  * `face_recognition` (reconocimiento facial) y `scikit-learn` (agrupación de caras)
  * `rawpy` (soporte RAW), `opencv-python-headless` (miniaturas de vídeo y ojos rojos), `Pillow`, `piexif`, `numpy`
  * `cryptography` (cifrado de la caja fuerte)
  * `watchdog` (vigilancia de la carpeta) y `Send2Trash` (papelera)
  * `google-api-python-client`, `google-auth`, `google-auth-oauthlib` y `requests` (Google Drive)

### Instalación

1.  **Clonar el repositorio:**

    ```bash
    git clone https://github.com/AnabasaSoft/VisageVault.git
    cd VisageVault
    ```

2.  **Instalar dependencias** (se recomienda un entorno virtual, `venv`):

    ```bash
    pip install -r requirements.txt
    ```

3.  **Ejecutar la aplicación:**

    ```bash
    python visagevault.py
    ```

Ejecutada desde el código fuente, la aplicación se identifica como versión `dev` y no busca actualizaciones.

> **Google Drive (opcional):** las versiones publicadas ya incluyen las credenciales de la aplicación. Desde el código fuente, la pestaña Nube necesita unas propias: crea un cliente OAuth de tipo **"Aplicación de escritorio"** en Google Cloud Console (con la API de Google Drive activada), descarga su JSON y guárdalo como `client_secrets.json` junto a `visagevault.py` (git lo ignora). Sin él, Google responde `Error 401: invalid_client`.

---

## 📖 Guía de Uso Rápida

### Navegación y Vistas

  * **Árbol de Fechas:** Las secciones de **Años/Meses** muestran solo archivos visibles. La sección
    **Ocultas** muestra los archivos que has archivado y permite restaurarlos o enviarlos a la papelera.
  * **Árbol de Directorios:** El botón **"Ver árbol de directorios"** filtra la galería por carpeta.
  * **Auto-Refresco:** Si copias fotos nuevas a tu carpeta, aparecerán automáticamente en la
    aplicación tras unos segundos.
  * **Pestaña Nube:** Inicia sesión con Google para explorar tus copias de seguridad. Usa el botón "Cambiar Carpeta" para seleccionar "Mi Ordenador" u otras carpetas de Drive.

### Menú Contextual (Clic Derecho)

Selecciona uno o varios elementos y haz clic derecho para acceder a las opciones:

| Opción | Función |
| :--- | :--- |
| **Cambiar Fecha (Mover)** | Abre un diálogo para reasignar la fecha. Actualiza la BD y los metadatos del archivo. |
| **Corregir Ojos Rojos** | Detecta y corrige automáticamente los ojos rojos en las fotos seleccionadas (modifica el archivo original). |
| **🔒 Añadir a Caja Fuerte** | Cifra los archivos, los guarda en la caja fuerte y los quita de la galería. |
| **Ocultar de la vista** | Archiva los archivos en la sección "Ocultas" sin borrarlos del disco. |
| **Restaurar a la galería** | Devuelve los archivos ocultos a la vista principal (Años/Meses). |
| **Mover a la papelera** | Envía los archivos a la papelera del sistema (se pueden recuperar desde ella). |

### Personas

  * Las caras se detectan solas en segundo plano a medida que se indexan las fotos.
  * **Haz clic en una cara** para asignarla a una persona existente o crear una nueva.
  * **"Agrupar caras parecidas"** reúne las caras sin asignar que se parecen para etiquetarlas de una vez.
  * Con **clic derecho** puedes eliminar una cara mal detectada; las eliminadas se recuperan desde **"Caras Eliminadas"**.

### Caja Fuerte

  * La primera vez que añades un archivo te pide crear una **contraseña**. **No se puede recuperar**: si la olvidas, el contenido de la caja fuerte se pierde.
  * En la pestaña **"Caja Fuerte"**, pulsa **"Desbloquear"** para ver su contenido y **"Bloquear"** al terminar.
  * Con **clic derecho → "Restaurar a Galería"** el archivo vuelve a su ubicación original con su fecha.
  * Los vídeos de la caja fuerte se muestran con su miniatura; para reproducirlos hay que restaurarlos.

### Duplicados

  * En la pestaña **Fotos**, el botón **"Buscar Duplicados"** compara visualmente todas las fotos y muestra los grupos de copias con su resolución y tamaño, para que envíes a la papelera las que sobran.

### Controles

| Acción | Comando |
| :--- | :--- |
| **Zoom de Miniaturas** | `Ctrl` + `+`/`-` |
| **Ver Foto / Reproducir Vídeo** | **Doble Clic** |
| **Zoom en el Visor** | Rueda del ratón (doble clic para ajustar a la ventana) |
| **Mover la Foto Ampliada** | Arrastrar con el ratón |
| **Cerrar el Visor** | Tecla `ESC` o clic fuera de la foto |
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
* 🐛 **Errores y sugerencias:** [github.com/AnabasaSoft/VisageVault/issues](https://github.com/AnabasaSoft/VisageVault/issues)

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
