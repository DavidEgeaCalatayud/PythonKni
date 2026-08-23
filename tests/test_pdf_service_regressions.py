import os
from pathlib import Path
from unittest.mock import patch

import pytest
from PyPDF2 import PdfReader, PdfWriter

from pythonkni.core.tasks import WorkerCancelled
from pythonkni.pdf.service import (
    extract_pages_task,
    extract_text_task,
    merge_pdfs_task,
    reorder_pdf_task,
    split_pdf_task,
)


class FakeWorker:
    def __init__(self):
        self.progress = []
        self.cancelled = False

    def check_cancelled(self):
        if self.cancelled:
            raise WorkerCancelled()

    def report_progress(self, payload):
        self.check_cancelled()
        self.progress.append(payload)


class CancelAfterProgressWorker(FakeWorker):
    def report_progress(self, payload):
        super().report_progress(payload)
        self.cancelled = True


def make_pdf(path: Path, widths):
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=100)
    with path.open("wb") as file:
        writer.write(file)


def make_encrypted_pdf(path: Path, widths, password: str):
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=100)
    writer.encrypt(password)
    with path.open("wb") as file:
        writer.write(file)


def pdf_widths(path: Path):
    reader = PdfReader(str(path))
    return [int(float(page.mediabox.width)) for page in reader.pages]


def assert_no_pdf_staging(directory: Path):
    assert not list(directory.glob(".pythonkni-pdf-*"))
    assert not list(directory.glob("*.pythonkni.tmp"))


