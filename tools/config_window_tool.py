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

        layout.addWidget(QLabel(LanguageManager.translate("Seleccionar Tema:")))
        self.theme_combobox = QComboBox()
        self.theme_combobox.addItems(["Claro", "Oscuro"])
        self.theme_combobox.setCurrentText(ThemeManager.get_theme())
        layout.addWidget(self.theme_combobox)

        layout.addWidget(QLabel(LanguageManager.translate("Seleccionar Idioma:")))
        self.language_combobox = QComboBox()
        self.language_combobox.addItems(["Español", "Ingles"])
        layout.addWidget(self.language_combobox)

        save_button = QPushButton(LanguageManager.translate("Guardar cambios"))
        save_button.clicked.connect(self.save_changes)
        layout.addWidget(save_button)

        close_button = QPushButton(LanguageManager.translate("Cerrar"))
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)

        self.load_config()

    def save_changes(self):
        selected_theme = self.theme_combobox.currentText()
        selected_language = self.language_combobox.currentText()

        ThemeManager.set_theme(selected_theme)

        app = QApplication.instance()
        if app is not None:
            ThemeManager.apply_theme(app)
            for widget in app.topLevelWidgets():
                widget.update()

        save_config(
            CONFIG_FILE,
            {
                "theme": selected_theme,
                "language": selected_language,
            },
        )

        QMessageBox.information(self, "Exito", "Cambios guardados correctamente.")

    def load_config(self):
        try:
            config = load_config(CONFIG_FILE)
        except ValueError:
            logger.exception("Invalid config file: %s", CONFIG_FILE)
            QMessageBox.warning(self, "Configuracion", "El archivo de configuracion no es valido.")
            return

        theme = config.get("theme", "Claro")
        language = config.get("language", "Español")

        self.theme_combobox.setCurrentText(theme)
        self.language_combobox.setCurrentText(language)
        ThemeManager.set_theme(theme)
