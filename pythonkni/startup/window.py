from __future__ import annotations

import csv
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tools.base_tool import BaseTool
from tools.theme_manager import ThemeManager

from .models import StartupItem
from .service import (
    collect_startup_items,
    disable_folder_item,
    disable_registry_item,
    enable_folder_item,
    enable_registry_item,
    extract_executable_path,
    is_windows,
    open_folder,
    run_regedit_at_key,
)


class Tool(BaseTool):
    name = "Gestor de Inicio de Windows"
    description = "Administra aplicaciones configuradas para iniciar con Windows."
    category = "Sistema"

    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(220, 220, 1250, 650)
        ThemeManager.apply_theme(self)

        self.items_by_id: dict[str, StartupItem] = {}
        self.items: list[StartupItem] = []

        layout = QVBoxLayout()
        layout.addWidget(
            QLabel(
                "Revisa los programas que arrancan con Windows. "
                "Las desactivaciones se guardan como copia recuperable, no se eliminan definitivamente."
            )
        )

        self.status_label = QLabel("Pulsa Actualizar para cargar las entradas de inicio.")
        layout.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Activo", "Nombre", "Origen", "Comando / Ruta", "Tipo", "Existe archivo", "Riesgo"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        button_layout = QHBoxLayout()

        self.btn_refresh = QPushButton("Actualizar")
        self.btn_refresh.clicked.connect(self.load_items)
        button_layout.addWidget(self.btn_refresh)

        self.btn_disable = QPushButton("Desactivar")
        self.btn_disable.clicked.connect(self.disable_selected)
        button_layout.addWidget(self.btn_disable)

        self.btn_enable = QPushButton("Activar")
        self.btn_enable.clicked.connect(self.enable_selected)
        button_layout.addWidget(self.btn_enable)

        self.btn_open = QPushButton("Abrir ubicación")
        self.btn_open.clicked.connect(self.open_selected_location)
        button_layout.addWidget(self.btn_open)

        self.btn_copy = QPushButton("Copiar ruta")
        self.btn_copy.clicked.connect(self.copy_selected_command)
        button_layout.addWidget(self.btn_copy)

        self.btn_export = QPushButton("Exportar CSV")
        self.btn_export.clicked.connect(self.export_csv)
        button_layout.addWidget(self.btn_export)

        layout.addLayout(button_layout)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.load_items()

    def load_items(self) -> None:
        if not is_windows():
            self.table.setRowCount(0)
            self.status_label.setText("Esta herramienta solo funciona en Windows.")
            QMessageBox.warning(self, self.name, "Esta herramienta solo funciona en Windows.")
            return

        self.items = collect_startup_items()
        self.items_by_id = {item.id: item for item in self.items}
        self.fill_table(self.items)
        active_count = sum(1 for item in self.items if item.active)
        disabled_count = len(self.items) - active_count
        self.status_label.setText(
            f"Entradas activas: {active_count} | Entradas desactivadas recuperables: {disabled_count}"
        )

    def fill_table(self, items: list[StartupItem]) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(items))

        for row, item in enumerate(items):
            active_item = QTableWidgetItem("Sí" if item.active else "No")
            active_item.setData(Qt.UserRole, item.id)
            self.table.setItem(row, 0, active_item)
            self.table.setItem(row, 1, QTableWidgetItem(item.name))
            self.table.setItem(row, 2, QTableWidgetItem(item.source))
            self.table.setItem(row, 3, QTableWidgetItem(item.command))
            self.table.setItem(row, 4, QTableWidgetItem(item.item_type))
            self.table.setItem(row, 5, QTableWidgetItem(item.exists))
            self.table.setItem(row, 6, QTableWidgetItem(item.risk))

        self.table.setSortingEnabled(True)

    def selected_item(self) -> StartupItem | None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, self.name, "Selecciona una entrada primero.")
            return None
        id_item = self.table.item(row, 0)
        if id_item is None:
            return None
        item_id = id_item.data(Qt.UserRole)
        return self.items_by_id.get(str(item_id))

    def disable_selected(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        if not item.active:
            QMessageBox.information(self, self.name, "Esta entrada ya está desactivada.")
            return

        extra_warning = ""
        if item.root_name == "HKLM":
            extra_warning = "\n\nEsta entrada pertenece a HKEY_LOCAL_MACHINE y puede requerir ejecutar la app como administrador."

        response = QMessageBox.question(
            self,
            "Confirmar desactivación",
            f"¿Quieres desactivar esta entrada de inicio?\n\nNombre: {item.name}\nOrigen: {item.source}\n\n"
            "Se guardará una copia para poder restaurarla después."
            f"{extra_warning}",
        )
        if response != QMessageBox.Yes:
            return

        try:
            if item.origin_kind == "registry":
                disable_registry_item(item)
            elif item.origin_kind == "folder":
                disable_folder_item(item)
            else:
                QMessageBox.warning(self, self.name, "Este tipo de entrada no se puede desactivar.")
                return

            QMessageBox.information(self, self.name, "Entrada desactivada correctamente.")
            self.load_items()
        except PermissionError as error:
            QMessageBox.critical(
                self,
                "Permisos insuficientes",
                f"No se pudo desactivar la entrada. Prueba a ejecutar PythonKni como administrador.\n\n{error}",
            )
        except Exception as error:
            QMessageBox.critical(self, "Error", f"No se pudo desactivar la entrada:\n{error}")

    def enable_selected(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        if item.active:
            QMessageBox.information(self, self.name, "Esta entrada ya está activa.")
            return

        response = QMessageBox.question(
            self,
            "Confirmar activación",
            f"¿Quieres restaurar esta entrada de inicio?\n\nNombre: {item.name}\nOrigen original: {item.source}",
        )
        if response != QMessageBox.Yes:
            return

        try:
            if item.origin_kind == "disabled_registry":
                enable_registry_item(item)
            elif item.origin_kind == "disabled_folder":
                enable_folder_item(item)
            else:
                QMessageBox.warning(self, self.name, "Este tipo de entrada no se puede activar.")
                return

            QMessageBox.information(self, self.name, "Entrada restaurada correctamente.")
            self.load_items()
        except PermissionError as error:
            QMessageBox.critical(
                self,
                "Permisos insuficientes",
                f"No se pudo restaurar la entrada. Prueba a ejecutar PythonKni como administrador.\n\n{error}",
            )
        except Exception as error:
            QMessageBox.critical(self, "Error", f"No se pudo restaurar la entrada:\n{error}")

    def open_selected_location(self) -> None:
        item = self.selected_item()
        if item is None:
            return

        path_to_open = ""
        if item.origin_kind in {"folder", "disabled_folder"}:
            path_to_open = item.file_path or item.backup_path or item.command
        else:
            path_to_open = extract_executable_path(item.command)

        try:
            if path_to_open and Path(path_to_open).exists():
                open_folder(path_to_open)
            elif item.origin_kind in {"registry", "disabled_registry"}:
                run_regedit_at_key(item.root_name, item.key_path)
            else:
                QMessageBox.warning(self, self.name, "No se pudo localizar una carpeta válida.")
        except Exception as error:
            QMessageBox.critical(self, "Error", f"No se pudo abrir la ubicación:\n{error}")

    def copy_selected_command(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        QApplication.clipboard().setText(item.command)
        QMessageBox.information(self, self.name, "Ruta/comando copiado al portapapeles.")

    def export_csv(self) -> None:
        if not self.items:
            QMessageBox.warning(self, "Exportar", "No hay datos para exportar.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar CSV",
            "programas_inicio_windows.csv",
            "CSV (*.csv)",
        )
        if not file_path:
            return

        with open(file_path, "w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.writer(csv_file, delimiter=";")
            writer.writerow(
                ["Activo", "Nombre", "Origen", "Comando / Ruta", "Tipo", "Existe archivo", "Riesgo"]
            )
            for item in self.items:
                writer.writerow(
                    [
                        "Sí" if item.active else "No",
                        item.name,
                        item.source,
                        item.command,
                        item.item_type,
                        item.exists,
                        item.risk,
                    ]
                )

        QMessageBox.information(self, "Exportado", "CSV generado correctamente.")
