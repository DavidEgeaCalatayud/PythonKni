from __future__ import annotations

from dataclasses import dataclass


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
