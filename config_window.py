import json
from PyQt5.QtWidgets import QMainWindow, QVBoxLayout, QLabel, QPushButton, QComboBox, QWidget, QApplication
from theme_manager import ThemeManager
from language_manager import LanguageManager


CONFIG_FILE = "config.json"

class ConfigWindow(QMainWindow):
    """Ventana de configuración principal."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración")
        self.setGeometry(100, 100, 400, 300)

        # Contenedor principal
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Configuración de temas
        layout.addWidget(QLabel(LanguageManager.translate("Seleccionar Tema:")))
        self.theme_combobox = QComboBox()
        self.theme_combobox.addItems(["Claro", "Oscuro"])
        self.theme_combobox.setCurrentText(ThemeManager.get_theme())
        layout.addWidget(self.theme_combobox)

        # Configuración de idiomas
        layout.addWidget(QLabel("Seleccionar Idioma:"))
        self.language_combobox = QComboBox()
        self.language_combobox.addItems(["Español", "Inglés"])
        layout.addWidget(self.language_combobox)

        # Botón para guardar cambios
        save_button = QPushButton("Guardar cambios")
        save_button.setText(LanguageManager.translate("Guardar cambios"))
        save_button.clicked.connect(self.save_changes)
        layout.addWidget(save_button)

        # Botón para cerrar la ventana
        close_button = QPushButton("Cerrar")
        close_button.setText(LanguageManager.translate("Cerrar"))
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)

        # Cargar configuraciones existentes
        self.load_config()

    def save_changes(self):
        """Guarda las configuraciones y actualiza el tema e idioma."""
        # Guardar el tema seleccionado
        selected_theme = self.theme_combobox.currentText()
        ThemeManager.set_theme(selected_theme)

        # Aplicar tema global
        app = QApplication.instance()
        if app is not None:
            ThemeManager.apply_theme(app)

        for widget in app.topLevelWidgets():
            widget.update()

        # Guardar idioma seleccionado
        selected_language = self.language_combobox.currentText()

        # Guardar configuración en un archivo
        config = {
            "theme": selected_theme,
            "language": selected_language
        }
        with open(CONFIG_FILE, "w") as file:
            json.dump(config, file)

        self.statusBar().showMessage("Cambios guardados", 3000)

    def load_config(self):
        """Carga las configuraciones desde un archivo JSON, si existe."""
        try:
            with open(CONFIG_FILE, "r") as file:
                config = json.load(file)
                theme = config.get("theme", "Claro")  # Valor predeterminado
                language = config.get("language", "Español")  # Valor predeterminado

                self.theme_combobox.setCurrentText(theme)
                self.language_combobox.setCurrentText(language)

                ThemeManager.set_theme(theme)
        except FileNotFoundError:
            pass  # Si el archivo no existe, se usan los valores predeterminados

