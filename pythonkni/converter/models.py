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

@dataclass(frozen=True)
class ConversionResult:
    """Structured result for converter operations."""

    success: bool
    outputs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()

    @classmethod
    def completed(
        cls,
        outputs: list[str] | tuple[str, ...],
        *,
        warnings: list[str] | tuple[str, ...] = (),
    ) -> "ConversionResult":
        return cls(True, tuple(outputs), tuple(warnings), ())

    @classmethod
    def failed(
        cls,
        *failures: str,
        warnings: list[str] | tuple[str, ...] = (),
    ) -> "ConversionResult":
        return cls(False, (), tuple(warnings), tuple(failures))
