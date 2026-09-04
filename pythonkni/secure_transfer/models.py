from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class TransferMode(str, Enum):
    FILE = "file"
    FOLDER = "folder"
    TEXT = "text"
    SERVE_PORT = "serve_port"
    FORWARD_PORT = "forward_port"


class TransferEventKind(str, Enum):
    STATUS = "status"
    READY = "ready"
    LOG = "log"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class BackendInfo:
    name: str
    version: str
    executable: Path
    supported: bool


@dataclass(frozen=True, slots=True)
class TransferEvent:
    kind: TransferEventKind
    message: str
    token: str = ""
    text: str = ""


@dataclass(frozen=True, slots=True)
class TransferResult:
    mode: TransferMode
    message: str
    source: Path | None = None
    destination: Path | None = None
    bytes_transferred: int | None = None


@dataclass(frozen=True, slots=True)
class ReceiveFilesRequest:
    destination: Path
    accept_directories: bool = False


@dataclass(frozen=True, slots=True)
class SendPathRequest:
    token: str
    source: Path


@dataclass(frozen=True, slots=True)
class SendTextRequest:
    token: str
    text: str


@dataclass(frozen=True, slots=True)
class ServePortRequest:
    local_port: int


@dataclass(frozen=True, slots=True)
class ForwardPortRequest:
    token: str
    remote_port: int
    local_port: int
