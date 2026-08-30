from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from pythonkni.startup import window as startup_window
from pythonkni.startup.models import StartupItem


def make_item(**overrides):
    values = {
        "active": True,
        "name": "Example",
        "source": "Registro usuario",
        "command": r"C:\Program Files\Example\app.exe --start",
        "item_type": "Registro",
        "exists": "Sí",
        "risk": "Normal",
        "origin_kind": "registry",
        "root_name": "HKCU",
        "key_path": r"Software\Microsoft\Windows\CurrentVersion\Run",
        "value_name": "Example",
        "value_type": 1,
    }
    values.update(overrides)
    return StartupItem(**values)


def build_tool(qtbot, monkeypatch, items=None):
    source_items = list(items or [])
    monkeypatch.setattr(startup_window, "is_windows", lambda: True)
    monkeypatch.setattr(startup_window, "collect_startup_items", lambda: list(source_items))
    monkeypatch.setattr(startup_window.QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(startup_window.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(startup_window.QMessageBox, "critical", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        startup_window.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.Yes,
    )
    tool = startup_window.Tool()
    qtbot.addWidget(tool)
    return tool


def select_item(tool, item):
    tool.items = [item]
    tool.items_by_id = {item.id: item}
    tool.fill_table(tool.items)
    tool.table.setCurrentCell(0, 0)


def test_startup_window_loads_items_and_non_windows_state(qtbot, monkeypatch):
    active = make_item(name="Active")
    disabled = make_item(
        active=False,
        name="Disabled",
        source="Registro usuario desactivado",
        origin_kind="disabled_registry",
        disabled_id="backup-1",
    )
    tool = build_tool(qtbot, monkeypatch, [active, disabled])

    assert tool.table.rowCount() == 2
    assert tool.table.item(0, 0).data(Qt.UserRole) in {active.id, disabled.id}
    assert "Entradas activas: 1" in tool.status_label.text()
    assert "Entradas desactivadas recuperables: 1" in tool.status_label.text()

    warnings = []
    monkeypatch.setattr(startup_window, "is_windows", lambda: False)
    monkeypatch.setattr(
        startup_window.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[-1]),
    )
    tool.load_items()

    assert tool.table.rowCount() == 0
    assert "solo funciona en Windows" in tool.status_label.text()
    assert warnings


def test_selected_item_handles_no_selection_missing_cell_and_unknown_id(qtbot, monkeypatch):
    tool = build_tool(qtbot, monkeypatch, [make_item()])
    warnings = []
    monkeypatch.setattr(
        startup_window.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[-1]),
    )

    tool.table.clearSelection()
    tool.table.setCurrentCell(-1, -1)
    assert tool.selected_item() is None
    assert warnings

    tool.table.setRowCount(1)
    tool.table.setItem(0, 0, None)
    tool.table.setCurrentCell(0, 0)
    assert tool.selected_item() is None

    tool.table.setItem(0, 0, startup_window.QTableWidgetItem("Sí"))
    tool.table.item(0, 0).setData(Qt.UserRole, "unknown")
    assert tool.selected_item() is None


def test_disable_selected_registry_folder_and_guard_branches(qtbot, monkeypatch):
    tool = build_tool(qtbot, monkeypatch)
    calls = []
    tool.load_items = lambda: calls.append("reload")
    monkeypatch.setattr(
        startup_window,
        "disable_registry_item",
        lambda item: calls.append(("registry", item.name)),
    )
    monkeypatch.setattr(
        startup_window,
        "disable_folder_item",
        lambda item: calls.append(("folder", item.name)),
    )

    registry = make_item(name="Registry", root_name="HKLM")
    select_item(tool, registry)
    tool.disable_selected()
    assert ("registry", "Registry") in calls
    assert "reload" in calls

    calls.clear()
    folder = make_item(
        name="Folder",
        item_type="Carpeta inicio",
        origin_kind="folder",
        root_name="",
    )
    select_item(tool, folder)
    tool.disable_selected()
    assert calls == [("folder", "Folder"), "reload"]

    info = []
    monkeypatch.setattr(
        startup_window.QMessageBox,
        "information",
        lambda *args, **kwargs: info.append(args[-1]),
    )
    select_item(tool, make_item(active=False))
    tool.disable_selected()
    assert any("ya está desactivada" in message for message in info)

    warnings = []
    monkeypatch.setattr(
        startup_window.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[-1]),
    )
    select_item(tool, make_item(origin_kind="unsupported"))
    tool.disable_selected()
    assert any("no se puede desactivar" in message for message in warnings)

    monkeypatch.setattr(
        startup_window.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.No,
    )
    calls.clear()
    select_item(tool, make_item())
    tool.disable_selected()
    assert calls == []


