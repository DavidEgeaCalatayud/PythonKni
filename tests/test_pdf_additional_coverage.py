from pathlib import Path
from types import SimpleNamespace

import pytest
from PyPDF2 import PdfWriter

from pythonkni.pdf import service as pdf


class RecordingWorker:
    def __init__(self):
        self.progress = []
        self.cancelled = False

    def check_cancelled(self):
        if self.cancelled:
            from pythonkni.core.tasks import WorkerCancelled

            raise WorkerCancelled()

    def report_progress(self, payload):
        self.progress.append(payload)


class TextPage:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


def test_pdf_transaction_rejects_other_directory_and_missing_stage(tmp_path):
    transaction = pdf._PdfOutputTransaction(tmp_path / "out")
    try:
        with pytest.raises(ValueError, match="compartir carpeta"):
            transaction.stage_for(tmp_path / "other" / "result.pdf")
    finally:
        transaction.abort()

    output = tmp_path / "result.pdf"
    output.write_bytes(b"old")
    transaction = pdf._PdfOutputTransaction(tmp_path)
    transaction.stage_for(output)
    with pytest.raises(FileNotFoundError, match="resultado temporal"):
        transaction.commit()
    transaction.abort()

    assert output.read_bytes() == b"old"
    assert not transaction.staging_dir.exists()


def test_pdf_transaction_success_replaces_existing_and_abort_after_commit_is_noop(tmp_path):
    output = tmp_path / "result.pdf"
    output.write_bytes(b"old")
    transaction = pdf._PdfOutputTransaction(tmp_path)
    stage = transaction.stage_for(output)
    stage.write_bytes(b"new")

    assert transaction.commit() == [str(output)]
    transaction.abort()

    assert output.read_bytes() == b"new"
    assert not transaction.staging_dir.exists()


def test_require_pypdf_available_reflects_dependencies(monkeypatch):
    assert pdf.require_pypdf_available()

    monkeypatch.setattr(pdf, "PdfReader", None)
    assert not pdf.require_pypdf_available()


def test_parse_page_list_reversed_range_and_page_spec_empty():
    assert pdf.parse_page_list("4-2", max_pages=5) == [1, 2, 3]

    with pytest.raises(ValueError, match="rangos válidos"):
        pdf.parse_page_spec(" , ", max_pages=5)


def test_open_reader_requires_library(monkeypatch):
    monkeypatch.setattr(pdf, "PdfReader", None)
    with pytest.raises(RuntimeError, match="PyPDF2"):
        pdf._open_reader("file.pdf")


def test_open_reader_surfaces_empty_password_decrypt_exception(monkeypatch):
    class EncryptedReader:
        is_encrypted = True

        def decrypt(self, _password):
            raise RuntimeError("decrypt failed")

    monkeypatch.setattr(pdf, "PdfReader", lambda _src: EncryptedReader())

    with pytest.raises(ValueError, match="no se pudo descifrar"):
        pdf._open_reader("file.pdf")


def test_temp_helpers_remove_missing_and_atomic_write_cleanup(monkeypatch, tmp_path):
    missing = tmp_path / "missing.tmp"
    pdf._remove_quietly(str(missing))

    output = tmp_path / "result.pdf"

    class BrokenWriter:
        def write(self, _file):
            raise OSError("write failed")

    with pytest.raises(OSError, match="write failed"):
        pdf._write_writer_atomic(BrokenWriter(), str(output))

    assert not Path(str(output) + ".pythonkni.tmp").exists()
    assert not output.exists()


def test_progress_supports_plain_and_detailed_payloads():
    worker = RecordingWorker()

    pdf._progress(worker, "plain")
    pdf._progress(worker, "half", current=1, total=2)

    assert worker.progress == [
        {"message": "plain"},
        {"message": "half", "percent": 50, "current": 1, "total": 2},
    ]


def test_split_ranges_requires_spec(monkeypatch, tmp_path):
    reader = SimpleNamespace(pages=[object()])
    monkeypatch.setattr(pdf, "_open_reader", lambda _src: reader)

    with pytest.raises(ValueError, match="Indique rangos"):
        pdf.split_pdf_task(
            RecordingWorker(),
            "source.pdf",
            str(tmp_path),
            "ranges",
            "",
        )


def test_preview_text_task_returns_text_and_empty_fallback(monkeypatch):
    worker = RecordingWorker()
    monkeypatch.setattr(
        pdf,
        "_open_reader",
        lambda _src: SimpleNamespace(pages=[TextPage(" hello "), TextPage(None)]),
    )

    result = pdf.preview_text_task(worker, "source.pdf", limit=2)

    assert result["pages"] == 2
    assert "hello" in result["preview"]
    assert "--- Página 2 ---" in result["preview"]
    assert worker.progress[-1]["percent"] == 100

    monkeypatch.setattr(
        pdf,
        "_open_reader",
        lambda _src: SimpleNamespace(pages=[]),
    )
    empty = pdf.preview_text_task(RecordingWorker(), "source.pdf", limit=2)
    assert empty["pages"] == 0
    assert "No se ha detectado texto" in empty["preview"]


