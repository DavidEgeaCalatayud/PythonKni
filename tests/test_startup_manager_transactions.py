import json
from pathlib import Path

import pytest

import pythonkni.startup.service as startup


def make_registry_item(**overrides):
    values = {
        "active": True,
        "name": "Example",
        "source": "Registro usuario",
        "command": r"C:\\Example\\app.exe",
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


def test_disable_registry_rolls_back_backup_when_delete_fails(monkeypatch):
    item = make_registry_item()
    calls = []

    monkeypatch.setattr(startup, "is_windows", lambda: True)
    monkeypatch.setattr(startup, "REGISTRY_ROOTS", {"HKCU": object()})
    monkeypatch.setattr(startup, "create_disabled_registry_backup", lambda _item: "backup-1")
    monkeypatch.setattr(
        startup,
        "delete_disabled_registry_backup",
        lambda disabled_id, missing_ok=False: calls.append((disabled_id, missing_ok)),
    )

    def fail_delete(_item):
        raise PermissionError("denied")

    monkeypatch.setattr(startup, "_delete_registry_value", fail_delete)

    with pytest.raises(PermissionError):
        startup.disable_registry_item(item)

    assert calls == [("backup-1", True)]


def test_enable_registry_rolls_back_restored_value_when_backup_delete_fails(monkeypatch):
    item = make_registry_item(active=False, origin_kind="disabled_registry", disabled_id="backup-1")
    calls = []

    monkeypatch.setattr(startup, "is_windows", lambda: True)
    monkeypatch.setattr(startup, "REGISTRY_ROOTS", {"HKCU": object()})
    monkeypatch.setattr(startup, "_registry_value_exists", lambda _item: False)
    monkeypatch.setattr(startup, "_write_registry_value", lambda _item: calls.append("restore"))
    monkeypatch.setattr(startup, "_delete_registry_value", lambda _item: calls.append("rollback"))

    def fail_backup_delete(_disabled_id, missing_ok=False):
        raise PermissionError("backup locked")

    monkeypatch.setattr(startup, "delete_disabled_registry_backup", fail_backup_delete)

    with pytest.raises(PermissionError):
        startup.enable_registry_item(item)

    assert calls == ["restore", "rollback"]


def test_enable_registry_refuses_to_overwrite_existing_value(monkeypatch):
    item = make_registry_item(active=False, origin_kind="disabled_registry", disabled_id="backup-1")

    monkeypatch.setattr(startup, "is_windows", lambda: True)
    monkeypatch.setattr(startup, "REGISTRY_ROOTS", {"HKCU": object()})
    monkeypatch.setattr(startup, "_registry_value_exists", lambda _item: True)

    with pytest.raises(FileExistsError):
        startup.enable_registry_item(item)


def test_disable_folder_rolls_back_move_when_metadata_commit_fails(tmp_path, monkeypatch):
    startup_folder = tmp_path / "Startup"
    startup_folder.mkdir()
    original = startup_folder / "example.lnk"
    original.write_text("shortcut", encoding="utf-8")
    disabled_root = tmp_path / "disabled"

    monkeypatch.setattr(startup, "disabled_folder_root", lambda: disabled_root)
    real_replace = startup.os.replace

    def fail_metadata_commit(source, destination):
        if str(source).endswith(".json.tmp") and str(destination).endswith(".json"):
            raise OSError("metadata commit failed")
        return real_replace(source, destination)

    monkeypatch.setattr(startup.os, "replace", fail_metadata_commit)

    with pytest.raises(OSError):
        startup.disable_folder_item(make_folder_item(original))

    assert original.exists()
    assert not list(disabled_root.glob("*.json"))
    assert not list(disabled_root.glob(".*.json.tmp"))
    assert not [path for path in disabled_root.iterdir() if path.name.endswith("_example.lnk")]


def test_disable_folder_metadata_write_failure_does_not_move_original(tmp_path, monkeypatch):
    startup_folder = tmp_path / "Startup"
    startup_folder.mkdir()
    original = startup_folder / "example.lnk"
    original.write_text("shortcut", encoding="utf-8")
    disabled_root = tmp_path / "disabled"

    monkeypatch.setattr(startup, "disabled_folder_root", lambda: disabled_root)

    def fail_metadata_write(_path, _metadata):
        raise OSError("disk full")

    monkeypatch.setattr(startup, "_write_pending_metadata", fail_metadata_write)

    with pytest.raises(OSError):
        startup.disable_folder_item(make_folder_item(original))

    assert original.exists()
    assert not [path for path in disabled_root.iterdir() if path.name.endswith("_example.lnk")]


def test_enable_folder_rolls_back_move_when_metadata_delete_fails(tmp_path, monkeypatch):
    disabled_root = tmp_path / "disabled"
    disabled_root.mkdir()
    original = tmp_path / "Startup" / "example.lnk"
    backup = disabled_root / "backup_example.lnk"
    backup.write_text("shortcut", encoding="utf-8")
    metadata_path = disabled_root / "backup.json"
    metadata_path.write_text(
        json.dumps(
            {
                "name": "example.lnk",
                "source": "Inicio usuario",
                "original_path": str(original),
                "backup_path": str(backup),
            }
        ),
        encoding="utf-8",
    )

    item = make_folder_item(
        backup,
        active=False,
        origin_kind="disabled_folder",
        file_path=str(backup),
        backup_path=str(backup),
        metadata_path=str(metadata_path),
    )

    real_unlink = Path.unlink

    def fail_metadata_unlink(path, *args, **kwargs):
        if path == metadata_path:
            raise PermissionError("metadata locked")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_metadata_unlink)

    with pytest.raises(PermissionError):
        startup.enable_folder_item(item)

    assert backup.exists()
    assert not original.exists()
    assert metadata_path.exists()
