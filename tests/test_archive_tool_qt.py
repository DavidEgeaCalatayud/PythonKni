import threading
import time
import zipfile
from pathlib import Path

from PyQt5.QtWidgets import QMessageBox, QPushButton

from tools import archive_tool, zip_7zip_utils
from tools.archive_tool import Tool as ArchiveTool


def test_archive_tool_exposes_all_compression_actions(qtbot):
    tool = ArchiveTool()
    qtbot.addWidget(tool)
    labels = {button.text() for button in tool.findChildren(QPushButton)}
    assert {"Extraer ZIP", "Crear ZIP", "Extraer 7z", "Crear 7z"}.issubset(labels)
    assert "Cancelar" in labels


def test_archive_tool_runs_extraction_in_background_and_can_cancel(monkeypatch, qtbot, tmp_path):
    archive_path = tmp_path / "sample.zip"
    archive_path.write_bytes(b"unused")
    started = threading.Event()

    def blocking_task(worker, _source, _destination):
        started.set()
        while True:
            worker.check_cancelled()
            time.sleep(0.01)

    monkeypatch.setattr(archive_tool, "extract_zip_task", blocking_task)
    monkeypatch.setattr(
        archive_tool.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(archive_path), ""),
    )

    tool = ArchiveTool()
    qtbot.addWidget(tool)
    tool.extract_zip_action()

    assert started.wait(1)
    assert tool.worker is not None and tool.worker.isRunning()
    assert tool.btn_cancel.isEnabled()
    assert all(not button.isEnabled() for button in tool._action_buttons)

    tool.cancel_operation()
    qtbot.waitUntil(lambda: tool.worker is None, timeout=2000)

    assert tool.status.text() == "Operación cancelada"
    assert all(button.isEnabled() for button in tool._action_buttons)


def test_create_and_extract_zip_round_trip(monkeypatch, tmp_path):
    source_a = tmp_path / "a.txt"
    source_b = tmp_path / "b.txt"
    source_a.write_text("alpha", encoding="utf-8")
    source_b.write_text("beta", encoding="utf-8")
    archive = tmp_path / "sample.zip"

    monkeypatch.setattr(
        zip_7zip_utils.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(source_a), str(source_b)], ""),
    )
    monkeypatch.setattr(
        zip_7zip_utils.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(archive), ""),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    zip_7zip_utils.create_zip()

    with zipfile.ZipFile(archive, "r") as zip_ref:
        assert set(zip_ref.namelist()) == {"a.txt", "b.txt"}
        assert zip_ref.read("a.txt") == b"alpha"
        assert zip_ref.read("b.txt") == b"beta"

    monkeypatch.setattr(
        zip_7zip_utils.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(archive), ""),
    )
    zip_7zip_utils.extract_zip()

    extracted = Path(str(archive).replace(".zip", "_extracted"))
    assert (extracted / "a.txt").read_text(encoding="utf-8") == "alpha"
    assert (extracted / "b.txt").read_text(encoding="utf-8") == "beta"


def test_create_and_extract_7z_round_trip(monkeypatch, tmp_path):
    source = tmp_path / "payload.txt"
    source.write_text("contenido 7z", encoding="utf-8")
    archive = tmp_path / "sample.7z"

    monkeypatch.setattr(
        zip_7zip_utils.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(source)], ""),
    )
    monkeypatch.setattr(
        zip_7zip_utils.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(archive), ""),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    zip_7zip_utils.create_7z()
    assert archive.exists() and archive.stat().st_size > 0

    monkeypatch.setattr(
        zip_7zip_utils.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(archive), ""),
    )
    zip_7zip_utils.extract_7z()

    extracted = Path(str(archive).replace(".7z", "_extracted"))
    assert (extracted / "payload.txt").read_text(encoding="utf-8") == "contenido 7z"
