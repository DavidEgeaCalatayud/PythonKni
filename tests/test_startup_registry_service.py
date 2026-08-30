from types import SimpleNamespace

import pytest

import pythonkni.startup.service as startup


class KeyContext:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False


def make_registry_item(**overrides):
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
        "key_path": startup.RUN_KEY,
        "value_name": "Example",
        "value_type": 1,
    }
    values.update(overrides)
    return startup.StartupItem(**values)


def test_read_registry_run_items_decodes_values(monkeypatch):
    class FakeWinreg:
        KEY_READ = 1

        @staticmethod
        def OpenKey(root, key_path, reserved, access):
            assert (root, key_path, reserved, access) == ("ROOT", startup.RUN_KEY, 0, 1)
            return KeyContext("run-key")

        @staticmethod
        def EnumValue(key, index):
            assert key == "run-key"
            if index == 0:
                return "BytesEntry", b"C:\\Tools\\bytes.exe", 1
            if index == 1:
                return "TextEntry", r"C:\Tools\text.exe --start", 2
            raise OSError("done")

    monkeypatch.setattr(startup, "winreg", FakeWinreg)
    monkeypatch.setattr(startup, "is_windows", lambda: True)
    monkeypatch.setattr(
        startup,
        "REGISTRY_LOCATIONS",
        [("HKCU", "Registro usuario", "HKEY_CURRENT_USER", startup.RUN_KEY)],
    )
    monkeypatch.setattr(startup, "REGISTRY_ROOTS", {"HKCU": "ROOT"})

    items = startup.read_registry_run_items()

    assert [item.name for item in items] == ["BytesEntry", "TextEntry"]
    assert items[0].command == r"C:\Tools\bytes.exe"
    assert items[1].value_type == 2
    assert all(item.origin_kind == "registry" for item in items)


@pytest.mark.parametrize("error", [FileNotFoundError(), PermissionError(), OSError()])
def test_read_registry_run_items_skips_unreadable_locations(monkeypatch, error):
    fake = SimpleNamespace(KEY_READ=1)

    def open_key(*_args, **_kwargs):
        raise error

    fake.OpenKey = open_key
    monkeypatch.setattr(startup, "winreg", fake)
    monkeypatch.setattr(startup, "is_windows", lambda: True)
    monkeypatch.setattr(
        startup,
        "REGISTRY_LOCATIONS",
        [("HKCU", "Registro usuario", "HKEY_CURRENT_USER", startup.RUN_KEY)],
    )
    monkeypatch.setattr(startup, "REGISTRY_ROOTS", {"HKCU": "ROOT"})
    assert startup.read_registry_run_items() == []


def test_read_registry_run_items_is_empty_off_windows(monkeypatch):
    monkeypatch.setattr(startup, "is_windows", lambda: False)
    assert startup.read_registry_run_items() == []


def test_read_disabled_registry_items_restores_metadata(monkeypatch):
    mapping = {
        "Name": "Example",
        "Command": r"C:\Tools\example.exe",
        "OriginalRoot": "HKCU",
        "OriginalKey": startup.RUN_KEY,
        "OriginalValueType": 1,
        "Source": "Registro usuario",
    }

    class FakeWinreg:
        HKEY_CURRENT_USER = "HKCU_ROOT"
        KEY_READ = 1

        @staticmethod
        def OpenKey(root, key_path, reserved, access):
            del reserved, access
            if root == "HKCU_ROOT":
                assert key_path == startup.DISABLED_REGISTRY_KEY
                return KeyContext("disabled-root")
            assert root == "disabled-root"
            assert key_path == "backup-1"
            return KeyContext("disabled-item")

        @staticmethod
        def EnumKey(root_key, index):
            assert root_key == "disabled-root"
            if index == 0:
                return "backup-1"
            raise OSError("done")

        @staticmethod
        def QueryValueEx(item_key, name):
            assert item_key == "disabled-item"
            return mapping[name], 1

    monkeypatch.setattr(startup, "winreg", FakeWinreg)
    monkeypatch.setattr(startup, "is_windows", lambda: True)

    items = startup.read_disabled_registry_items()

    assert len(items) == 1
    item = items[0]
    assert item.name == "Example"
    assert item.disabled_id == "backup-1"
    assert item.root_name == "HKCU"
    assert item.origin_kind == "disabled_registry"
    assert not item.active


def test_read_disabled_registry_items_skips_broken_backup(monkeypatch):
    class FakeWinreg:
        HKEY_CURRENT_USER = "ROOT"
        KEY_READ = 1

        @staticmethod
        def OpenKey(root, key_path, reserved, access):
            del reserved, access
            if root == "ROOT":
                return KeyContext("disabled-root")
            raise OSError("broken backup")

        @staticmethod
        def EnumKey(root_key, index):
            assert root_key == "disabled-root"
            if index == 0:
                return "broken"
            raise OSError("done")

    monkeypatch.setattr(startup, "winreg", FakeWinreg)
    monkeypatch.setattr(startup, "is_windows", lambda: True)
    assert startup.read_disabled_registry_items() == []


