from __future__ import annotations

import threading
from pathlib import Path

import pytest

from pythonkni.secure_transfer.models import (
    BackendInfo,
    ForwardPortRequest,
    ReceiveFilesRequest,
    SendPathRequest,
    SendTextRequest,
    ServePortRequest,
    TransferEventKind,
    TransferMode,
)
from pythonkni.secure_transfer.service import SecureTransferService

TOKEN = "tc" + "B" * 32


class FakeBackend:
    def __init__(self):
        self.calls = []

    def info(self):
        self.calls.append(("info",))
        return BackendInfo("Tailcat", "0.5.0", Path("tailcat.exe"), True)

    def parse_address(self, token):
        self.calls.append(("parse", token))
        return {"token": token}

    def receive_files(self, destination, *, accept_directories, stop_event, on_ready=None):
        self.calls.append(("receive_files", destination, accept_directories))
        if on_ready:
            on_ready(TOKEN)

    def send_path(self, token, source, *, recursive, stop_event):
        self.calls.append(("send_path", token, source, recursive))

    def receive_text(self, *, stop_event, on_ready=None):
        self.calls.append(("receive_text",))
        if on_ready:
            on_ready(TOKEN)
        return "hello"

    def send_text(self, token, text, *, stop_event):
        self.calls.append(("send_text", token, text))

    def serve_port(self, port, *, stop_event, on_ready=None):
        self.calls.append(("serve_port", port))
        if on_ready:
            on_ready(TOKEN)

    def forward_port(self, token, *, remote_port, local_port, stop_event, on_ready=None):
        self.calls.append(("forward_port", token, remote_port, local_port))
        if on_ready:
            on_ready()


@pytest.fixture
def setup_service():
    fake = FakeBackend()
    return SecureTransferService(fake), fake


def test_backend_info_and_validate_token(setup_service):
    service, fake = setup_service
    assert service.backend_info().version == "0.5.0"
    assert service.validate_token(TOKEN) == {"token": TOKEN}
    assert ("parse", TOKEN) in fake.calls


def test_receive_file_validates_destination_and_emits_ready(tmp_path, setup_service):
    service, fake = setup_service
    events = []
    result = service.receive_files(
        ReceiveFilesRequest(tmp_path),
        stop_event=threading.Event(),
        on_event=events.append,
    )
    assert result.mode == TransferMode.FILE
    assert result.destination == tmp_path
    assert any(event.kind == TransferEventKind.READY and event.token == TOKEN for event in events)
    assert ("receive_files", tmp_path, False) in fake.calls


def test_receive_folder_marks_directory_mode(tmp_path, setup_service):
    service, fake = setup_service
    events = []
    result = service.receive_files(
        ReceiveFilesRequest(tmp_path, accept_directories=True),
        stop_event=threading.Event(),
        on_event=events.append,
    )
    assert result.mode == TransferMode.FOLDER
    ready = next(event for event in events if event.kind == TransferEventKind.READY)
    assert "carpetas" in ready.message
    assert ("receive_files", tmp_path, True) in fake.calls


def test_receive_files_rejects_missing_or_non_directory(tmp_path, setup_service):
    service, _fake = setup_service
    with pytest.raises(ValueError, match="no existe"):
        service.receive_files(
            ReceiveFilesRequest(tmp_path / "missing"),
            stop_event=threading.Event(),
        )
    file_path = tmp_path / "x"
    file_path.write_text("x")
    with pytest.raises(ValueError, match="carpeta"):
        service.receive_files(ReceiveFilesRequest(file_path), stop_event=threading.Event())


def test_send_file_and_folder(tmp_path, setup_service):
    service, fake = setup_service
    file_path = tmp_path / "x.txt"
    file_path.write_text("hello")
    result = service.send_path(
        SendPathRequest(TOKEN, file_path),
        stop_event=threading.Event(),
    )
    assert result.mode == TransferMode.FILE
    assert result.bytes_transferred == 5
    assert ("send_path", TOKEN, file_path, False) in fake.calls
    assert not any(call[0] == "parse" for call in fake.calls)

    folder = tmp_path / "folder"
    folder.mkdir()
    result = service.send_path(SendPathRequest(TOKEN, folder), stop_event=threading.Event())
    assert result.mode == TransferMode.FOLDER
    assert result.bytes_transferred is None
    assert ("send_path", TOKEN, folder, True) in fake.calls


def test_send_path_rejects_missing_source(tmp_path, setup_service):
    service, _fake = setup_service
    with pytest.raises(ValueError, match="no existe"):
        service.send_path(
            SendPathRequest(TOKEN, tmp_path / "missing"),
            stop_event=threading.Event(),
        )


def test_receive_and_send_text_emit_events(setup_service):
    service, fake = setup_service
    events = []
    result = service.receive_text(stop_event=threading.Event(), on_event=events.append)
    assert result.mode == TransferMode.TEXT
    assert result.bytes_transferred == 5
    assert any(event.kind == TransferEventKind.READY for event in events)
    assert any(event.kind == TransferEventKind.TEXT and event.text == "hello" for event in events)

    events.clear()
    result = service.send_text(
        SendTextRequest(TOKEN, "á"),
        stop_event=threading.Event(),
        on_event=events.append,
    )
    assert result.bytes_transferred == len("á".encode())
    assert ("send_text", TOKEN, "á") in fake.calls
    assert not any(call[0] == "parse" for call in fake.calls)


def test_send_text_rejects_empty(setup_service):
    service, _fake = setup_service
    with pytest.raises(ValueError, match="texto"):
        service.send_text(SendTextRequest(TOKEN, ""), stop_event=threading.Event())


def test_receive_text_returns_cancelled_result_if_event_set(setup_service):
    service, fake = setup_service

    def cancelled_receive(*, stop_event, on_ready=None):
        stop_event.set()
        return ""

    fake.receive_text = cancelled_receive
    result = service.receive_text(stop_event=threading.Event())
    assert result.message.endswith("detenida.")


def test_serve_and_forward_ports(setup_service):
    service, fake = setup_service
    events = []
    result = service.serve_port(
        ServePortRequest(8080),
        stop_event=threading.Event(),
        on_event=events.append,
    )
    assert result.mode == TransferMode.SERVE_PORT
    assert any(event.token == TOKEN for event in events)
    assert ("serve_port", 8080) in fake.calls

    events.clear()
    result = service.forward_port(
        ForwardPortRequest(TOKEN, 8080, 18080),
        stop_event=threading.Event(),
        on_event=events.append,
    )
    assert result.mode == TransferMode.FORWARD_PORT
    assert ("forward_port", TOKEN, 8080, 18080) in fake.calls
    assert any("127.0.0.1:18080" in event.message for event in events)
    assert not any(call[0] == "parse" for call in fake.calls)


def test_emit_is_optional(setup_service):
    service, _fake = setup_service
    service._emit(None, TransferEventKind.LOG, "ignored")
