import errno
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import pythonkni.startup.service as startup


def make_registry_item(**overrides):
    values = {
        "active": True,
        "name": "Example",
        "source": "Registro usuario",
        "command": r'C:\Program Files\Example\app.exe --start',
        "item_type": "Registro",
        "exists": "Sí",
        "risk": "Normal",
        "origin_kind": "registry",
        "root_name": "HKCU",
        "key_path": startup.RUN_KEY,
        "value_name": "Example",
        "value_type": 1,
    }
    values.update(overrides)
    return startup.StartupItem(**values)


def make_folder_item(path: Path, **overrides):
    values = {
        "active": True,
        "name": path.name,
        "source": "Inicio usuario",
        "command": str(path),
        "item_type": "Carpeta inicio",
        "exists": "Sí",
        "risk": "Normal",
        "origin_kind": "folder",
        "file_path": str(path),
    }
    values.update(overrides)
    return startup.StartupItem(**values)


@pytest.mark.parametrize(
    ("command", "expected_suffix"),
    [
        (r'"C:\Program Files\App\app.exe" --silent', r"App\app.exe"),
        (r"C:\Tools\worker.cmd /background", r"Tools\worker.cmd"),
        ("", ""),
    ],
)
def test_extract_executable_path_common_forms(command, expected_suffix):
    extracted = startup.extract_executable_path(command)
    assert extracted.endswith(expected_suffix)


def test_extract_executable_path_uses_path_lookup(monkeypatch):
    monkeypatch.setattr(startup.shutil, "which", lambda name: r"C:\Tools\helper.exe")
    assert startup.extract_executable_path("helper --quiet") == r"C:\Tools\helper.exe"


def test_expand_command_expands_environment(monkeypatch):
    monkeypatch.setenv("PYTHONKNI_TEST_HOME", r"C:\Example")
    assert "Example" in startup.expand_command(r"%PYTHONKNI_TEST_HOME%\app.exe")


def test_path_exists_from_command(monkeypatch, tmp_path):
    executable = tmp_path / "app.exe"
    executable.write_text("binary", encoding="utf-8")
    monkeypatch.setattr(startup, "extract_executable_path", lambda _command: str(executable))
    assert startup.path_exists_from_command("anything") == "Sí"

    monkeypatch.setattr(startup, "extract_executable_path", lambda _command: "")
    assert startup.path_exists_from_command("anything") == "Desconocido"

    monkeypatch.setattr(startup, "extract_executable_path", lambda _command: str(tmp_path / "missing.exe"))
    assert startup.path_exists_from_command("anything") == "No"


@pytest.mark.parametrize(
    ("command", "exists", "active", "expected"),
    [
        (r"C:\safe\app.exe", "Sí", False, "Desactivado"),
        (r"C:\Users\me\AppData\Local\Temp\evil.exe", "Sí", True, "Alto"),
        (r"C:\safe\missing.exe", "No", True, "Medio"),
        (r"powershell.exe -File C:\safe\task.ps1", "Sí", True, "Medio"),
        (r"cmd.exe /c %APPDATA%\task.cmd", "Sí", True, "Alto"),
        (r"C:\Users\me\AppData\Roaming\app.exe", "Sí", True, "Medio"),
        (r"C:\Program Files\Vendor\app.exe", "Sí", True, "Normal"),
    ],
)
def test_calculate_risk_matrix(command, exists, active, expected):
    assert startup.calculate_risk(command, exists, active) == expected


def test_item_from_basic_calculates_exists_and_risk(tmp_path):
    entry = tmp_path / "startup.lnk"
    entry.write_text("shortcut", encoding="utf-8")

    item = startup.item_from_basic(
        active=True,
        name="Startup",
        source="Inicio usuario",
        command=str(entry),
        item_type="Carpeta inicio",
        origin_kind="folder",
        file_path=str(entry),
    )

    assert item.exists == "Sí"
    assert item.risk == "Normal"
    assert item.file_path == str(entry)


def test_startup_folder_helpers_read_environment(monkeypatch, tmp_path):
    appdata = tmp_path / "AppData" / "Roaming"
    programdata = tmp_path / "ProgramData"
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("PROGRAMDATA", str(programdata))

    assert startup.startup_user_folder() == (
        appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    )
    assert startup.startup_common_folder() == (
        programdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "StartUp"
    )

    monkeypatch.delenv("APPDATA")
    monkeypatch.delenv("PROGRAMDATA")
    assert startup.startup_user_folder() is None
    assert startup.startup_common_folder() is None


def test_disabled_folder_root_is_created_under_local_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert startup.disabled_folder_root() == tmp_path / "PythonKni" / "startup_disabled"


