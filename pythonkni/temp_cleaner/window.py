from __future__ import annotations

import sys as _sys
import types as _types

from PyQt5.QtWidgets import QCheckBox, QMessageBox, QPushButton, QVBoxLayout, QWidget

from tools.base_tool import BaseTool
from tools.ui_feedback import show_error

from . import service as _service
from .models import (
    CleanPreview as CleanPreview,
)
from .models import (
    CleanResult as CleanResult,
)
from .service import (
    CleanTarget as CleanTarget,
)
from .service import (
    _allowed_clean_containers as _allowed_clean_containers,
)
from .service import (
    _allowed_exact_clean_targets as _allowed_exact_clean_targets,
)
from .service import (
    _browser_cache_candidates as _browser_cache_candidates,
)
from .service import (
    _forbidden_clean_roots as _forbidden_clean_roots,
)
from .service import (
    _is_safe_clean_root as _is_safe_clean_root,
)
from .service import (
    _log_candidates as _log_candidates,
)
from .service import (
    _resolve_existing as _resolve_existing,
)
from .service import (
    _resolved_path as _resolved_path,
)
from .service import (
    _temp_candidates as _temp_candidates,
)
from .service import (
    _unique_safe_targets as _unique_safe_targets,
)
from .service import (
    build_preview as build_preview,
)
from .service import (
    clean_browser_cache as clean_browser_cache,
)
from .service import (
    clean_logs as clean_logs,
)
from .service import (
    clean_targets as clean_targets,
)
from .service import (
    clean_temp as clean_temp,
)
from .service import (
    delete_folder_contents as delete_folder_contents,
)
from .service import (
    get_browser_cache_targets as get_browser_cache_targets,
)
from .service import (
    get_log_targets as get_log_targets,
)
from .service import (
    get_temp_targets as get_temp_targets,
)
from .service import (
    logger as logger,
)


class Tool(BaseTool):
    name = "Limpieza de Temporales"
    description = "Analiza y limpia ubicaciones temporales autorizadas."
    category = "Sistema"

    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 400, 300)

        layout = QVBoxLayout()

        self.chk_temp = QCheckBox("Archivos temporales seguros")
        self.chk_temp.setChecked(True)
        layout.addWidget(self.chk_temp)

        self.chk_cache = QCheckBox("Cache de navegadores (Chrome, Edge, Firefox)")
        layout.addWidget(self.chk_cache)

        self.chk_logs = QCheckBox("Temporales de Windows")
        layout.addWidget(self.chk_logs)

        btn_clean = QPushButton("Vista previa y limpieza")
        btn_clean.clicked.connect(self.clean_action)
        layout.addWidget(btn_clean)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def clean_action(self):
        try:
            targets = []

            if self.chk_temp.isChecked():
                targets.extend(get_temp_targets())
            if self.chk_cache.isChecked():
                targets.extend(get_browser_cache_targets())
            if self.chk_logs.isChecked():
                targets.extend(get_log_targets())

            preview = build_preview(targets)
        except Exception as error:
            show_error(
                self,
                "Vista previa de limpieza",
                "No se pudo preparar la vista previa de limpieza.",
                error=error,
            )
            return

        if not preview.targets:
            QMessageBox.information(
                self,
                "Sin rutas seguras",
                "No hay rutas de limpieza seguras para las opciones seleccionadas.",
            )
            return

        detail = "\n".join(f"- {target.label}: {target.path}" for target in preview.targets)
        size_mb = preview.bytes / (1024 * 1024)
        confirm = QMessageBox.question(
            self,
            "Confirmar limpieza",
            "Vista previa de limpieza:\n"
            f"{detail}\n\n"
            f"Elementos detectados: {preview.items}\n"
            f"Tamano aproximado: {size_mb:.2f} MB\n\n"
            "Deseas borrar el contenido de estas rutas?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            QMessageBox.information(
                self, "Simulacion completada", "No se ha borrado ningun archivo."
            )
            return

        try:
            result = clean_targets(preview.targets)
        except Exception as error:
            show_error(
                self,
                "Limpieza de temporales",
                "No se pudo completar la limpieza de temporales.",
                error=error,
            )
            return

        QMessageBox.information(
            self,
            "Limpieza completada",
            f"Se han eliminado {result.deleted} archivos/carpetas temporales.\n"
            f"No se pudieron eliminar {result.failed} elementos.",
        )


class _CompatibilityModule(_types.ModuleType):
    """Forward legacy monkeypatches to the separated service module."""

    def __setattr__(self, name, value):
        if hasattr(_service, name):
            setattr(_service, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if hasattr(_service, name):
            delattr(_service, name)
        super().__delattr__(name)


_sys.modules[__name__].__class__ = _CompatibilityModule
