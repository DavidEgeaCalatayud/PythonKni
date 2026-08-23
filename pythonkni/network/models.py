from __future__ import annotations
import csv
import ipaddress
import json
import logging
import platform
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import psutil

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
