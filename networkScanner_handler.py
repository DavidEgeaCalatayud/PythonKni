import socket
import subprocess
import threading
import sys
import os
import json
import csv
from PyQt5.QtWidgets import (
    QApplication, QVBoxLayout, QLabel, QPushButton, QTextEdit, QWidget, QTabWidget, QMainWindow, QLineEdit, QHBoxLayout, QFileDialog, QComboBox, QCheckBox, QSpinBox
)

class NetworkScanner(QWidget):
    def __init__(self, history_tab):
        super().__init__()
        self.history_tab = history_tab  # Referencia de HistoryTab para guardar el registro
        self.stop_scanning = False  # Variable para detener el escaneo

        # Fondo oscuro y estilo elegante
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #1e1e1e;
            }
            QTextEdit {
                background-color: #2b2b2b;
                color: white;
                font-size: 14px;
                border: 1px solid #444;
            }
            QPushButton {
                background-color: #2b2b2b;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border-radius: 10px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
            }
            QLabel {
                color: black;
                font-size: 14px;
            }
            """
        )

        # Diseño de la interfaz
        layout = QVBoxLayout()

        self.info_label = QLabel("Haz clic en 'Explorar red' para detectar dispositivos conectados.")
        layout.addWidget(self.info_label)

        self.result_area = QTextEdit()
        self.result_area.setReadOnly(True)
        layout.addWidget(self.result_area)

        self.scan_button = QPushButton("Explorar red")
        self.scan_button.clicked.connect(self.scan_network)
        layout.addWidget(self.scan_button)

        self.stop_button = QPushButton("Detener escaneo")
        self.stop_button.clicked.connect(self.stop_scan)
        layout.addWidget(self.stop_button)

        self.setLayout(layout)

    def scan_network(self):
        self.result_area.clear()
        self.result_area.append("Escaneando la red...\n")
        self.stop_scanning = False
        threading.Thread(target=self.perform_scan).start()

    def stop_scan(self):
        self.stop_scanning = True
        self.result_area.append("Escaneo detenido por el usuario.\n")

    def perform_scan(self):
        # Obtener la IP de la red local
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        self.result_area.append(f"Dirección IP local: {local_ip}\n")

        # Determinar el rango de IP a escanear (por ejemplo, 192.168.1.0/24)
        network_base = '.'.join(local_ip.split('.')[:-1])
        self.result_area.append(f"Escaneando en: {network_base}.x\n")

        dispositivos_encontrados = []  # Almacena información de dispositivos encontrados

        for i in range(1, 255):
            if self.stop_scanning:
                self.result_area.append("Escaneo detenido por el usuario.\n")
                break

            ip = f"{network_base}.{i}"
            try:
                # Hacer ping al dispositivo
                output = subprocess.run(
                    ["ping", "-n", "1", ip], capture_output=True, text=True, timeout=1
                )
                if "Tiempo" in output.stdout or "time" in output.stdout:
                    # Resolver nombre de host
                    try:
                        hostname = socket.gethostbyaddr(ip)[0]
                    except socket.herror:
                        hostname = "No resuelto"

                    mac_address = self.get_mac_address(ip)
                    dispositivo_info = f"{ip} - Hostname: {hostname} - MAC: {mac_address}"
                    dispositivos_encontrados.append(dispositivo_info)
                    self.result_area.append(f"Dispositivo encontrado: {dispositivo_info}\n")
            except subprocess.TimeoutExpired:
                pass  # Ignorar dispositivos que no respondan a tiempo
            except Exception as e:
                self.result_area.append(f"Error escaneando {ip}: {e}\n")

        # Registro final con todos los dispositivos encontrados
        if dispositivos_encontrados:
            entry = f"Escaneo completado. Dispositivos encontrados:\n" + "\n".join(dispositivos_encontrados)
        else:
            entry = f"Escaneo completado. No se encontraron dispositivos en {network_base}.x."

        self.result_area.append("Exploración completada.\n")
        self.history_tab.append_to_history(entry)

    def get_mac_address(self, ip):
        try:
            # Ejecutar el comando arp para obtener la dirección MAC
            output = subprocess.run(["arp", "-a", ip], capture_output=True, text=True)
            lines = output.stdout.splitlines()
            for line in lines:
                if ip in line:
                    # La dirección MAC suele estar en la segunda columna
                    parts = line.split()
                    if len(parts) > 1:
                        return parts[1]
        except Exception:
            pass
        return "No disponible"


class PortScanner(QWidget):
    def __init__(self, history_tab):
        super().__init__()
        self.history_tab = history_tab  # Guardamos la referencia de HistoryTab

        # Layout principal
        layout = QVBoxLayout()

        # Fondo oscuro y estilo elegante
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #1e1e1e;
            }
            QTextEdit {
                background-color: #2b2b2b;
                color: white;
                font-size: 14px;
                border: 1px solid #444;
            }
            QPushButton {
                background-color: #2b2b2b;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border-radius: 10px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
            }
            QLabel {
                color: black;
                font-size: 14px;
            }
            """
        )
        # Etiqueta y entrada para la IP o dominio
        ip_layout = QHBoxLayout()
        ip_label = QLabel("Dirección IP o dominio:")
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("Ejemplo: 192.168.1.1 o google.com")
        ip_layout.addWidget(ip_label)
        ip_layout.addWidget(self.ip_input)
        layout.addLayout(ip_layout)

        # Etiqueta y entrada para el rango de puertos
        port_layout = QHBoxLayout()
        port_label = QLabel("Rango de puertos:")
        self.port_range_input = QLineEdit()
        self.port_range_input.setPlaceholderText("Ejemplo: 20-80")
        port_layout.addWidget(port_label)
        port_layout.addWidget(self.port_range_input)
        layout.addLayout(port_layout)

        # Área de resultados
        self.result_area = QTextEdit()
        self.result_area.setReadOnly(True)
        layout.addWidget(self.result_area)

        # Botón de escanear puertos
        self.scan_button = QPushButton("Escanear Puertos")
        self.scan_button.clicked.connect(self.scan_ports)
        layout.addWidget(self.scan_button)

        # Botón de detener escaneo
        self.stop_button = QPushButton("Detener Escaneo")
        self.stop_button.clicked.connect(self.stop_scan)
        layout.addWidget(self.stop_button)

        self.setLayout(layout)

        # Variable para detener el escaneo
        self.stop_scanning = False
        
    def scan_ports(self):
        """Inicia el escaneo de puertos en un hilo separado."""
        target = self.ip_input.text().strip()
        port_range = self.port_range_input.text().strip()

        if not target:
            self.result_area.append("Error: Debes ingresar una dirección IP o dominio.\n")
            return

        if not port_range:
            self.result_area.append("Error: Debes ingresar un rango de puertos.\n")
            return

        try:
            start_port, end_port = map(int, port_range.split('-'))
        except ValueError:
            self.result_area.append("Error: El rango de puertos debe estar en el formato 'inicio-fin'.\n")
            return

        self.result_area.append(f"Iniciando escaneo de puertos en {target} ({start_port}-{end_port})...\n")
        self.stop_scanning = False
        threading.Thread(target=self.perform_scan, args=(target, start_port, end_port)).start()

    def stop_scan(self):
        """Detiene el escaneo de puertos."""
        self.stop_scanning = True
        self.result_area.append("Escaneo detenido por el usuario.\n")

    def perform_scan(self, target, start_port, end_port):
        """Realiza el escaneo de puertos en el rango especificado."""
        try:
            resultados = []  # Lista para almacenar los resultados
            for port in range(start_port, end_port + 1):
                if self.stop_scanning:
                    break

                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)  # Tiempo de espera
                    result = s.connect_ex((target, port))
                    if result == 0:  # El puerto está abierto
                        resultado = f"Puerto {port}: ABIERTO"
                        resultados.append(resultado)
                        self.result_area.append(f"{resultado}\n")
                    else:
                        resultado = f"Puerto {port}: CERRADO"
                        resultados.append(resultado)
                        self.result_area.append(f"{resultado}\n")

            # Crear una entrada para el historial
            if resultados:
                resumen = f"Escaneo de puertos en {target} ({start_port}-{end_port}):\n" + "\n".join(resultados)
            else:
                resumen = f"Escaneo de puertos en {target} ({start_port}-{end_port}): No se encontraron puertos abiertos."

            self.result_area.append("Escaneo completado.\n")
            self.history_tab.append_to_history(resumen)  # Añadir al historial
        except Exception as e:
            self.result_area.append(f"Error durante el escaneo: {str(e)}\n")
    
