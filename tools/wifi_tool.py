# tools/wifi_tool.py
import subprocess
from PyQt5.QtWidgets import QMainWindow, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget


def get_wifi_profiles():
    """Obtiene las redes WiFi guardadas en Windows junto con sus contraseñas."""
    try:
        output = subprocess.check_output("netsh wlan show profile", shell=True, text=True)
        profiles = [
            line.split(":")[1].strip() for line in output.splitlines() if "All User Profile" in line
        ]
        wifi_data = []
        for profile in profiles:
            try:
                details = subprocess.check_output(
                    f'netsh wlan show profile "{profile}" key=clear', shell=True, text=True
                )
                key_line = [line for line in details.splitlines() if "Key Content" in line]
                password = key_line[0].split(":")[1].strip() if key_line else "No Password"
                wifi_data.append((profile, password))
            except subprocess.CalledProcessError:
                wifi_data.append((profile, "Error retrieving"))
        return wifi_data
    except Exception as e:
        return [("Error", str(e))]


class Tool(QMainWindow):
    name = "Listado WiFi + Claves"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.name)
        self.setGeometry(100, 100, 800, 600)

        # Estilo oscuro
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QTableWidget {
                background-color: #2b2b2b;
                color: white;
                font-size: 14px;
                gridline-color: #444;
                border: 1px solid #444;
            }
            QTableWidget QHeaderView::section {
                background-color: #3d3d3d;
                color: white;
                font-size: 16px;
                font-weight: bold;
                border: 1px solid #444;
            }
        """)

        # Tabla
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["WiFi Name", "Password"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        # Layout
        layout = QVBoxLayout()
        layout.addWidget(self.table)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # Cargar datos
        self.show_wifi_data()

    def show_wifi_data(self):
        """Muestra los perfiles WiFi en la tabla."""
        data = get_wifi_profiles()
        self.table.setRowCount(len(data))
        for row, (name, password) in enumerate(data):
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(password))
