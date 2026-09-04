from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from .models import PcapCaptureResult


class PacketCaptureError(RuntimeError):
    """Raised when the optional Windows pktmon capture backend cannot complete."""


def pktmon_path() -> str | None:
    if os.name != "nt":
        return None
    return shutil.which("pktmon")


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PacketCaptureError(f"Could not execute pktmon: {error}") from error


def _message(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "pktmon returned an error").strip()


class PktmonCapture:
    """Explicit Windows packet capture using the in-box Packet Monitor utility.

    Pktmon owns a system-wide capture session. PythonKni never clears user filters and
    never stops another session after a failed start. A successful start is the only
    state that gives this object ownership of the matching stop/convert operation.
    """

    def __init__(self, capture_dir: Path) -> None:
        self.capture_dir = Path(capture_dir)
        self.active = False
        self.etl_path: Path | None = None
        self.pcapng_path: Path | None = None

    @property
    def available(self) -> bool:
        return pktmon_path() is not None

    def start(self) -> Path:
        executable = pktmon_path()
        if executable is None:
            raise PacketCaptureError("pktmon is not available on this Windows installation.")
        if self.active:
            raise PacketCaptureError("A PythonKni packet capture is already active.")

        self.capture_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        etl_path = self.capture_dir / f"network-monitor-{stamp}.etl"
        result = _run(
            [
                executable,
                "start",
                "--capture",
                "--comp",
                "nics",
                "--pkt-size",
                "0",
                "--file-name",
                str(etl_path),
            ]
        )
        if result.returncode != 0:
            raise PacketCaptureError(_message(result))

        self.active = True
        self.etl_path = etl_path
        self.pcapng_path = etl_path.with_suffix(".pcapng")
        return etl_path

    def stop(self) -> PcapCaptureResult:
        executable = pktmon_path()
        if executable is None:
            raise PacketCaptureError("pktmon is not available on this Windows installation.")
        if not self.active or self.etl_path is None or self.pcapng_path is None:
            raise PacketCaptureError("No PythonKni packet capture is active.")

        stop_result = _run([executable, "stop"])
        self.active = False
        if stop_result.returncode != 0:
            raise PacketCaptureError(_message(stop_result))

        convert_result = _run(
            [
                executable,
                "etl2pcap",
                str(self.etl_path),
                "--out",
                str(self.pcapng_path),
            ]
        )
        if convert_result.returncode != 0:
            raise PacketCaptureError(_message(convert_result))

        return PcapCaptureResult(
            etl_path=str(self.etl_path),
            pcapng_path=str(self.pcapng_path),
        )
