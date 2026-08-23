from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterable

from pythonkni.core.tasks import WorkerCancelled

try:
    from PyPDF2 import PdfMerger, PdfReader, PdfWriter
except ImportError:
    PdfReader = PdfWriter = PdfMerger = None


class _PdfOutputTransaction:
    """Stage PDF-tool outputs and publish them as one logical batch.

    Existing destinations are moved to backups only during commit. If any
    publication step fails, already-published files are removed and the
    previous destinations are restored before the staging directory is cleaned.
    """

    def __init__(self, destination_dir: str | Path):
        self.destination_dir = Path(destination_dir)
        self.destination_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir = Path(
            tempfile.mkdtemp(prefix=".pythonkni-pdf-", dir=self.destination_dir)
        )
        self._entries: list[tuple[Path, Path]] = []
        self._committed = False

    def stage_for(self, final_path: str | Path) -> Path:
        final = Path(final_path)
        if final.parent.resolve(strict=False) != self.destination_dir.resolve(strict=False):
            raise ValueError("Todos los destinos de una transacción PDF deben compartir carpeta.")
        index = len(self._entries)
        stage = self.staging_dir / f"{index:04d}_{final.stem}.stage{final.suffix}"
        self._entries.append((stage, final))
        return stage

    def commit(self) -> list[str]:
        states: list[tuple[Path, Path | None]] = []
        try:
            for index, (stage, final) in enumerate(self._entries):
                if not stage.exists():
                    raise FileNotFoundError(f"No existe el resultado temporal: {stage}")

                backup = None
                if final.exists():
                    backup = self.staging_dir / f"{index:04d}_{final.name}.backup"
                    os.replace(final, backup)
                states.append((final, backup))
                os.replace(stage, final)
        except Exception:
            for final, backup in reversed(states):
                try:
                    if final.exists():
                        final.unlink()
                    if backup is not None and backup.exists():
                        os.replace(backup, final)
                except OSError:
                    pass
            raise

        self._committed = True
        outputs = [str(final) for _, final in self._entries]
        self._cleanup()
        return outputs

    def _cleanup(self) -> None:
        shutil.rmtree(self.staging_dir, ignore_errors=True)

    def abort(self) -> None:
        if not self._committed:
            self._cleanup()

    def __enter__(self) -> "_PdfOutputTransaction":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if not self._committed:
            self.abort()


def require_pypdf_available() -> bool:
    return PdfReader is not None and PdfWriter is not None


def parse_page_list(spec: str, max_pages: int) -> list[int]:
    """Parse ``1,3,5-7`` into unique zero-based page indexes."""
    result = []
    seen = set()
    parts = [part.strip() for part in spec.split(",") if part.strip()]
    for part in parts:
        if "-" in part:
            first, last = part.split("-", 1)
            start = int(first.strip())
            end = int(last.strip())
            if start > end:
                start, end = end, start
            page_numbers = range(start, end + 1)
        else:
            page_numbers = (int(part),)

        for page_number in page_numbers:
            index = page_number - 1
            if 0 <= index < max_pages and index not in seen:
                result.append(index)
                seen.add(index)

    if not result:
        raise ValueError("No se han podido parsear páginas válidas.")
    return result


def parse_page_spec(spec: str, max_pages: int) -> list[list[int]]:
    """Parse comma-separated split groups into zero-based page indexes."""
    groups = []
    parts = [part.strip() for part in spec.split(",") if part.strip()]
    for part in parts:
        groups.append(parse_page_list(part, max_pages=max_pages))
    if not groups:
        raise ValueError("No se han podido parsear rangos válidos.")
    return groups


def _open_reader(src: str):
    if PdfReader is None:
        raise RuntimeError("No se encuentra PyPDF2.")
    reader = PdfReader(src)
    if getattr(reader, "is_encrypted", False):
        try:
            result = reader.decrypt("")
        except Exception as error:
            raise ValueError(
                "El PDF parece estar cifrado y no se pudo descifrar sin contraseña."
            ) from error
        if result == 0:
            raise ValueError("El PDF está cifrado y requiere contraseña.")
    return reader


def _temp_path(path: str) -> str:
    return path + ".pythonkni.tmp"


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _write_writer(writer, output_path: str | Path) -> None:
    with open(output_path, "wb") as file:
        writer.write(file)


def _write_writer_atomic(writer, output_path: str) -> None:
    temp_path = _temp_path(output_path)
    _remove_quietly(temp_path)
    try:
        _write_writer(writer, temp_path)
        os.replace(temp_path, output_path)
    except Exception:
        _remove_quietly(temp_path)
        raise


