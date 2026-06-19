from __future__ import annotations

import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from PyQt5.QtWidgets import QMainWindow, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget


def _run_netsh(args: list[str]) -> str:
    completed = subprocess.run(
        ["netsh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return completed.stdout


def _parse_profiles(output: str) -> list[str]:
    profiles = []
    for line in output.splitlines():
        if ":" not in line:
            continue
        left, right = line.split(":", 1)
        profile = right.strip()
        label = left.lower()
        if profile and ("profile" in label or "perfil" in label):
            profiles.append(profile)
    return profiles


def _read_exported_password(profile: str, export_dir: Path) -> str:
    _run_netsh(["wlan", "export", "profile", f"name={profile}", "key=clear", f"folder={export_dir}"])
    exported_files = sorted(export_dir.glob("*.xml"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not exported_files:
        return "No Password"

    tree = ET.parse(exported_files[0])
    root = tree.getroot()
    namespace = {"w": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {}
    key = root.find(".//w:keyMaterial", namespace) if namespace else root.find(".//keyMaterial")
    return key.text if key is not None and key.text else "No Password"


def get_wifi_profiles():
    """Obtiene las redes WiFi guardadas en Windows junto con sus contrasenas."""
    try:
        output = _run_netsh(["wlan", "show", "profiles"])
        profiles = _parse_profiles(output)
        wifi_data = []

        with tempfile.TemporaryDirectory() as temp_dir:
            export_dir = Path(temp_dir)
            for profile in profiles:
                try:
                    wifi_data.append((profile, _read_exported_password(profile, export_dir)))
                except (subprocess.CalledProcessError, ET.ParseError, OSError):
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

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["WiFi Name", "Password"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        layout = QVBoxLayout()
        layout.addWidget(self.table)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.show_wifi_data()

    def show_wifi_data(self):
        data = get_wifi_profiles()
        self.table.setRowCount(len(data))
        for row, (name, password) in enumerate(data):
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(password))
