from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class NetworkInterface:
    name: str
    address: str
    netmask: str
    cidr: str


@dataclass(frozen=True)
class DiscoveredHost:
    ip: str
    hostname: str
    mac: str


@dataclass(frozen=True)
class OpenPort:
    port: int
    service: str


@dataclass(frozen=True)
class ServiceFingerprint:
    host: str
    ip: str
    port: int
    protocol: str
    transport: str = "tcp"
    product: str = ""
    version: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def endpoint(self) -> str:
        return f"{self.ip or self.host}:{self.port}"
