import logging

from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tools.app_paths import CONFIG_FILE
from tools.config_service import load_config, save_config
from tools.language_manager import LanguageManager
from tools.runtime_config import apply_runtime_config
from tools.theme_manager import ThemeManager


logger = logging.getLogger(__name__)


class Tool(QMainWindow):
    name = "Configuracion"

    def __init__(self):
        super().__init__()
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
        selected_theme = self.theme_combobox.currentText()
        selected_language = self.language_combobox.currentText()

        config = {
            "theme": selected_theme,
            "language": selected_language,
        }
        apply_runtime_config(config)

        app = QApplication.instance()
        if app is not None:
            ThemeManager.apply_theme(app)
            for widget in app.topLevelWidgets():
                widget.update()

        self.refresh_language_texts()
        save_config(CONFIG_FILE, config)

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