def _progress(worker, message: str, current: int | None = None, total: int | None = None) -> None:
    payload = {"message": message}
    if current is not None and total:
        payload["percent"] = int((current / total) * 100)
        payload["current"] = current
        payload["total"] = total
    worker.report_progress(payload)


def split_pdf_task(worker, src: str, out_dir: str, mode: str, spec: str):
    reader = _open_reader(src)
    page_count = len(reader.pages)
    base = os.path.splitext(os.path.basename(src))[0]

    with _PdfOutputTransaction(out_dir) as transaction:
        if mode == "individual":
            for index in range(page_count):
                worker.check_cancelled()
                writer = PdfWriter()
                writer.add_page(reader.pages[index])
                output_path = os.path.join(out_dir, f"{base}_p{index + 1}.pdf")
                stage_path = transaction.stage_for(output_path)
                _write_writer(writer, stage_path)
                _progress(
                    worker,
                    f"Dividiendo página {index + 1}/{page_count}",
                    index + 1,
                    page_count,
                )
        else:
            if not spec:
                raise ValueError("Indique rangos. Ej: 1-3,5,8-10")
            groups = parse_page_spec(spec, max_pages=page_count)
            total = len(groups)
            for number, group in enumerate(groups, start=1):
                worker.check_cancelled()
                writer = PdfWriter()
                for page_index in group:
                    worker.check_cancelled()
                    writer.add_page(reader.pages[page_index])
                output_path = os.path.join(out_dir, f"{base}_part{number}.pdf")
                stage_path = transaction.stage_for(output_path)
                _write_writer(writer, stage_path)
                _progress(worker, f"Creando parte {number}/{total}", number, total)

        worker.check_cancelled()
        outputs = transaction.commit()

    return {"outputs": outputs, "out_dir": out_dir, "mode": mode}


def preview_text_task(worker, src: str, limit: int = 2):
    reader = _open_reader(src)
    take = min(limit, len(reader.pages))
    sample = []
    for index in range(take):
        worker.check_cancelled()
        text = (reader.pages[index].extract_text() or "").strip()
        sample.append(f"--- Página {index + 1} ---\n{text}\n")
        _progress(worker, f"Leyendo página {index + 1}/{take}", index + 1, take)

    preview = "\n".join(sample).strip()
    if not preview:
        preview = "(No se ha detectado texto. Puede ser un PDF escaneado o protegido.)"
    return {"preview": preview, "pages": take}


def ocr_available():
    deps = {}
    try:
        import pytesseract

        deps["pytesseract"] = True
    except Exception:
        deps["pytesseract"] = False

    try:
        from pdf2image import convert_from_path  # noqa: F401

        deps["pdf2image"] = True
    except Exception:
        deps["pdf2image"] = False

    if not deps["pytesseract"] or not deps["pdf2image"]:
        return False, "Faltan librerías Python para OCR: instale pytesseract, pdf2image, pillow."

    try:
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception:
        return False, "Tesseract no está accesible. Instálelo y/o añádalo al PATH."
    return True, "OCR disponible."


def ocr_page(worker, pdf_path: str, page_number_1based: int) -> str:
    import pytesseract
    from pdf2image import convert_from_path

    worker.check_cancelled()
    images = convert_from_path(
        pdf_path,
        first_page=page_number_1based,
        last_page=page_number_1based,
    )
    worker.check_cancelled()
    if not images:
        return ""
    text = pytesseract.image_to_string(images[0]) or ""
    worker.check_cancelled()
    return text.strip()


