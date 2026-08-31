from pathlib import Path

from PyQt5.QtWidgets import QMessageBox

from pythonkni.temp_cleaner import window as cleaner_window
from pythonkni.temp_cleaner.models import CleanPreview, CleanResult, CleanTarget


def _tool(qtbot):
    tool = cleaner_window.Tool()
    qtbot.addWidget(tool)
    return tool


def test_preview_collects_selected_target_groups(qtbot, monkeypatch):
    tool = _tool(qtbot)
    tool.chk_temp.setChecked(True)
    tool.chk_cache.setChecked(True)
    tool.chk_logs.setChecked(True)
    temp = CleanTarget("Temp", Path("C:/Temp"))
    cache = CleanTarget("Cache", Path("C:/Cache"))
    logs = CleanTarget("Logs", Path("C:/Logs"))
    monkeypatch.setattr(cleaner_window, "get_temp_targets", lambda: [temp])
    monkeypatch.setattr(cleaner_window, "get_browser_cache_targets", lambda: [cache])
    monkeypatch.setattr(cleaner_window, "get_log_targets", lambda: [logs])
    captured = []
    monkeypatch.setattr(
        cleaner_window,
        "build_preview",
        lambda targets: captured.append(list(targets)) or CleanPreview(),
    )
    info = []
    monkeypatch.setattr(
        cleaner_window.QMessageBox,
        "information",
        lambda *args: info.append(args),
    )

    tool.clean_action()

    assert captured == [[temp, cache, logs]]
    assert info[-1][1] == "Sin rutas seguras"


def test_preview_failure_reports_error(qtbot, monkeypatch):
    tool = _tool(qtbot)
    error = RuntimeError("preview failed")
    monkeypatch.setattr(
        cleaner_window,
        "get_temp_targets",
        lambda: (_ for _ in ()).throw(error),
    )
    feedback = []
    monkeypatch.setattr(
        cleaner_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )

    tool.clean_action()

    assert feedback[-1][0][1] == "Vista previa de limpieza"
    assert feedback[-1][1]["error"] is error


def test_declined_cleanup_reports_simulation_without_mutation(qtbot, monkeypatch):
    tool = _tool(qtbot)
    target = CleanTarget("Temp", Path("C:/Temp"))
    monkeypatch.setattr(
        cleaner_window,
        "build_preview",
        lambda _targets: CleanPreview([target], items=3, bytes=2 * 1024 * 1024),
    )
    monkeypatch.setattr(cleaner_window, "get_temp_targets", lambda: [target])
    questions = []
    monkeypatch.setattr(
        cleaner_window.QMessageBox,
        "question",
        lambda *args: questions.append(args) or QMessageBox.No,
    )
    cleaned = []
    monkeypatch.setattr(cleaner_window, "clean_targets", lambda targets: cleaned.append(targets))
    info = []
    monkeypatch.setattr(
        cleaner_window.QMessageBox,
        "information",
        lambda *args: info.append(args),
    )

    tool.clean_action()

    assert "Elementos detectados: 3" in questions[-1][2]
    assert "2.00 MB" in questions[-1][2]
    assert cleaned == []
    assert info[-1][1] == "Simulacion completada"


def test_confirmed_cleanup_reports_counts(qtbot, monkeypatch):
    tool = _tool(qtbot)
    target = CleanTarget("Temp", Path("C:/Temp"))
    monkeypatch.setattr(cleaner_window, "get_temp_targets", lambda: [target])
    monkeypatch.setattr(
        cleaner_window,
        "build_preview",
        lambda _targets: CleanPreview([target], items=5, bytes=1024),
    )
    monkeypatch.setattr(
        cleaner_window.QMessageBox,
        "question",
        lambda *args: QMessageBox.Yes,
    )
    monkeypatch.setattr(
        cleaner_window,
        "clean_targets",
        lambda targets: CleanResult(deleted=4, failed=1),
    )
    info = []
    monkeypatch.setattr(
        cleaner_window.QMessageBox,
        "information",
        lambda *args: info.append(args),
    )

    tool.clean_action()

    assert info[-1][1] == "Limpieza completada"
    assert "4 archivos/carpetas" in info[-1][2]
    assert "1 elementos" in info[-1][2]


def test_cleanup_failure_reports_error(qtbot, monkeypatch):
    tool = _tool(qtbot)
    target = CleanTarget("Temp", Path("C:/Temp"))
    monkeypatch.setattr(cleaner_window, "get_temp_targets", lambda: [target])
    monkeypatch.setattr(
        cleaner_window,
        "build_preview",
        lambda _targets: CleanPreview([target], items=1, bytes=1),
    )
    monkeypatch.setattr(
        cleaner_window.QMessageBox,
        "question",
        lambda *args: QMessageBox.Yes,
    )
    error = OSError("locked")
    monkeypatch.setattr(
        cleaner_window,
        "clean_targets",
        lambda _targets: (_ for _ in ()).throw(error),
    )
    feedback = []
    monkeypatch.setattr(
        cleaner_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )

    tool.clean_action()

    assert feedback[-1][0][1] == "Limpieza de temporales"
    assert feedback[-1][1]["error"] is error
