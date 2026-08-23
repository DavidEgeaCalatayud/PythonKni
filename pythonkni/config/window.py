from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from tools.language_manager import LanguageManager
from tools.theme_manager import ThemeManager
from tools.base_tool import BaseTool
import logging
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from tools.app_paths import CONFIG_FILE
from .models import (
    DEFAULT_CONFIG,
    LEGACY_LANGUAGES,
    VALID_LANGUAGES,
    VALID_THEMES,
)
from .service import (
    apply_runtime_config,
    load_config,
    load_runtime_config,
    logger,
    normalize_config,
    save_config,
    save_runtime_config,
)
from . import service as _service
import sys as _sys
import types as _types


class Tool(BaseTool):
    name = "Configuracion"
    description = "Configura el tema y el idioma de la aplicación."
    category = "Configuración"

    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(100, 100, 400, 300)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        self.theme_label = QLabel()
        layout.addWidget(self.theme_label)

        self.theme_combobox = QComboBox()
        self.theme_combobox.addItems(["Claro", "Oscuro"])
        layout.addWidget(self.theme_combobox)

        self.language_label = QLabel()
        layout.addWidget(self.language_label)

        self.language_combobox = QComboBox()
        self.language_combobox.addItems(["Español", "Inglés"])
        layout.addWidget(self.language_combobox)

        self.save_button = QPushButton()
        self.save_button.clicked.connect(self.save_changes)
        layout.addWidget(self.save_button)

        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.close_button)

        self.load_config()

    def refresh_language_texts(self):
        self.theme_label.setText(LanguageManager.translate("Seleccionar Tema:"))
        self.language_label.setText(LanguageManager.translate("Seleccionar Idioma:"))
        self.save_button.setText(LanguageManager.translate("Guardar cambios"))
        self.close_button.setText(LanguageManager.translate("Cerrar"))

    def save_changes(self):
        try:
            config = save_runtime_config(
                CONFIG_FILE,
                {
                    "theme": self.theme_combobox.currentText(),
                    "language": self.language_combobox.currentText(),
                },
            )
        except (OSError, ValueError, TypeError) as error:
            logger.exception("Could not save config file: %s", CONFIG_FILE)
            QMessageBox.critical(
                self,
                "Error al guardar",
                f"No se pudo guardar la configuración. No se han aplicado los cambios.\n\n{error}",
            )
            return

        self.theme_combobox.setCurrentText(config["theme"])
        self.language_combobox.setCurrentText(config["language"])

        app = QApplication.instance()
        if app is not None:
            ThemeManager.apply_theme(app)
            for widget in app.topLevelWidgets():
                widget.update()

        self.refresh_language_texts()

        QMessageBox.information(
            self,
            "Exito",
            LanguageManager.translate("Cambios guardados"),
        )

    def load_config(self):
        try:
            config = load_config(CONFIG_FILE)
        except (OSError, ValueError):
            logger.exception("Invalid config file: %s", CONFIG_FILE)
            QMessageBox.warning(
                self,
                "Configuracion",
                "El archivo de configuracion no es valido.",
            )
            config = {
                "theme": ThemeManager.get_theme(),
                "language": LanguageManager.get_language(),
            }

        apply_runtime_config(config)
        self.theme_combobox.setCurrentText(config["theme"])
        self.language_combobox.setCurrentText(config["language"])
        self.refresh_language_texts()


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
