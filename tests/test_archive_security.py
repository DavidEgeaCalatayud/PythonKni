import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import py7zr
import pytest

from tools import zip_7zip_utils as archives


def make_zip(path: Path, entries: dict[str, bytes], compression=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def test_safe_zip_extracts_normal_archive(tmp_path):
    archive_path = tmp_path / "normal.zip"
    destination = tmp_path / "out"
    make_zip(archive_path, {"folder/a.txt": b"alpha", "b.txt": b"beta"})

    result = archives.safe_extract_zip(archive_path, destination)

    assert result == destination
    assert (destination / "folder" / "a.txt").read_bytes() == b"alpha"
    assert (destination / "b.txt").read_bytes() == b"beta"
    assert not list(tmp_path.glob(".out.pythonkni-*.tmp"))


@pytest.mark.parametrize(
    "member_name",
    [
        "../escape.txt",
        "folder/../../escape.txt",
        "/absolute.txt",
        r"C:\escape.txt",
        r"\\server\share\escape.txt",
        "folder//ambiguous.txt",
        "folder/../escape.txt",
        "payload.txt:stream",
        "NUL.txt",
        "folder./payload.txt",
    ],
)
def test_zip_rejects_unsafe_paths_before_extraction(tmp_path, member_name):
    archive_path = tmp_path / "unsafe.zip"
    destination = tmp_path / "out"
    make_zip(archive_path, {member_name: b"blocked"})

    with pytest.raises(archives.ArchiveSecurityError):
        archives.safe_extract_zip(archive_path, destination)

    assert not destination.exists()
    assert not (tmp_path.parent / "escape.txt").exists()


def test_zip_rejects_symbolic_links(tmp_path):
    archive_path = tmp_path / "link.zip"
    destination = tmp_path / "out"
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16

    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(link, "../outside.txt")

    with pytest.raises(archives.ArchiveSecurityError, match="enlaces simbólicos"):
        archives.safe_extract_zip(archive_path, destination)

    assert not destination.exists()


def test_zip_rejects_special_files(tmp_path):
    archive_path = tmp_path / "special.zip"
    destination = tmp_path / "out"
    fifo = zipfile.ZipInfo("pipe")
    fifo.create_system = 3
    fifo.external_attr = (stat.S_IFIFO | 0o644) << 16

    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(fifo, b"")

    with pytest.raises(archives.ArchiveSecurityError, match="especial"):
        archives.safe_extract_zip(archive_path, destination)


def test_archive_limits_file_count_and_total_size(tmp_path):
    archive_path = tmp_path / "limits.zip"
    make_zip(archive_path, {"a.txt": b"1234", "b.txt": b"5678"}, zipfile.ZIP_STORED)

    with pytest.raises(archives.ArchiveSecurityError, match="máximo"):
        archives.safe_extract_zip(
            archive_path,
            tmp_path / "count-out",
            limits=archives.ArchiveLimits(max_files=1),
        )

    with pytest.raises(archives.ArchiveSecurityError, match="tamaño total"):
        archives.safe_extract_zip(
            archive_path,
            tmp_path / "size-out",
            limits=archives.ArchiveLimits(max_total_uncompressed=7),
        )


def test_archive_rejects_suspicious_compression_ratio(tmp_path):
    archive_path = tmp_path / "ratio.zip"
    make_zip(archive_path, {"bomb.txt": b"A" * 100_000})

    with pytest.raises(archives.ArchiveSecurityError, match="Ratio de compresión"):
        archives.safe_extract_zip(
            archive_path,
            tmp_path / "out",
            limits=archives.ArchiveLimits(max_compression_ratio=5.0),
        )


def test_archive_rejects_case_insensitive_duplicate_paths():
    members = [
        archives.ArchiveMember("Folder/File.txt", 1, 1),
        archives.ArchiveMember("folder/file.TXT", 1, 1),
    ]

    with pytest.raises(archives.ArchiveSecurityError, match="duplicada"):
        archives.validate_archive_members(members)


def test_archive_rejects_declared_7z_link_and_unknown_special_type():
    link = archives.ArchiveMember("link", 5, 5, is_symlink=True, is_regular=False)
    special = archives.ArchiveMember("socket", 0, 0, is_regular=False)

    with pytest.raises(archives.ArchiveSecurityError, match="enlaces simbólicos"):
        archives.validate_archive_members([link])
    with pytest.raises(archives.ArchiveSecurityError, match="especial"):
        archives.validate_archive_members([special])


def test_seven_zip_metadata_is_normalized_for_security_validation():
    info = SimpleNamespace(
        filename="nested/data.txt",
        uncompressed=123,
        compressed=50,
        is_directory=False,
        is_symlink=False,
        is_file=True,
    )

    member = archives._seven_zip_member(info)

    assert member == archives.ArchiveMember("nested/data.txt", 123, 50)


def test_safe_7z_extracts_normal_archive(tmp_path):
    source = tmp_path / "payload.txt"
    source.write_text("contenido seguro", encoding="utf-8")
    archive_path = tmp_path / "normal.7z"
    destination = tmp_path / "out"

    with py7zr.SevenZipFile(archive_path, "w") as archive:
        archive.write(source, arcname="nested/payload.txt")

    result = archives.safe_extract_7z(archive_path, destination)

    assert result == destination
    assert (destination / "nested" / "payload.txt").read_text(
        encoding="utf-8"
    ) == "contenido seguro"
    assert not list(tmp_path.glob(".out.pythonkni-*.tmp"))


def test_safe_7z_applies_metadata_limits_before_extracting(monkeypatch, tmp_path):
    archive_path = tmp_path / "fake.7z"
    archive_path.write_bytes(b"not-used")
    destination = tmp_path / "out"
    calls = {"extract": 0}

    class FakeArchive:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def list(self):
            return [
                SimpleNamespace(
                    filename="huge.bin",
                    uncompressed=100,
                    compressed=1,
                    is_directory=False,
                    is_symlink=False,
                    is_file=True,
                )
            ]

        def extractall(self, path):
            calls["extract"] += 1

    monkeypatch.setattr(archives, "_open_7z_for_read", lambda *args, **kwargs: FakeArchive())

    with pytest.raises(archives.ArchiveSecurityError, match="Ratio de compresión"):
        archives.safe_extract_7z(
            archive_path,
            destination,
            limits=archives.ArchiveLimits(max_compression_ratio=10.0),
        )

    assert calls["extract"] == 0
    assert not destination.exists()


def test_existing_destination_is_never_merged_or_overwritten(tmp_path):
    archive_path = tmp_path / "normal.zip"
    destination = tmp_path / "out"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    make_zip(archive_path, {"new.txt": b"new"})

    with pytest.raises(archives.ArchiveSecurityError, match="ya existe"):
        archives.safe_extract_zip(archive_path, destination)

    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (destination / "new.txt").exists()
