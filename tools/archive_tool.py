from PyQt5.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QPushButton

from tools.theme_manager import ThemeManager
from tools.zip_7zip_utils import create_7z, create_zip, extract_7z, extract_zip


class Tool(QMainWindow):
    name = "Gestor de Archivos (ZIP/7Z)"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.name)
        self.setGeometry(150, 150, 400, 200)

        layout = QVBoxLayout()

        btn_extract_zip = QPushButton("Extraer ZIP")
        btn_extract_zip.clicked.connect(extract_zip)
        layout.addWidget(btn_extract_zip)

        btn_create_zip = QPushButton("Crear ZIP")
        btn_create_zip.clicked.connect(create_zip)
        layout.addWidget(btn_create_zip)

        btn_extract_7z = QPushButton("Extraer 7z")
        btn_extract_7z.clicked.connect(extract_7z)
        layout.addWidget(btn_extract_7z)

        btn_create_7z = QPushButton("Crear 7z")
        btn_create_7z.clicked.connect(create_7z)
        layout.addWidget(btn_create_7z)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        app = self.parent() if self.parent() else None
        if app:
            ThemeManager.apply_theme(app)
