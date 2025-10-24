from PyQt5.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QPushButton
from zip_7zip_handler import extract_zip, create_zip, extract_7z, create_7z
from theme_manager import ThemeManager

class ArchiveWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gestor de Archivos (ZIP/7Z)")
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

        ThemeManager.apply_theme(self)
