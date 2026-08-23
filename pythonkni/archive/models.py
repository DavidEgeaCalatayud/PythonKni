from __future__ import annotations
import io
import os
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path
import py7zr
from py7zr import Py7zIO, WriterFactory
import logging

"""Domain has no dedicated value objects yet."""

__all__: list[str] = []
