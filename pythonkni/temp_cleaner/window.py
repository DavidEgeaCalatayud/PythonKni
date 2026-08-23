from __future__ import annotations
from tools.base_tool import BaseTool
import logging
import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from PyQt5.QtWidgets import QCheckBox, QMessageBox, QPushButton, QVBoxLayout, QWidget
from .models import (
    CleanPreview,
    CleanResult,
)
from .service import (
    CleanTarget,
    _allowed_clean_containers,
    _allowed_exact_clean_targets,
    _browser_cache_candidates,
    _forbidden_clean_roots,
    _is_safe_clean_root,
    _log_candidates,
    _resolve_existing,
    _resolved_path,
    _temp_candidates,
    _unique_safe_targets,
    build_preview,
    clean_browser_cache,
    clean_logs,
    clean_targets,
    clean_temp,
    delete_folder_contents,
    get_browser_cache_targets,
    get_log_targets,
    get_temp_targets,
    logger,
)
from . import service as _service
import sys as _sys
import types as _types

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
        targets = []

        if self.chk_temp.isChecked():
            targets.extend(get_temp_targets())
        if self.chk_cache.isChecked():
            targets.extend(get_browser_cache_targets())
        if self.chk_logs.isChecked():
            targets.extend(get_log_targets())

        preview = build_preview(targets)
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

        result = clean_targets(preview.targets)

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
