from __future__ import annotations
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
import logging
from xml.dom.minidom import Document as XMLDocument
import fitz
from docx import Document
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from pythonkni.core.tasks import WorkerCancelled

"""Domain has no dedicated value objects yet."""

__all__: list[str] = []