def test_split_ranges_preserves_requested_page_groups(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "out"
    output.mkdir()
    make_pdf(source, [101, 202, 303, 404])

    result = split_pdf_task(FakeWorker(), str(source), str(output), "ranges", "1-2,4")

    assert [Path(path).name for path in result["outputs"]] == [
        "source_part1.pdf",
        "source_part2.pdf",
    ]
    assert pdf_widths(output / "source_part1.pdf") == [101, 202]
    assert pdf_widths(output / "source_part2.pdf") == [404]
    assert_no_pdf_staging(output)


def test_split_cancellation_preserves_preexisting_destination(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "out"
    output.mkdir()
    make_pdf(source, [101, 202, 303])
    preexisting = output / "source_p1.pdf"
    make_pdf(preexisting, [999])

    with pytest.raises(WorkerCancelled):
        split_pdf_task(CancelAfterProgressWorker(), str(source), str(output), "individual", "")

    assert pdf_widths(preexisting) == [999]
    assert not (output / "source_p2.pdf").exists()
    assert not (output / "source_p3.pdf").exists()
    assert_no_pdf_staging(output)


def test_split_commit_failure_rolls_back_all_preexisting_destinations(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "out"
    output.mkdir()
    make_pdf(source, [101, 202])
    first = output / "source_p1.pdf"
    second = output / "source_p2.pdf"
    make_pdf(first, [901])
    make_pdf(second, [902])
    real_replace = os.replace

    def flaky_replace(src, dst):
        src_path = Path(src)
        dst_path = Path(dst)
        if (
            dst_path == second
            and src_path.parent.name.startswith(".pythonkni-pdf-")
            and ".stage" in src_path.name
        ):
            raise OSError("simulated publish failure")
        return real_replace(src, dst)

    with patch("pythonkni.pdf.service.os.replace", side_effect=flaky_replace):
        with pytest.raises(OSError, match="simulated publish failure"):
            split_pdf_task(FakeWorker(), str(source), str(output), "individual", "")

    assert pdf_widths(first) == [901]
    assert pdf_widths(second) == [902]
    assert_no_pdf_staging(output)


def test_merge_preserves_input_order(tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    target = tmp_path / "merged.pdf"
    make_pdf(first, [101, 102])
    make_pdf(second, [201])

    result = merge_pdfs_task(FakeWorker(), [str(first), str(second)], str(target))

    assert result["file_count"] == 2
    assert pdf_widths(target) == [101, 102, 201]
    assert_no_pdf_staging(tmp_path)


def test_merge_replace_failure_preserves_existing_destination_and_cleans_temp(tmp_path):
    first = tmp_path / "first.pdf"
    target = tmp_path / "merged.pdf"
    make_pdf(first, [101])
    make_pdf(target, [999])
    real_replace = os.replace

    def fail_target_replace(src, dst):
        if Path(dst) == target:
            raise OSError("cannot publish")
        return real_replace(src, dst)

    with patch("pythonkni.pdf.service.os.replace", side_effect=fail_target_replace):
        with pytest.raises(OSError, match="cannot publish"):
            merge_pdfs_task(FakeWorker(), [str(first)], str(target))

    assert pdf_widths(target) == [999]
    assert not Path(str(target) + ".pythonkni.tmp").exists()


def test_merge_cancellation_preserves_existing_destination(tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    target = tmp_path / "merged.pdf"
    make_pdf(first, [101])
    make_pdf(second, [202])
    make_pdf(target, [999])

    with pytest.raises(WorkerCancelled):
        merge_pdfs_task(
            CancelAfterProgressWorker(),
            [str(first), str(second)],
            str(target),
        )

    assert pdf_widths(target) == [999]
    assert not Path(str(target) + ".pythonkni.tmp").exists()


def test_extract_pages_preserves_requested_order(tmp_path):
    source = tmp_path / "source.pdf"
    target = tmp_path / "extract.pdf"
    make_pdf(source, [101, 202, 303])

    result = extract_pages_task(FakeWorker(), str(source), "3,1", str(target))

    assert result["page_count"] == 2
    assert pdf_widths(target) == [303, 101]


def test_reorder_pdf_preserves_arbitrary_order(tmp_path):
    source = tmp_path / "source.pdf"
    target = tmp_path / "reordered.pdf"
    make_pdf(source, [101, 202, 303])

    result = reorder_pdf_task(FakeWorker(), str(source), [3, 1, 2], str(target))

    assert result["page_count"] == 3
    assert pdf_widths(target) == [303, 101, 202]


def test_extract_pages_cancellation_preserves_existing_destination(tmp_path):
    source = tmp_path / "source.pdf"
    target = tmp_path / "extract.pdf"
    make_pdf(source, [101, 202])
    make_pdf(target, [999])

    with pytest.raises(WorkerCancelled):
        extract_pages_task(CancelAfterProgressWorker(), str(source), "1,2", str(target))

    assert pdf_widths(target) == [999]
    assert not Path(str(target) + ".pythonkni.tmp").exists()


def test_corrupt_pdf_does_not_touch_existing_destination(tmp_path):
    source = tmp_path / "broken.pdf"
    target = tmp_path / "extract.pdf"
    source.write_bytes(b"this is not a pdf")
    make_pdf(target, [999])

    with pytest.raises(Exception):
        extract_pages_task(FakeWorker(), str(source), "1", str(target))

    assert pdf_widths(target) == [999]
    assert not Path(str(target) + ".pythonkni.tmp").exists()


def test_password_protected_pdf_is_rejected_without_touching_destination(tmp_path):
    source = tmp_path / "encrypted.pdf"
    target = tmp_path / "extract.pdf"
    make_encrypted_pdf(source, [101], "secret")
    make_pdf(target, [999])

    with pytest.raises(ValueError, match="requiere contraseña"):
        extract_pages_task(FakeWorker(), str(source), "1", str(target))

    assert pdf_widths(target) == [999]
    assert not Path(str(target) + ".pythonkni.tmp").exists()


def test_empty_password_encrypted_pdf_can_be_processed(tmp_path):
    source = tmp_path / "encrypted-empty.pdf"
    target = tmp_path / "extract.pdf"
    make_encrypted_pdf(source, [101, 202], "")

    result = extract_pages_task(FakeWorker(), str(source), "2", str(target))

    assert result["page_count"] == 1
    assert pdf_widths(target) == [202]


def test_per_page_text_cancellation_preserves_preexisting_markdown(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "out"
    output.mkdir()
    make_pdf(source, [101, 202])
    preexisting = output / "source_p1.md"
    preexisting.write_text("contenido previo\n", encoding="utf-8")

    with pytest.raises(WorkerCancelled):
        extract_text_task(
            CancelAfterProgressWorker(),
            str(source),
            "",
            True,
            True,
            False,
            True,
            60,
            str(output),
            None,
        )

    assert preexisting.read_text(encoding="utf-8") == "contenido previo\n"
    assert not (output / "source_p2.md").exists()
    assert_no_pdf_staging(output)
