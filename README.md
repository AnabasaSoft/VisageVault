Aquí tienes el archivo `README.md` actualizado para incluir las nuevas funciones de reconocimiento facial y las nuevas dependencias que hemos añadido.

He modificado 3 secciones:

1.  **Características Principales:** Añadidas las funciones de reconocimiento facial.
2.  **Pila Tecnológica:** Añadida la biblioteca `face_recognition`.
3.  **Instalación y Ejecución:** Actualizado el comando `pip install` con las nuevas dependencias.

-----

# VisageVault - Gestor de Fotografías Inteligente

DERECHOS DE AUTOR: © 2025 Daniel Serrano Armenta

VisageVault es una aplicación de escritorio moderna y de alto rendimiento para gestionar grandes colecciones de fotografías. Se centra en una navegación ultrarrápida basada en la **fecha y las personas** de tus fotos, utilizando escaneo asíncrono, una base de datos local y generación de miniaturas en hilos para una experiencia de usuario fluida.

-----

## 🚀 Características Principales

  * **Navegación por Fechas:** Organiza y agrupa automáticamente toda tu biblioteca por **Año** y **Mes**, permitiéndote encontrar recuerdos al instante.
  * **Reconocimiento Facial:** Escanea tus fotos en segundo plano para detectar y recortar caras automáticamente.
  * **Gestión de Personas:** Muestra todas las caras detectadas (en formato circular) en una pestaña dedicada, listas para ser etiquetadas y agrupadas por nombre.
  * **Interfaz Fluida y Asíncrona:** El escaneo de archivos, la detección de caras y la carga de miniaturas se realizan en hilos separados (`QThread`, `QThreadPool`), evitando que la aplicación se congele, incluso con decenas de miles de fotos.
  * **Carga Diferida (Lazy Loading):** Las miniaturas solo se cargan cuando son visibles (o están a punto de serlo), optimizando el uso de memoria y la velocidad de desplazamiento.
  * **Caché de Base de Datos:** Utiliza `SQLite` para almacenar las rutas, las fechas y los datos faciales de todas las fotos. Los escaneos posteriores son casi instantáneos.
  * **Editor de Fechas:** ¿Una foto escaneada o antigua tiene una fecha incorrecta? Puedes editar fácilmente el **Año** y el **Mes** en la base de datos a través del diálogo de detalles, sin modificar el archivo original.
  * **Lector de Metadatos EXIF:** Extrae la fecha de captura (`DateTimeOriginal`) de tus fotos. Si no existe, utiliza la fecha de modificación del archivo como respaldo.
  * **Visor de Detalles Avanzado:**
      * Haz doble clic para abrir una vista de detalle con la imagen en alta resolución.
      * **Zoom interactivo** y arrastre (panning) dentro del visor de detalles.
      * Muestra una **tabla completa con todos los metadatos EXIF** encontrados en el archivo.
  * **Vista Previa Rápida (Quick-Look):** En la vista de miniaturas, mantén pulsado `Ctrl` y usa la **rueda del ratón** para una vista previa ampliada e instantánea de cualquier foto sin necesidad de abrirla.
  * **Caché de Miniaturas:** Genera y guarda las miniaturas en un directorio local (`.visagevault_cache`) para una carga visual instantánea.

## 🔧 Pila Tecnológica (Tech Stack)

  * **Python 3**
  * **PySide6:** Para la interfaz gráfica de usuario (GUI).
  * **SQLite3:** (Módulo nativo de Python) Para la base de datos.
  * **face\_recognition:** Para la detección y el reconocimiento facial (basado en `dlib`).
  * **Pillow (PIL):** Para la lectura de imágenes, recorte de caras y generación de miniaturas.
  * **piexif:** Para la lectura avanzada de metadatos EXIF.

## 📦 Instalación y Ejecución

1.  **Clona el repositorio:**

    ```bash
    git clone https://github.com/danitxu79/VisageVault.git
    cd VisageVault
    ```

2.  **Instala las dependencias:**
    (Se recomienda crear un entorno virtual)

    ```bash
    pip install PySide6 Pillow piexif face_recognition setuptools
    ```

3.  **Ejecuta la aplicación:**

    ```bash
    python visagevault.py
    ```

4.  **Primer Inicio:** La aplicación te pedirá que selecciones el directorio raíz que contiene todas tus fotografías. Comenzará el primer escaneo. El escaneo de caras se iniciará automáticamente la primera vez que visites la pestaña "Personas".

-----

## 📜 Licencia

Este proyecto se ofrece bajo un modelo de licenciamiento dual:

### 1\. Licencia Pública (LGPLv3)

Este software está disponible bajo la **GNU Lesser General Public License v3.0 (LGPLv3)**.

Puedes usarlo libremente de acuerdo con los términos de la LGPLv3, lo cual es ideal para proyectos de código abierto. En resumen, esto significa que si usas esta biblioteca (especialmente si la modificas), debes cumplir con las obligaciones de la LGPLv3, como publicar el código fuente de tus modificaciones a esta biblioteca y permitir que los usuarios la reemplacen.

Puedes encontrar el texto completo de la licencia en el archivo `LICENSE` de este repositorio.

### 2\. Licencia Comercial (Privativa)

Si los términos de la LGPLv3 no se ajustan a tus necesidades, ofrezco una licencia comercial alternativa.

Necesitarás una licencia comercial si, por ejemplo:

  * Deseas incluir el código en un software propietario (código cerrado) sin tener que publicar tus modificaciones.
  * Necesitas enlazar estáticamente (static linking) la biblioteca con tu aplicación propietaria.
  * Prefieres no estar sujeto a las obligaciones y restricciones de la LGPLv3.

La licencia comercial te otorga el derecho a usar el código en tus aplicaciones comerciales de código cerrado sin las restricciones de la LGPLv3, a cambio de una tarifa.

Para adquirir una licencia comercial o para más información, por favor, pónte en contacto conmigo:

  * **Nombre:** Daniel Serrano Armenta
  * **Email:** dani.eus79@gmail.com
  * **GitHub:** [danitxu79](https://github.com/danitxu79)
  * **Portafolio:** [danitxu79.github.io](https://danitxu79.github.io/)
