import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QPushButton, QFileDialog, QMessageBox, QInputDialog
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from wifi_handler import WifiWindow
from networkScanner_handler import MainWindow
from config_window import ConfigWindow
from theme_manager import ThemeManager

class MenuWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Multipurpose Knife")
        self.setGeometry(100, 100, 800, 600)

        # Fondo oscuro y estilo elegante
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #1e1e1e;
            }
            QPushButton {
                background-color: #2b2b2b;
                color: white;
                font-size: 18px;
                font-weight: bold;
                border-radius: 10px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
            }
            QLabel {
                color: white;
                font-size: 24px;
                font-weight: bold;
            }
            QInputDialog {
                color: black;
                font-weigth: bold;
            }
            QMessageBox{
                color:black;
            }
            """
        )

        # Layout principal
        layout = QVBoxLayout()

        # Título
        title = QLabel("Multipurpose Knife")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 16))
        layout.addWidget(title)

        # Botón para listado WiFi
        wifi_button = QPushButton("Listado WiFi + Claves")
        wifi_button.clicked.connect(self.open_wifi_window)
        layout.addWidget(wifi_button)

        # Botón para abrir el explorador de red
        self.network_button = QPushButton("Explorar Red")
        self.network_button.clicked.connect(self.open_network_scanner)
        layout.addWidget(self.network_button)

        # Botón para abrir la configuración
        self.config_button = QPushButton("Configuración")
        self.config_button.clicked.connect(self.open_config_window)
        layout.addWidget(self.config_button)

        # Contenedor
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def open_wifi_window(self):
        self.wifi_window = WifiWindow()
        self.wifi_window.show()
        #def open_wifi_window(self):

    def open_network_scanner(self):
        self.network_scanner = MainWindow()
        self.network_scanner.show()

    def open_config_window(self):
        """Abre la ventana de configuración."""
        self.config_window = ConfigWindow(self)
        self.config_window.show()    
            
if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Aplicar tema inicial desde el gestor
    ThemeManager.apply_theme(app)
    menu = MenuWindow()
    menu.show()
    sys.exit(app.exec_())
