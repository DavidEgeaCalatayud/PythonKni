from PyQt5.QtCore import Qt

class ThemeManager:
    current_theme = "Claro"

    @staticmethod
    def set_theme(theme):
        ThemeManager.current_theme = theme

    @staticmethod
    def get_theme():
        return ThemeManager.current_theme

    @staticmethod
    def apply_theme(app):
        """Aplica el tema global a la aplicación."""
        if ThemeManager.current_theme == "Oscuro":
            app.setStyleSheet("""
                QMainWindow {
                    background-color: #000000; /* Fondo negro */
                    color: #ffffff; /* Texto blanco */
                }
                QPushButton {
                    background-color: #333333; /* Botones gris oscuro */
                    color: #ffffff; /* Texto blanco */
                    border: 2px solid #555555; /* Bordes más visibles */
                    border-radius: 5px; /* Bordes redondeados */
                }
                QPushButton:hover {
                    background-color: #555555; /* Efecto hover */
                    color: #dddddd; /* Texto más claro */
                }
                QLabel {
                    color: #ffffff; /* Texto blanco */
                }
                QComboBox {
                    background-color: #333333; /* Fondo gris oscuro */
                    color: #ffffff; /* Texto blanco */
                    border: 1px solid #555555; /* Bordes visibles */
                }
                QComboBox::drop-down {
                    background-color: #444444; /* Dropdown más oscuro */
                    border: 1px solid #666666;
                }
                QLineEdit {
                    background-color: #222222; /* Fondo gris oscuro */
                    color: #ffffff; /* Texto blanco */
                    border: 1px solid #444444;
                }
            """)
        else:
            app.setStyleSheet("""
                QMainWindow {
                    background-color: #ffffff; /* Fondo blanco */
                    color: #000000; /* Texto negro */
                }
                QPushButton {
                    background-color: #f0f0f0; /* Fondo claro */
                    color: #000000; /* Texto negro */
                    border: 2px solid #cccccc; /* Bordes suaves */
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0; /* Efecto hover */
                    color: #111111; /* Texto más oscuro */
                }
                QLabel {
                    color: #000000; /* Texto negro */
                }
                QComboBox {
                    background-color: #ffffff; /* Fondo blanco */
                    color: #000000; /* Texto negro */
                    border: 1px solid #cccccc; /* Bordes suaves */
                }
                QComboBox::drop-down {
                    background-color: #f0f0f0; /* Dropdown claro */
                    border: 1px solid #dddddd;
                }
                QLineEdit {
                    background-color: #ffffff; /* Fondo blanco */
                    color: #000000; /* Texto negro */
                    border: 1px solid #cccccc;
                }
            """)