def test_create_disabled_registry_backup_writes_recovery_metadata(monkeypatch):
    writes = []

    class FakeWinreg:
        HKEY_CURRENT_USER = "ROOT"
        KEY_WRITE = 2
        REG_SZ = 1
        REG_DWORD = 4

        @staticmethod
        def CreateKeyEx(root, key_path, reserved, access):
            del reserved
            assert access == 2
            if root == "ROOT":
                assert key_path == startup.DISABLED_REGISTRY_KEY
                return KeyContext("backup-root")
            assert root == "backup-root"
            return KeyContext("backup-item")

        @staticmethod
        def SetValueEx(key, name, reserved, value_type, value):
            del reserved
            assert key == "backup-item"
            writes.append((name, value_type, value))

    monkeypatch.setattr(startup, "winreg", FakeWinreg)
    monkeypatch.setattr(startup, "is_windows", lambda: True)

    disabled_id = startup.create_disabled_registry_backup(make_registry_item())

    assert disabled_id
    written_names = {name for name, _value_type, _value in writes}
    assert written_names == {
        "Name",
        "Command",
        "Source",
        "OriginalRoot",
        "OriginalKey",
        "OriginalValueType",
        "DisabledAt",
    }


def test_create_disabled_registry_backup_cleans_partial_backup(monkeypatch):
    cleanup = []

    class FakeWinreg:
        HKEY_CURRENT_USER = "ROOT"
        KEY_WRITE = 2
        REG_SZ = 1
        REG_DWORD = 4

        @staticmethod
        def CreateKeyEx(root, key_path, reserved, access):
            del root, key_path, reserved, access
            return KeyContext("key")

        @staticmethod
        def SetValueEx(*_args):
            raise OSError("write failed")

    monkeypatch.setattr(startup, "winreg", FakeWinreg)
    monkeypatch.setattr(startup, "is_windows", lambda: True)
    monkeypatch.setattr(
        startup,
        "delete_disabled_registry_backup",
        lambda disabled_id, missing_ok=False: cleanup.append((disabled_id, missing_ok)),
    )

    with pytest.raises(OSError, match="write failed"):
        startup.create_disabled_registry_backup(make_registry_item())

    assert cleanup and cleanup[0][1] is True


def test_registry_value_helpers_read_write_and_delete(monkeypatch):
    calls = []

    class FakeWinreg:
        KEY_SET_VALUE = 2
        KEY_QUERY_VALUE = 4
        REG_SZ = 1

        @staticmethod
        def OpenKey(root, key_path, reserved, access):
            calls.append(("open", root, key_path, access))
            return KeyContext("key")

        @staticmethod
        def DeleteValue(key, name):
            calls.append(("delete", key, name))

        @staticmethod
        def QueryValueEx(key, name):
            calls.append(("query", key, name))
            return "command", 1

        @staticmethod
        def CreateKeyEx(root, key_path, reserved, access):
            calls.append(("create", root, key_path, access))
            return KeyContext("key")

        @staticmethod
        def SetValueEx(key, name, reserved, value_type, value):
            del reserved
            calls.append(("write", key, name, value_type, value))

    item = make_registry_item()
    monkeypatch.setattr(startup, "winreg", FakeWinreg)
    monkeypatch.setattr(startup, "REGISTRY_ROOTS", {"HKCU": "ROOT"})

    startup._delete_registry_value(item)
    assert startup._registry_value_exists(item)
    startup._write_registry_value(item)

    assert ("delete", "key", "Example") in calls
    assert ("query", "key", "Example") in calls
    assert any(call[0] == "write" and call[-1] == item.command for call in calls)


def test_registry_value_exists_returns_false_for_missing_value(monkeypatch):
    class FakeWinreg:
        KEY_QUERY_VALUE = 4

        @staticmethod
        def OpenKey(root, key_path, reserved, access):
            del root, key_path, reserved, access
            return KeyContext("key")

        @staticmethod
        def QueryValueEx(key, name):
            del key, name
            raise FileNotFoundError

    monkeypatch.setattr(startup, "winreg", FakeWinreg)
    monkeypatch.setattr(startup, "REGISTRY_ROOTS", {"HKCU": "ROOT"})
    assert not startup._registry_value_exists(make_registry_item())


def test_delete_disabled_registry_backup_honours_missing_ok(monkeypatch):
    class FakeWinreg:
        HKEY_CURRENT_USER = "ROOT"

        @staticmethod
        def DeleteKey(root, key_path):
            del root, key_path
            raise FileNotFoundError

    monkeypatch.setattr(startup, "winreg", FakeWinreg)
    monkeypatch.setattr(startup, "is_windows", lambda: True)

    startup.delete_disabled_registry_backup("missing", missing_ok=True)
    with pytest.raises(FileNotFoundError):
        startup.delete_disabled_registry_backup("missing", missing_ok=False)
