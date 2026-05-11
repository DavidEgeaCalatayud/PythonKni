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
                    background-color: #1e1e1e;
                }
                QTabWidget::pane {
                    border: 1px solid #444;
                    background: #1e1e1e;
                }
                QTabBar::tab {
                    background: #2b2b2b;
                    color: white;
                    padding: 6px;
                    border: 1px solid #444;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                }
                QTabBar::tab:selected {
                    background: #3d3d3d;
                }
                QLabel {
                    color: white;
                    font-size: 14px;
                }
                QTextEdit {
                    background-color: #2b2b2b;
                    color: white;
                    border: 1px solid #444;
                }
                QLineEdit {
                    background-color: #2b2b2b;
                    color: white;
                    border: 1px solid #555;
                }
                QComboBox {
                    background-color: #2b2b2b;
                    color: white;
                    border: 1px solid #555;
                }
                QSpinBox {
                    background-color: #2b2b2b;
                    color: white;
                    border: 1px solid #555;
                }
                QCheckBox {
                    color: white;
                }
                QPushButton {
                    background-color: #2b2b2b;
                    color: white;
                    font-size: 14px;
                    font-weight: bold;
                    border-radius: 6px;
                    padding: 6px;
                }
                QPushButton:hover {
                    background-color: #3d3d3d;
                }
                QMessageBox {
                    background-color: #2b2b2b;
                    color: white;
                }
                QInputDialog {
                    background-color: #2b2b2b;
                    color: white;
                }
            """)
        else:  # Claro
            app.setStyleSheet("""
                QMainWindow {
                    background-color: #ffffff;
                }
                QTabWidget::pane {
                    border: 1px solid #ccc;
                    background: #fff;
                }
                QTabBar::tab {
                    background: #f0f0f0;
                    color: black;
                    padding: 6px;
                    border: 1px solid #ccc;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                }
                QTabBar::tab:selected {
                    background: #e0e0e0;
                }
                QLabel {
                    color: black;
                    font-size: 14px;
                }
                QTextEdit {
                    background-color: #ffffff;
                    color: black;
                    border: 1px solid #ccc;
                }
                QLineEdit {
                    background-color: #ffffff;
                    color: black;
                    border: 1px solid #ccc;
                }
                QComboBox {
                    background-color: #ffffff;
                    color: black;
                    border: 1px solid #ccc;
                }
                QSpinBox {
                    background-color: #ffffff;
                    color: black;
                    border: 1px solid #ccc;
                }
                QCheckBox {
                    color: black;
                }
                QPushButton {
                    background-color: #f0f0f0;
                    color: black;
                    font-size: 14px;
                    font-weight: bold;
                    border-radius: 6px;
                    padding: 6px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                }
                QMessageBox {
                    background-color: #ffffff;
                    color: black;
                }
                QInputDialog {
                    background-color: #ffffff;
                    color: black;
                }
            """)
