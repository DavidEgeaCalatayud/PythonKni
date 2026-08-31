from PyQt5.QtCore import QObject, pyqtSignal

from pythonkni.wifi import window as wifi_window


class FakeWorker(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(object)
    cancelled = pyqtSignal()
    finished = pyqtSignal()

    instances = []

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args
        self.kwargs = kwargs
        self.running = False
        self.cancelled_requested = False
        self.__class__.instances.append(self)

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def cancel(self):
        self.cancelled_requested = True


def _tool_without_autoload(qtbot, monkeypatch):
    monkeypatch.setattr(wifi_window.Tool, "refresh_wifi_data", lambda self: False)
    tool = wifi_window.Tool()
    qtbot.addWidget(tool)
    return tool


def test_loading_state_and_show_data(qtbot, monkeypatch):
    tool = _tool_without_autoload(qtbot, monkeypatch)

    tool._set_loading(True)
    assert not tool.btn_refresh.isEnabled()
    assert tool.btn_cancel.isEnabled()
    assert tool.table.rowCount() == 1
    assert tool.table.item(0, 0).text() == "Cargando perfiles Wi-Fi..."

    tool.show_wifi_data([("Office", "secret"), ("Guest", "")])
    assert tool.table.rowCount() == 2
    assert tool.table.item(0, 0).text() == "Office"
    assert tool.table.item(0, 1).text() == "secret"
    assert tool.table.item(1, 0).text() == "Guest"

    tool._set_loading(False)
    assert tool.btn_refresh.isEnabled()
    assert not tool.btn_cancel.isEnabled()


def test_loading_active_and_cancel_noop_then_running(qtbot, monkeypatch):
    tool = _tool_without_autoload(qtbot, monkeypatch)
    assert not tool._loading_active()
    tool.cancel_loading()

    worker = FakeWorker()
    tool.worker = worker
    assert not tool._loading_active()
    tool.cancel_loading()
    assert not worker.cancelled_requested

    worker.running = True
    tool.btn_cancel.setEnabled(True)
    assert tool._loading_active()
    tool.cancel_loading()
    assert worker.cancelled_requested
    assert not tool.btn_cancel.isEnabled()
    worker.running = False
    tool.worker = None


def test_refresh_wires_worker_and_rejects_overlap(qtbot, monkeypatch):
    FakeWorker.instances.clear()
    monkeypatch.setattr(wifi_window, "Worker", FakeWorker)
    monkeypatch.setattr(
        wifi_window.Tool,
        "start_managed_worker",
        lambda self, worker, cancel=None: worker.start(),
    )
    monkeypatch.setattr(wifi_window.Tool, "refresh_wifi_data", lambda self: False)
    tool = wifi_window.Tool()
    qtbot.addWidget(tool)
    monkeypatch.undo()

    monkeypatch.setattr(wifi_window, "Worker", FakeWorker)
    monkeypatch.setattr(
        tool,
        "start_managed_worker",
        lambda worker, cancel=None: worker.start(),
    )

    assert tool.refresh_wifi_data()
    worker = FakeWorker.instances[-1]
    assert worker.args[0] is wifi_window._load_wifi_task
    assert worker.running
    assert tool.worker is worker
    assert not tool.btn_refresh.isEnabled()
    assert tool.btn_cancel.isEnabled()

    assert not tool.refresh_wifi_data()
    assert len(FakeWorker.instances) == 1

    worker.result.emit([("Office", "secret")])
    assert tool.table.item(0, 0).text() == "Office"
    worker.running = False
    worker.finished.emit()
    assert tool.worker is None
    assert tool.btn_refresh.isEnabled()
    assert not tool.btn_cancel.isEnabled()


def test_loading_cancelled_and_plain_failure(qtbot, monkeypatch):
    tool = _tool_without_autoload(qtbot, monkeypatch)
    feedback = []
    monkeypatch.setattr(
        wifi_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )

    tool.on_loading_cancelled()
    assert tool.table.item(0, 0).text() == "Carga cancelada"

    tool.on_loading_failed("plain diagnostic")
    assert tool.table.item(0, 0).text() == "No se pudieron cargar los perfiles Wi-Fi"
    assert tool.table.item(0, 1).text() == "Consulte los detalles del error"
    assert feedback[-1][1]["details"] == "plain diagnostic"


def test_worker_finished_ignores_stale_and_clears_current(qtbot, monkeypatch):
    tool = _tool_without_autoload(qtbot, monkeypatch)
    current = FakeWorker()
    stale = FakeWorker()
    tool.worker = current
    tool._set_loading(True)

    tool._on_worker_finished(stale)
    assert tool.worker is current
    assert not tool.btn_refresh.isEnabled()

    tool._on_worker_finished(current)
    assert tool.worker is None
    assert tool.btn_refresh.isEnabled()
    assert not tool.btn_cancel.isEnabled()