def test_open_folder_rejects_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        startup.open_folder(tmp_path / "missing")


def test_open_folder_uses_parent_for_file(monkeypatch, tmp_path):
    file_path = tmp_path / "entry.txt"
    file_path.write_text("x", encoding="utf-8")
    calls = []
    monkeypatch.setattr(startup.platform, "system", lambda: "Linux")
    monkeypatch.setattr(startup.subprocess, "Popen", lambda args: calls.append(args))

    startup.open_folder(file_path)

    assert calls == [["xdg-open", str(tmp_path)]]


def test_run_regedit_is_noop_off_windows(monkeypatch):
    monkeypatch.setattr(startup, "is_windows", lambda: False)
    calls = []
    monkeypatch.setattr(startup.subprocess, "Popen", lambda *args, **kwargs: calls.append(args))
    startup.run_regedit_at_key("HKCU", startup.RUN_KEY)
    assert calls == []


def test_read_startup_folder_items_ignores_desktop_ini(monkeypatch, tmp_path):
    user_dir = tmp_path / "user"
    common_dir = tmp_path / "common"
    user_dir.mkdir()
    common_dir.mkdir()
    (user_dir / "desktop.ini").write_text("hidden", encoding="utf-8")
    (user_dir / "one.lnk").write_text("one", encoding="utf-8")
    (common_dir / "folder-entry").mkdir()

    monkeypatch.setattr(startup, "startup_user_folder", lambda: user_dir)
    monkeypatch.setattr(startup, "startup_common_folder", lambda: common_dir)

    items = startup.read_startup_folder_items()

    assert {item.name for item in items} == {"one.lnk", "folder-entry"}
    assert all(item.origin_kind == "folder" for item in items)


