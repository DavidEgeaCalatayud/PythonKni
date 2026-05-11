# PythonKni

Aplicacion de escritorio desarrollada en Python y PyQt5 que agrupa herramientas de mantenimiento, analisis y conversion de archivos.

## Funcionalidades

- Gestion de archivos ZIP/7Z.
- Conversion de imagenes, PDF, DOCX, TXT y KML.
- Busqueda de duplicados.
- Escaneo de red y puertos.
- Gestion de procesos.
- Limpieza de temporales.
- Listado de perfiles WiFi guardados.
- Herramientas PDF: unir, dividir, extraer texto, extraer paginas y OCR.

## Tecnologias

- Python
- PyQt5
- PyInstaller
- PyPDF2
- PyMuPDF
- ReportLab
- Pillow
- psutil
- py7zr
- pytesseract
- pdf2image

## Instalacion

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## Configuracion

PythonKni guarda configuracion, historial y logs fuera del repositorio, en una carpeta de usuario:

```text
%LOCALAPPDATA%\PythonKni\
```

Para usar el analisis de VirusTotal, crea una variable de entorno:

```powershell
$env:VIRUSTOTAL_API_KEY="your_api_key_here"
```

No subas nunca un archivo `.env` real ni claves API al repositorio.

## OCR

Las funciones OCR necesitan dependencias externas del sistema ademas de las dependencias de Python:

- Tesseract OCR
- Poppler

Asegurate de que ambos ejecutables esten disponibles en el `PATH`.

## Build

```powershell
pyinstaller PythonKni.spec
```

El archivo `PythonKni.spec` se mantiene versionado para documentar el build. La carpeta `dist/` es un artefacto generado y no debe subirse.

## Calidad

```powershell
python -m compileall .
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

El workflow de CI ejecuta estas comprobaciones en cada `push` y `pull_request`.

## Seguridad

Algunas herramientas interactuan con procesos, red, perfiles WiFi locales y archivos del sistema. Usalas solo en equipos propios o con autorizacion.

Si alguna vez se subio una clave API al repositorio, revocala en el proveedor, genera una nueva y configura la nueva clave mediante variable de entorno.
