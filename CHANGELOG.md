# Changelog

## Unreleased

### Added

- **Disk Analyzer** (`disk_analyzer_tool.py`): escanea carpetas recursivamente y lista archivos y subcarpetas con sus tamaños. Permite identificar los elementos más grandes y exportar los resultados a CSV.
- **Startup Manager** (`startup_manager_tool.py`): lee entradas de inicio de Windows desde el registro (`HKCU\Run`, `HKLM\Run`), permite activar, desactivar y eliminar programas de inicio, añadir nuevas entradas y exportar la lista como CSV o JSON.
- **System Report** (`system_report_tool.py`): genera un informe técnico completo del equipo local con CPU, RAM, disco, GPU, sistema operativo, adaptadores de red y procesos activos. Exporta el informe en HTML, PDF y CSV.
- **Windows Event Viewer** (`event_viewer_tool.py`): lee eventos reales de los registros `Application`, `System` y `Security`. Clasifica cada evento por nivel de riesgo (Alto / Medio / Bajo / Normal) con colores visuales, añade interpretaciones legibles para IDs comunes, incluye búsqueda por texto libre, filtros por nivel y riesgo, cancelación de lecturas largas, resumen ejecutivo y exportación a CSV, HTML y PDF.

### Changed

- Se separan configuracion, historial y logs del directorio del proyecto.
- Se elimina la clave de VirusTotal del codigo fuente.
- Se documentan instalacion, build, OCR y seguridad.
- Se corrige el nombre de `requirements.txt` y se completan dependencias OCR.