def test_disable_selected_surfaces_permission_and_generic_errors(qtbot, monkeypatch):
    tool = build_tool(qtbot, monkeypatch)
    critical = []
    monkeypatch.setattr(
        startup_window.QMessageBox,
        "critical",
        lambda *args, **kwargs: critical.append((args[1], args[2])),
    )

    select_item(tool, make_item())
    monkeypatch.setattr(
        startup_window,
        "disable_registry_item",
        lambda _item: (_ for _ in ()).throw(PermissionError("denied")),
    )
    tool.disable_selected()
    assert any(title == "Permisos insuficientes" for title, _ in critical)

    critical.clear()
    monkeypatch.setattr(
        startup_window,
        "disable_registry_item",
        lambda _item: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    tool.disable_selected()
    assert any(title == "Error" and "boom" in message for title, message in critical)


def test_enable_selected_registry_folder_and_error_branches(qtbot, monkeypatch):
    tool = build_tool(qtbot, monkeypatch)
    calls = []
    tool.load_items = lambda: calls.append("reload")
    monkeypatch.setattr(
        startup_window,
        "enable_registry_item",
        lambda item: calls.append(("registry", item.name)),
    )
    monkeypatch.setattr(
        startup_window,
        "enable_folder_item",
        lambda item: calls.append(("folder", item.name)),
    )

    disabled_registry = make_item(
        active=False,
        name="Registry",
        origin_kind="disabled_registry",
        disabled_id="backup-1",
    )
    select_item(tool, disabled_registry)
    tool.enable_selected()
    assert calls == [("registry", "Registry"), "reload"]

    calls.clear()
    disabled_folder = make_item(
        active=False,
        name="Folder",
        origin_kind="disabled_folder",
        item_type="Carpeta inicio",
    )
    select_item(tool, disabled_folder)
    tool.enable_selected()
    assert calls == [("folder", "Folder"), "reload"]

    info = []
    monkeypatch.setattr(
        startup_window.QMessageBox,
        "information",
        lambda *args, **kwargs: info.append(args[-1]),
    )
    select_item(tool, make_item(active=True))
    tool.enable_selected()
    assert any("ya está activa" in message for message in info)

    warnings = []
    monkeypatch.setattr(
        startup_window.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[-1]),
    )
    select_item(tool, make_item(active=False, origin_kind="unsupported"))
    tool.enable_selected()
    assert any("no se puede activar" in message for message in warnings)

    critical = []
    monkeypatch.setattr(
        startup_window.QMessageBox,
        "critical",
        lambda *args, **kwargs: critical.append((args[1], args[2])),
    )
    select_item(tool, disabled_registry)
    monkeypatch.setattr(
        startup_window,
        "enable_registry_item",
        lambda _item: (_ for _ in ()).throw(PermissionError("denied")),
    )
    tool.enable_selected()
    assert any(title == "Permisos insuficientes" for title, _ in critical)

    critical.clear()
    monkeypatch.setattr(
        startup_window,
        "enable_registry_item",
        lambda _item: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    tool.enable_selected()
    assert any(title == "Error" and "boom" in message for title, message in critical)


def test_open_selected_location_covers_file_registry_warning_and_error(qtbot, monkeypatch, tmp_path):
    tool = build_tool(qtbot, monkeypatch)
    opened = []
    regedit = []
    warnings = []
    critical = []
    monkeypatch.setattr(startup_window, "open_folder", lambda path: opened.append(str(path)))
    monkeypatch.setattr(
        startup_window,
        "run_regedit_at_key",
        lambda root, key: regedit.append((root, key)),
    )
    monkeypatch.setattr(
        startup_window.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[-1]),
    )
    monkeypatch.setattr(
        startup_window.QMessageBox,
        "critical",
        lambda *args, **kwargs: critical.append(args[-1]),
    )

    file_path = tmp_path / "startup.lnk"
    file_path.write_text("shortcut", encoding="utf-8")
    select_item(
        tool,
        make_item(
            origin_kind="folder",
            item_type="Carpeta inicio",
            file_path=str(file_path),
            command=str(file_path),
        ),
    )
    tool.open_selected_location()
    assert opened == [str(file_path)]

    select_item(tool, make_item(command=r"C:\missing\app.exe"))
    monkeypatch.setattr(startup_window, "extract_executable_path", lambda _command: "")
    tool.open_selected_location()
    assert regedit == [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run")]

    select_item(tool, make_item(origin_kind="unsupported", command="missing"))
    tool.open_selected_location()
    assert any("No se pudo localizar" in message for message in warnings)

    select_item(tool, make_item())
    monkeypatch.setattr(
        startup_window,
        "run_regedit_at_key",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("open failed")),
    )
    tool.open_selected_location()
    assert any("open failed" in message for message in critical)


def test_copy_selected_command_uses_clipboard(qtbot, monkeypatch):
    item = make_item(command="example --start")
    tool = build_tool(qtbot, monkeypatch, [item])
    select_item(tool, item)

    tool.copy_selected_command()

    assert startup_window.QApplication.clipboard().text() == "example --start"


def test_export_csv_empty_cancel_and_success(qtbot, monkeypatch, tmp_path):
    tool = build_tool(qtbot, monkeypatch)
    warnings = []
    info = []
    monkeypatch.setattr(
        startup_window.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[-1]),
    )
    monkeypatch.setattr(
        startup_window.QMessageBox,
        "information",
        lambda *args, **kwargs: info.append(args[-1]),
    )

    tool.items = []
    tool.export_csv()
    assert any("No hay datos" in message for message in warnings)

    item = make_item(name="=Formula", command="+danger")
    tool.items = [item]
    monkeypatch.setattr(
        startup_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    tool.export_csv()

    output = tmp_path / "startup.csv"
    monkeypatch.setattr(
        startup_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), ""),
    )
    tool.export_csv()

    content = output.read_text(encoding="utf-8-sig")
    assert "'=Formula" in content
    assert "'+danger" in content
    assert any("CSV generado" in message for message in info)