def test_ocr_available_reports_missing_tesseract_runtime(monkeypatch):
    import pytesseract

    monkeypatch.setattr(
        pytesseract,
        "get_tesseract_version",
        lambda: (_ for _ in ()).throw(RuntimeError("missing binary")),
    )

    available, message = pdf.ocr_available()

    assert not available
    assert "Tesseract no está accesible" in message


def test_ocr_page_handles_empty_images_and_extracts_text(monkeypatch):
    import pdf2image
    import pytesseract

    worker = RecordingWorker()
    monkeypatch.setattr(pdf2image, "convert_from_path", lambda *_args, **_kwargs: [])
    assert pdf.ocr_page(worker, "source.pdf", 1) == ""

    image = object()
    monkeypatch.setattr(pdf2image, "convert_from_path", lambda *_args, **_kwargs: [image])
    monkeypatch.setattr(
        pytesseract,
        "image_to_string",
        lambda value: " OCR text " if value is image else "",
    )

    assert pdf.ocr_page(worker, "source.pdf", 1) == "OCR text"


def test_extract_text_disables_unavailable_ocr_and_writes_single_file(monkeypatch, tmp_path):
    output = tmp_path / "text.md"
    monkeypatch.setattr(
        pdf,
        "_open_reader",
        lambda _src: SimpleNamespace(pages=[TextPage("hello"), TextPage("")]),
    )
    monkeypatch.setattr(pdf, "ocr_available", lambda: (False, "OCR missing"))

    result = pdf.extract_text_task(
        RecordingWorker(),
        "source.pdf",
        "",
        False,
        True,
        True,
        True,
        60,
        None,
        str(output),
    )

    assert result["created_files"] == [str(output)]
    assert result["empty_pages"] == 1
    assert result["empty_ratio"] == 50
    assert result["ocr_warning"] == "OCR missing"
    assert "[Texto][OCR] No disponible: OCR missing" in result["logs"]
    assert "## Página 1" in output.read_text(encoding="utf-8")


def test_extract_text_per_page_requires_output_directory(monkeypatch):
    monkeypatch.setattr(
        pdf,
        "_open_reader",
        lambda _src: SimpleNamespace(pages=[TextPage("hello")]),
    )

    with pytest.raises(ValueError, match="carpeta de salida"):
        pdf.extract_text_task(
            RecordingWorker(),
            "source.pdf",
            "",
            True,
            False,
            False,
            True,
            60,
            None,
            None,
        )


def test_extract_text_records_ocr_error_and_commits_per_page_outputs(monkeypatch, tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    monkeypatch.setattr(
        pdf,
        "_open_reader",
        lambda _src: SimpleNamespace(pages=[TextPage("")]),
    )
    monkeypatch.setattr(pdf, "ocr_available", lambda: (True, "OCR disponible."))
    monkeypatch.setattr(
        pdf,
        "ocr_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ocr failed")),
    )

    result = pdf.extract_text_task(
        RecordingWorker(),
        "source.pdf",
        "1",
        True,
        False,
        True,
        False,
        60,
        str(output_dir),
        None,
    )

    created = output_dir / "source_p1.md"
    assert result["created_files"] == [str(created)]
    assert created.exists()
    assert any("[OCR][ERROR]" in line for line in result["logs"])
    assert not list(output_dir.glob(".pythonkni-pdf-*"))


def test_extract_text_requires_save_path_for_single_file_and_cleans_temp(monkeypatch, tmp_path):
    monkeypatch.setattr(
        pdf,
        "_open_reader",
        lambda _src: SimpleNamespace(pages=[TextPage("hello")]),
    )

    with pytest.raises(ValueError, match="archivo de salida"):
        pdf.extract_text_task(
            RecordingWorker(),
            "source.pdf",
            "",
            False,
            False,
            False,
            True,
            60,
            None,
            None,
        )

    assert not list(tmp_path.glob("*.pythonkni.tmp"))


def test_load_reorder_task_reports_structure(monkeypatch):
    worker = RecordingWorker()
    monkeypatch.setattr(
        pdf,
        "_open_reader",
        lambda _src: SimpleNamespace(pages=[object(), object(), object()]),
    )

    result = pdf.load_reorder_task(worker, "source.pdf")

    assert result == {"src": "source.pdf", "page_count": 3}
    assert worker.progress == [{"message": "Leyendo estructura del PDF..."}]


def test_merge_requires_pypdf_merger(monkeypatch, tmp_path):
    monkeypatch.setattr(pdf, "PdfMerger", None)

    with pytest.raises(RuntimeError, match="PyPDF2"):
        pdf.merge_pdfs_task(RecordingWorker(), [], str(tmp_path / "merged.pdf"))


def test_write_writer_atomic_publishes_valid_pdf(tmp_path):
    output = tmp_path / "result.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)

    pdf._write_writer_atomic(writer, str(output))

    assert output.exists()
    assert not Path(str(output) + ".pythonkni.tmp").exists()