class HistoryTab(QWidget):
    def __init__(self):
        super().__init__()

        # Fondo oscuro y estilo elegante
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #1e1e1e;
            }
            QTextEdit {
                background-color: #2b2b2b;
                color: white;
                font-size: 14px;
                border: 1px solid #444;
            }
            QPushButton {
                background-color: #2b2b2b;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border-radius: 10px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
            }
            QLabel {
                color: black;
                font-size: 14px;
            }
            """
        )

        self.history_file = "scan_history.txt"

        # Layout principal
        layout = QVBoxLayout()

        # Etiqueta informativa
        layout.addWidget(QLabel("Registro histórico de escaneos:"))

        # Área de texto para mostrar el historial
        self.history_area = QTextEdit()
        self.history_area.setReadOnly(True)
        layout.addWidget(self.history_area)

        # Botón para recargar el historial
        self.load_button = QPushButton("Cargar historial")
        self.load_button.clicked.connect(self.load_history)
        layout.addWidget(self.load_button)

        # Botón para limpiar el historial
        self.clear_button = QPushButton("Limpiar historial")
        self.clear_button.clicked.connect(self.clear_history)
        layout.addWidget(self.clear_button)

        # Botón para exportar el historial
        self.export_button = QPushButton("Exportar historial")
        self.export_button.clicked.connect(self.export_history)
        layout.addWidget(self.export_button)

        # Botón para importar historial
        self.import_button = QPushButton("Importar historial")
        self.import_button.clicked.connect(self.import_history)
        layout.addWidget(self.import_button)

        self.setLayout(layout)

        # Cargar el historial al inicio
        self.load_history()

    def load_history(self):
        """Carga el historial desde el archivo y lo muestra en el área de texto."""
        if os.path.exists(self.history_file):
            with open(self.history_file, "r") as file:
                history_data = file.read()
                self.history_area.setText(history_data)
        else:
            self.history_area.setText("No hay historial disponible.\n")

    def clear_history(self):
        """Limpia el archivo de historial y actualiza el área de texto."""
        open(self.history_file, "w").close()  # Vacía el contenido del archivo
        self.history_area.setText("El historial ha sido limpiado.\n")

    def append_to_history(self, entry):
        """Añade una entrada al historial."""
        self.history_area.append(entry)
        with open(self.history_file, "a") as file:
            file.write(entry + "\n")

    def export_history(self):
        """Exporta el historial en formato .txt, .json o .csv."""
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(self, "Exportar historial", "", "Archivos TXT (*.txt);;Archivos JSON (*.json);;Archivos CSV (*.csv)", options=options)

        if file_path:
            data = self.history_area.toPlainText().splitlines()
            if file_path.endswith(".txt"):
                with open(file_path, "w") as file:
                    file.write("\n".join(data))
            elif file_path.endswith(".json"):
                with open(file_path, "w") as file:
                    json.dump(data, file, indent=4)
            elif file_path.endswith(".csv"):
                with open(file_path, "w", newline="") as file:
                    writer = csv.writer(file)
                    for line in data:
                        writer.writerow([line])
            self.history_area.append(f"Historial exportado a {file_path}\n")

    def import_history(self):
        """Importa un historial desde un archivo .txt, .json o .csv."""
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(self, "Importar historial", "", "Archivos TXT (*.txt);;Archivos JSON (*.json);;Archivos CSV (*.csv)", options=options)

        if file_path:
            if file_path.endswith(".txt"):
                with open(file_path, "r") as file:
                    data = file.read().splitlines()
            elif file_path.endswith(".json"):
                with open(file_path, "r") as file:
                    data = json.load(file)
            elif file_path.endswith(".csv"):
                with open(file_path, "r") as file:
                    reader = csv.reader(file)
                    data = [",".join(row) for row in reader]

            # Actualiza el área de texto y sobrescribe el archivo actual
            self.history_area.setText("\n".join(data))
            with open(self.history_file, "w") as file:
                file.write("\n".join(data))
            self.history_area.append(f"Historial importado desde {file_path}\n")


class SettingsTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()

        # Descripción general
        layout.addWidget(QLabel("Configuraciones generales del programa."))

        # Tema
        self.theme_label = QLabel("Tema:")
        self.theme_combobox = QComboBox()
        self.theme_combobox.addItems(["Claro", "Oscuro"])
        self.theme_combobox.currentIndexChanged.connect(self.change_theme)
        layout.addWidget(self.theme_label)
        layout.addWidget(self.theme_combobox)

        # Tamaño de fuente
        self.font_label = QLabel("Tamaño de fuente:")
        self.font_size_spinbox = QSpinBox()
        self.font_size_spinbox.setRange(8, 24)
        self.font_size_spinbox.setValue(14)
        self.font_size_spinbox.valueChanged.connect(self.change_font_size)
        layout.addWidget(self.font_label)
        layout.addWidget(self.font_size_spinbox)

         # Configuración de proxy
        self.proxy_label = QLabel("Configurar Proxy:")
        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("http://proxy:puerto")
        layout.addWidget(self.proxy_label)
        layout.addWidget(self.proxy_input)

        # Guardar configuración de proxy
        self.save_proxy_button = QPushButton("Guardar Proxy")
        self.save_proxy_button.clicked.connect(self.save_proxy)
        layout.addWidget(self.save_proxy_button)

         # Configuración de directorio por defecto
        self.export_path_label = QLabel("Directorio por defecto:")
        self.export_path_button = QPushButton("Seleccionar carpeta")
        self.export_path_button.clicked.connect(self.select_export_path)
        layout.addWidget(self.export_path_label)
        layout.addWidget(self.export_path_button)

        # Idioma
        self.language_label = QLabel("Idioma:")
        self.language_combobox = QComboBox()
        self.language_combobox.addItems(["Español", "Inglés"])
        self.language_combobox.currentIndexChanged.connect(self.change_language)
        layout.addWidget(self.language_label)
        layout.addWidget(self.language_combobox)

         # Activar/desactivar notificaciones
        self.notifications_checkbox = QCheckBox("Activar notificaciones")
        layout.addWidget(self.notifications_checkbox)

        self.save_notifications_button = QPushButton("Guardar configuración de notificaciones")
        self.save_notifications_button.clicked.connect(self.save_notifications)
        layout.addWidget(self.save_notifications_button)

        # Aplicar los cambios
        self.save_button = QPushButton("Guardar configuración")
        self.save_button.clicked.connect(self.save_settings)
        layout.addWidget(self.save_button)
        
        self.setLayout(layout)
        
    def change_theme(self):
        """Cambia el tema de la aplicación."""
        theme = self.theme_combobox.currentText()
        if theme == "Claro":
            # Estilo para el tema claro
            self.setStyleSheet("""
                QWidget {
                    background-color: white;
                    color: black;
                }
                QLineEdit, QComboBox, QSpinBox, QPushButton {
                    background-color: #f0f0f0;
                    color: black;
                    border: 1px solid #ccc;
                }
                QComboBox::drop-down {
                    border: none;
                }
                QPushButton {
                    background-color: #e6e6e6;
                    border-radius: 5px;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #d6d6d6;
                }
            """)
        elif theme == "Oscuro":
            # Estilo para el tema oscuro
            self.setStyleSheet("""
                QWidget {
                    background-color: #2e2e2e;
                    color: white;
                }
                QLineEdit, QComboBox, QSpinBox, QPushButton {
                    background-color: #3e3e3e;
                    color: white;
                    border: 1px solid #555;
                }
                QComboBox::drop-down {
                    border: none;
                }
                QPushButton {
                    background-color: #4e4e4e;
                    border-radius: 5px;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #5e5e5e;
                }
            """)
        else:
            # Restablecer estilo predeterminado si es necesario
            self.setStyleSheet("")
        
        print(f"Tema cambiado a: {theme}")


    def change_font_size(self):
        """Cambia el tamaño de la fuente."""
        font_size = self.font_size_spinbox.value()
        # Implementar lógica para cambiar el tamaño de la fuente.

    def change_language(self):
        """Cambia el idioma de la aplicación."""
        language = self.language_combobox.currentText()
        # Implementar lógica para cambiar idioma (ej., recargar textos).

    def save_proxy(self):
        """Guarda la configuración del proxy."""
        proxy = self.proxy_input.text()
        print(f"Proxy configurado: {proxy}")
        # Guardar en archivo o aplicar a la configuración de red.

    def save_settings(self):
        """Guarda las configuraciones actuales."""
        # Aquí se guardarran las configuraciones en un archivo o base de datos.
        print("Configuraciones guardadas.")

    def select_export_path(self):
        """Abre un diálogo para seleccionar un directorio."""
        directory = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta")
        if directory:
            self.export_path_label.setText(f"Directorio: {directory}")

    def save_notifications(self):
        """Guarda el estado de las notificaciones."""
        notifications_enabled = self.notifications_checkbox.isChecked()
        print(f"Notificaciones activadas: {notifications_enabled}")        
    
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Explorador de Red")
        self.setGeometry(200, 200, 800, 600)

        # Crear la instancia de HistoryTab
        history_tab = HistoryTab()

        # Crear las demás pestañas, pasando la referencia de history_tab
        network_scanner = NetworkScanner(history_tab)
        port_scanner = PortScanner(history_tab)
        settings_tab = SettingsTab()  # Si no necesita historial, no pasa la referencia

        # Crear el QTabWidget y añadir las pestañas
        tabs = QTabWidget()
        tabs.addTab(network_scanner, "Escáner de Red")
        tabs.addTab(port_scanner, "Escáner de Puertos")
        tabs.addTab(history_tab, "Registro Histórico")
        tabs.addTab(settings_tab, "Configuración")

        self.setCentralWidget(tabs)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