def test_read_disabled_folder_items_skips_invalid_metadata(monkeypatch, tmp_path):
    valid = tmp_path / "valid.json"
    valid.write_text(
        json.dumps(
            {
                "name": "example.lnk",
                "source": "Inicio usuario",
                "original_path": str(tmp_path / "Startup" / "example.lnk"),
                "backup_path": str(tmp_path / "backup_example.lnk"),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(startup, "disabled_folder_root", lambda: tmp_path)

    items = startup.read_disabled_folder_items()

    assert len(items) == 1
    assert items[0].name == "example.lnk"
    assert items[0].origin_kind == "disabled_folder"
    assert not items[0].active


def test_collect_startup_items_orders_active_before_disabled(monkeypatch):
    active_b = make_registry_item(name="B", source="Registro Z")
    active_a = make_registry_item(name="A", source="Registro A")
    disabled = make_registry_item(active=False, name="C", source="Registro A desactivado")

    monkeypatch.setattr(startup, "read_registry_run_items", lambda: [active_b, active_a])
    monkeypatch.setattr(startup, "read_startup_folder_items", lambda: [])
    monkeypatch.setattr(startup, "read_disabled_registry_items", lambda: [disabled])
    monkeypatch.setattr(startup, "read_disabled_folder_items", lambda: [])

    result = startup.collect_startup_items()
    assert [item.name for item in result] == ["A", "B", "C"]


def test_move_path_validates_source_and_destination(tmp_path):
    with pytest.raises(FileNotFoundError):
        startup._move_path(tmp_path / "missing", tmp_path / "target")

    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("source", encoding="utf-8")
    target.write_text("target", encoding="utf-8")
    with pytest.raises(FileExistsError):
        startup._move_path(source, target)


def test_move_path_falls_back_on_cross_device_error(monkeypatch, tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("content", encoding="utf-8")

    def cross_device(*_args):
        raise OSError(errno.EXDEV, "cross-device")

    monkeypatch.setattr(startup.os, "replace", cross_device)
    startup._move_path(source, target)

    assert target.read_text(encoding="utf-8") == "content"
    assert not source.exists()


def test_preserve_disabled_metadata_promotes_pending_file(tmp_path):
    pending = tmp_path / ".pending.json.tmp"
    metadata = tmp_path / "saved.json"
    pending.write_text("{}", encoding="utf-8")

    startup._preserve_disabled_folder_metadata(pending, metadata)

    assert metadata.exists()
    assert not pending.exists()


def test_disable_registry_validates_platform_and_root(monkeypatch):
    item = make_registry_item()
    monkeypatch.setattr(startup, "is_windows", lambda: False)
    with pytest.raises(RuntimeError, match="Windows"):
        startup.disable_registry_item(item)

    monkeypatch.setattr(startup, "is_windows", lambda: True)
    monkeypatch.setattr(startup, "REGISTRY_ROOTS", {})
    with pytest.raises(RuntimeError, match="Raíz"):
        startup.disable_registry_item(item)


def test_disable_registry_success_delegates_backup_then_delete(monkeypatch):
    item = make_registry_item()
    calls = []
    monkeypatch.setattr(startup, "is_windows", lambda: True)
    monkeypatch.setattr(startup, "REGISTRY_ROOTS", {"HKCU": object()})
    monkeypatch.setattr(
        startup, "create_disabled_registry_backup", lambda value: calls.append(("backup", value)) or "id"
    )
    monkeypatch.setattr(startup, "_delete_registry_value", lambda value: calls.append(("delete", value)))

    startup.disable_registry_item(item)
    assert calls == [("backup", item), ("delete", item)]


def test_enable_registry_validates_required_metadata(monkeypatch):
    item = make_registry_item(active=False, origin_kind="disabled_registry", disabled_id="")
    monkeypatch.setattr(startup, "is_windows", lambda: True)
    monkeypatch.setattr(startup, "REGISTRY_ROOTS", {"HKCU": object()})

    with pytest.raises(RuntimeError, match="identificador"):
        startup.enable_registry_item(item)


def test_enable_registry_success_restores_and_deletes_backup(monkeypatch):
    item = make_registry_item(active=False, origin_kind="disabled_registry", disabled_id="backup-1")
    calls = []
    monkeypatch.setattr(startup, "is_windows", lambda: True)
    monkeypatch.setattr(startup, "REGISTRY_ROOTS", {"HKCU": object()})
    monkeypatch.setattr(startup, "_registry_value_exists", lambda _item: False)
    monkeypatch.setattr(startup, "_write_registry_value", lambda value: calls.append(("write", value)))
    monkeypatch.setattr(
        startup,
        "delete_disabled_registry_backup",
        lambda disabled_id: calls.append(("cleanup", disabled_id)),
    )

    startup.enable_registry_item(item)
    assert calls == [("write", item), ("cleanup", "backup-1")]


def test_disable_and_enable_folder_happy_path(tmp_path, monkeypatch):
    startup_dir = tmp_path / "Startup"
    startup_dir.mkdir()
    original = startup_dir / "example.lnk"
    original.write_text("shortcut", encoding="utf-8")
    disabled_root = tmp_path / "disabled"
    monkeypatch.setattr(startup, "disabled_folder_root", lambda: disabled_root)

    startup.disable_folder_item(make_folder_item(original))

    metadata_files = list(disabled_root.glob("*.json"))
    backups = [path for path in disabled_root.iterdir() if path.suffix != ".json"]
    assert len(metadata_files) == 1
    assert len(backups) == 1
    assert not original.exists()

    item = make_folder_item(
        backups[0],
        active=False,
        origin_kind="disabled_folder",
        backup_path=str(backups[0]),
        metadata_path=str(metadata_files[0]),
    )
    startup.enable_folder_item(item)

    assert original.exists()
    assert original.read_text(encoding="utf-8") == "shortcut"
    assert not backups[0].exists()
    assert not metadata_files[0].exists()


def test_enable_folder_validates_backup_metadata_and_original(tmp_path):
    missing_backup = tmp_path / "missing.lnk"
    missing_metadata = tmp_path / "missing.json"
    item = make_folder_item(
        missing_backup,
        active=False,
        origin_kind="disabled_folder",
        backup_path=str(missing_backup),
        metadata_path=str(missing_metadata),
    )
    with pytest.raises(FileNotFoundError):
        startup.enable_folder_item(item)

    backup = tmp_path / "backup.lnk"
    backup.write_text("x", encoding="utf-8")
    item.backup_path = str(backup)
    with pytest.raises(FileNotFoundError):
        startup.enable_folder_item(item)

    metadata = tmp_path / "entry.json"
    metadata.write_text(json.dumps({"original_path": ""}), encoding="utf-8")
    item.metadata_path = str(metadata)
    with pytest.raises(RuntimeError, match="ruta original"):
        startup.enable_folder_item(item)

    original = tmp_path / "Startup" / "entry.lnk"
    original.parent.mkdir()
    original.write_text("already", encoding="utf-8")
    metadata.write_text(json.dumps({"original_path": str(original)}), encoding="utf-8")
    with pytest.raises(FileExistsError):
        startup.enable_folder_item(item)


def test_delete_disabled_registry_backup_is_noop_off_windows(monkeypatch):
    monkeypatch.setattr(startup, "is_windows", lambda: False)
    startup.delete_disabled_registry_backup("id")


def test_create_disabled_registry_backup_rejects_non_windows(monkeypatch):
    monkeypatch.setattr(startup, "is_windows", lambda: False)
    with pytest.raises(RuntimeError, match="Windows"):
        startup.create_disabled_registry_backup(make_registry_item())
