from __future__ import annotations
import hashlib
import logging
import os
from dataclasses import dataclass
import psutil
import requests

@dataclass(frozen=True)
class ProcessDetails:
    pid: int
    name: str
    exe_path: str
    username: str
    create_time: float
@dataclass(frozen=True)
class VirusTotalResult:
    status: str
    exe_path: str
    file_hash: str
    positives: int = 0
    total: int = 0
    detections: tuple[str, ...] = ()
    response_text: str = ""