def extract_text_task(
    worker,
    src: str,
    pages_spec: str,
    one_per_page: bool,
    include_headers: bool,
    use_ocr: bool,
    ocr_only_empty: bool,
    scan_threshold: int,
    out_dir: str | None,
    save_path: str | None,
):
    reader = _open_reader(src)
    page_count = len(reader.pages)
    pages = parse_page_list(pages_spec, page_count) if pages_spec else list(range(page_count))
    total = len(pages)
    base = os.path.splitext(os.path.basename(src))[0]
    logs = [f"[Texto] Páginas seleccionadas: {', '.join(str(page + 1) for page in pages)}"]
    logs.append(
        "[Texto] Exportación: "
        + ("1 archivo por página" if one_per_page else "archivo único")
        + " (Markdown)"
    )

    ocr_warning = ""
    if use_ocr:
        _progress(worker, "Comprobando OCR...")
        available, message = ocr_available()
        if not available:
            ocr_warning = message
            logs.append(f"[Texto][OCR] No disponible: {message}")
            use_ocr = False
        else:
            logs.append(f"[Texto][OCR] {message}")

    empty_pages = 0
    extracted = []
    created_files = []
    transaction = None
    if one_per_page:
        if out_dir is None:
            raise ValueError("Falta la carpeta de salida.")
        transaction = _PdfOutputTransaction(out_dir)

    try:
        for position, page_index in enumerate(pages, start=1):
            worker.check_cancelled()
            page_number = page_index + 1
            text = (reader.pages[page_index].extract_text() or "").strip()
            is_empty = not text
            if is_empty:
                empty_pages += 1

            if use_ocr and ((not ocr_only_empty) or is_empty):
                try:
                    _progress(
                        worker,
                        f"OCR página {page_number} ({position}/{total})",
                        position - 1,
                        total,
                    )
                    ocr_text = ocr_page(worker, src, page_number)
                    if ocr_text:
                        text = ocr_text
                except WorkerCancelled:
                    raise
                except Exception as error:
                    logs.append(f"[Texto][OCR][ERROR] Página {page_number}: {error}")

            blocks = []
            if include_headers:
                blocks.append(f"## Página {page_number}\n")
            blocks.append(text)
            md_content = "\n".join(blocks).strip() + "\n"

            if one_per_page:
                output_path = os.path.join(out_dir, f"{base}_p{page_number}.md")
                stage_path = transaction.stage_for(output_path)
                with open(stage_path, "w", encoding="utf-8") as file:
                    file.write(md_content)
            else:
                extracted.append(md_content)

            _progress(worker, f"Procesando página {position}/{total}", position, total)

        if one_per_page:
            worker.check_cancelled()
            created_files = transaction.commit()
        else:
            if save_path is None:
                raise ValueError("Falta el archivo de salida.")
            final_md = "\n\n".join(extracted).strip() + "\n"
            temp_path = _temp_path(save_path)
            _remove_quietly(temp_path)
            try:
                with open(temp_path, "w", encoding="utf-8") as file:
                    file.write(final_md)
                worker.check_cancelled()
                os.replace(temp_path, save_path)
            except Exception:
                _remove_quietly(temp_path)
                raise
            created_files.append(save_path)
    except Exception:
        if transaction is not None:
            transaction.abort()
        raise

    empty_ratio = (empty_pages / total) * 100 if total else 0
    return {
        "created_files": created_files,
        "empty_pages": empty_pages,
        "empty_ratio": empty_ratio,
        "total": total,
        "threshold": scan_threshold,
        "ocr_warning": ocr_warning,
        "logs": logs,
    }


def extract_pages_task(worker, src: str, spec: str, save_path: str):
    reader = _open_reader(src)
    pages = parse_page_list(spec, max_pages=len(reader.pages))
    writer = PdfWriter()
    total = len(pages)
    for position, page_index in enumerate(pages, start=1):
        worker.check_cancelled()
        writer.add_page(reader.pages[page_index])
        _progress(worker, f"Extrayendo página {position}/{total}", position, total)
    worker.check_cancelled()
    _write_writer_atomic(writer, save_path)
    return {"save_path": save_path, "page_count": total}


def load_reorder_task(worker, src: str):
    worker.report_progress({"message": "Leyendo estructura del PDF..."})
    reader = _open_reader(src)
    worker.check_cancelled()
    return {"src": src, "page_count": len(reader.pages)}


def reorder_pdf_task(worker, src: str, order: Iterable[int], save_path: str):
    reader = _open_reader(src)
    page_order = list(order)
    writer = PdfWriter()
    total = len(page_order)
    for position, page_number in enumerate(page_order, start=1):
        worker.check_cancelled()
        writer.add_page(reader.pages[page_number - 1])
        _progress(worker, f"Reordenando página {position}/{total}", position, total)
    worker.check_cancelled()
    _write_writer_atomic(writer, save_path)
    return {"save_path": save_path, "page_count": total}


def merge_pdfs_task(worker, paths: Iterable[str], save_path: str):
    if PdfMerger is None:
        raise RuntimeError("No se encuentra PyPDF2.")
    pdf_paths = list(paths)
    merger = PdfMerger()
    temp_path = _temp_path(save_path)
    _remove_quietly(temp_path)
    try:
        total = len(pdf_paths)
        for position, path in enumerate(pdf_paths, start=1):
            worker.check_cancelled()
            merger.append(path)
            _progress(worker, f"Combinando PDF {position}/{total}", position, total)
        worker.check_cancelled()
        merger.write(temp_path)
        worker.check_cancelled()
        os.replace(temp_path, save_path)
    except Exception:
        _remove_quietly(temp_path)
        raise
    finally:
        merger.close()
    return {"save_path": save_path, "file_count": len(pdf_paths)}
