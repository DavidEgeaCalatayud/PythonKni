from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

IEEE_MA_L_CSV_URL = "https://standards-oui.ieee.org/oui/oui.csv"
SOURCE_NAME = "IEEE Registration Authority MA-L Public Listing"
SCHEMA_VERSION = 1
DEFAULT_MIN_ENTRIES = 20_000
MAX_SOURCE_BYTES = 32 * 1024 * 1024
_HEX_RE = re.compile(r"^[0-9A-F]{6}$")
_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = _REPO_ROOT / "assets" / "network_oui_prefixes.csv"
DEFAULT_METADATA_PATH = _REPO_ROOT / "assets" / "network_oui_prefixes.meta.json"


class RegistryUpdateError(ValueError):
    """Raised when the IEEE source or bundled registry violates its contract."""


@dataclass(frozen=True, order=True)
class RegistryEntry:
    prefix: str
    vendor: str


@dataclass(frozen=True)
class DuplicateAssignment:
    prefix: str
    vendors: tuple[str, ...]


@dataclass(frozen=True)
class ParsedRegistry:
    entries: tuple[RegistryEntry, ...]
    duplicate_assignments: tuple[DuplicateAssignment, ...]


@dataclass(frozen=True)
class DownloadedSource:
    content: bytes
    etag: str | None = None
    last_modified: str | None = None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_assignment(value: str | None) -> str:
    compact = (
        (value or "")
        .strip()
        .upper()
        .replace(":", "")
        .replace("-", "")
        .replace(".", "")
    )
    if not _HEX_RE.fullmatch(compact):
        raise RegistryUpdateError(f"invalid MA-L assignment: {value!r}")
    return "-".join(compact[index : index + 2] for index in range(0, 6, 2))


def normalize_vendor(value: str | None) -> str:
    normalized = unicodedata.normalize("NFC", value or "")
    normalized = "".join(
        char for char in normalized if unicodedata.category(char) != "Cf"
    )
    normalized = " ".join(normalized.split())
    if not normalized:
        raise RegistryUpdateError("vendor name is empty")
    if any(unicodedata.category(char).startswith("C") for char in normalized):
        raise RegistryUpdateError(f"vendor contains a control character: {value!r}")
    return normalized


def _render_ambiguous_vendor(vendors: tuple[str, ...]) -> str:
    if len(vendors) == 1:
        return vendors[0]
    return " / ".join(vendors)


def parse_ieee_ma_l_csv(source: bytes) -> ParsedRegistry:
    try:
        text = source.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RegistryUpdateError("IEEE MA-L CSV is not valid UTF-8") from exc

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        required = {"Registry", "Assignment", "Organization Name"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise RegistryUpdateError(
                "IEEE MA-L CSV is missing required columns: "
                + ", ".join(sorted(required))
            )

        vendors_by_prefix: dict[str, set[str]] = {}
        for line_number, row in enumerate(reader, start=2):
            if (row.get("Registry") or "").strip().upper() != "MA-L":
                raise RegistryUpdateError(
                    f"unexpected registry at line {line_number}: {row.get('Registry')!r}"
                )
            try:
                prefix = normalize_assignment(row.get("Assignment"))
                vendor = normalize_vendor(row.get("Organization Name"))
            except RegistryUpdateError as exc:
                raise RegistryUpdateError(f"line {line_number}: {exc}") from exc
            vendors_by_prefix.setdefault(prefix, set()).add(vendor)
    except csv.Error as exc:
        raise RegistryUpdateError(f"invalid IEEE MA-L CSV: {exc}") from exc

    if not vendors_by_prefix:
        raise RegistryUpdateError("IEEE MA-L CSV contains no assignments")

    entries: list[RegistryEntry] = []
    duplicates: list[DuplicateAssignment] = []
    for prefix in sorted(vendors_by_prefix):
        vendors = tuple(sorted(vendors_by_prefix[prefix], key=str.casefold))
        entries.append(
            RegistryEntry(prefix=prefix, vendor=_render_ambiguous_vendor(vendors))
        )
        if len(vendors) > 1:
            duplicates.append(DuplicateAssignment(prefix=prefix, vendors=vendors))
    return ParsedRegistry(entries=tuple(entries), duplicate_assignments=tuple(duplicates))


def render_registry(entries: tuple[RegistryEntry, ...] | list[RegistryEntry]) -> bytes:
    sorted_entries = sorted(entries)
    seen: set[str] = set()
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("prefix", "vendor"))
    for entry in sorted_entries:
        prefix = normalize_assignment(entry.prefix)
        vendor = normalize_vendor(entry.vendor)
        if prefix in seen:
            raise RegistryUpdateError(f"duplicate bundled assignment: {prefix}")
        seen.add(prefix)
        writer.writerow((prefix, vendor))
    return buffer.getvalue().encode("utf-8")


def parse_bundled_registry(content: bytes) -> tuple[RegistryEntry, ...]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RegistryUpdateError("bundled OUI registry is not valid UTF-8") from exc

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if reader.fieldnames != ["prefix", "vendor"]:
            raise RegistryUpdateError(
                "bundled OUI registry must contain exactly the columns prefix,vendor"
            )
        entries: list[RegistryEntry] = []
        seen: set[str] = set()
        previous: str | None = None
        for line_number, row in enumerate(reader, start=2):
            try:
                prefix = normalize_assignment(row.get("prefix"))
                vendor = normalize_vendor(row.get("vendor"))
            except RegistryUpdateError as exc:
                raise RegistryUpdateError(f"line {line_number}: {exc}") from exc
            if prefix in seen:
                raise RegistryUpdateError(
                    f"duplicate bundled assignment at line {line_number}: {prefix}"
                )
            if previous is not None and prefix <= previous:
                raise RegistryUpdateError(
                    f"bundled registry is not strictly sorted at line {line_number}"
                )
            seen.add(prefix)
            previous = prefix
            entries.append(RegistryEntry(prefix=prefix, vendor=vendor))
    except csv.Error as exc:
        raise RegistryUpdateError(f"invalid bundled OUI registry: {exc}") from exc

    if not entries:
        raise RegistryUpdateError("bundled OUI registry contains no assignments")
    return tuple(entries)


def download_ieee_ma_l_csv(
    url: str = IEEE_MA_L_CSV_URL,
    *,
    timeout: float = 30.0,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> DownloadedSource:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "PythonKni-OUI-Updater/1.0 "
                "(https://github.com/DavidEgeaCalatayud/PythonKni)"
            ),
            "Accept": "text/csv,*/*;q=0.1",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise RegistryUpdateError(
                    f"IEEE MA-L CSV exceeds the {max_bytes}-byte safety limit"
                )
            return DownloadedSource(
                content=content,
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
            )
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RegistryUpdateError(f"failed to download IEEE MA-L CSV: {exc}") from exc


def _parse_retrieved_at(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise RegistryUpdateError(f"invalid retrieval timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise RegistryUpdateError("retrieval timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def build_metadata(
    *,
    source: DownloadedSource,
    registry_bytes: bytes,
    parsed: ParsedRegistry,
    retrieved_at: datetime,
    source_url: str = IEEE_MA_L_CSV_URL,
) -> bytes:
    if retrieved_at.tzinfo is None:
        raise RegistryUpdateError("retrieval timestamp must be timezone-aware")
    timestamp = (
        retrieved_at.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "registry": "IEEE MA-L / OUI-24",
        "source_name": SOURCE_NAME,
        "source_url": source_url,
        "retrieved_at": timestamp,
        "source_sha256": _sha256(source.content),
        "registry_sha256": _sha256(registry_bytes),
        "entry_count": len(parsed.entries),
        "duplicate_assignment_count": len(parsed.duplicate_assignments),
        "duplicate_assignments": [
            {"prefix": item.prefix, "vendors": list(item.vendors)}
            for item in parsed.duplicate_assignments
        ],
        "source_etag": source.etag,
        "source_last_modified": source.last_modified,
        "generator": "scripts/update_oui_registry.py",
    }
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _stage_file(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return temp_path
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def write_registry_pair(
    registry_path: Path,
    metadata_path: Path,
    registry_bytes: bytes,
    metadata_bytes: bytes,
) -> None:
    registry_temp = _stage_file(registry_path, registry_bytes)
    metadata_temp = _stage_file(metadata_path, metadata_bytes)
    try:
        os.replace(registry_temp, registry_path)
        os.replace(metadata_temp, metadata_path)
    finally:
        registry_temp.unlink(missing_ok=True)
        metadata_temp.unlink(missing_ok=True)


def _load_metadata(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def update_registry(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    metadata_path: Path = DEFAULT_METADATA_PATH,
    source_url: str = IEEE_MA_L_CSV_URL,
    source_file: Path | None = None,
    min_entries: int = DEFAULT_MIN_ENTRIES,
    retrieved_at: datetime | None = None,
) -> bool:
    if min_entries < 1:
        raise RegistryUpdateError("minimum entry count must be positive")

    if source_file is None:
        source = download_ieee_ma_l_csv(source_url)
    else:
        try:
            raw = source_file.read_bytes()
        except OSError as exc:
            raise RegistryUpdateError(f"failed to read source file: {exc}") from exc
        if len(raw) > MAX_SOURCE_BYTES:
            raise RegistryUpdateError(
                f"source file exceeds the {MAX_SOURCE_BYTES}-byte safety limit"
            )
        source = DownloadedSource(content=raw)

    parsed = parse_ieee_ma_l_csv(source.content)
    if len(parsed.entries) < min_entries:
        raise RegistryUpdateError(
            f"IEEE MA-L CSV contains only {len(parsed.entries)} unique entries; "
            f"expected at least {min_entries}"
        )

    registry_bytes = render_registry(parsed.entries)
    existing_metadata = _load_metadata(metadata_path)
    try:
        existing_registry = registry_path.read_bytes()
    except OSError:
        existing_registry = None

    if (
        existing_registry == registry_bytes
        and existing_metadata is not None
        and existing_metadata.get("source_sha256") == _sha256(source.content)
    ):
        validate_bundled_registry(
            registry_path=registry_path,
            metadata_path=metadata_path,
            min_entries=min_entries,
            expected_source_url=source_url,
        )
        return False

    metadata_bytes = build_metadata(
        source=source,
        registry_bytes=registry_bytes,
        parsed=parsed,
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
        source_url=source_url,
    )
    write_registry_pair(registry_path, metadata_path, registry_bytes, metadata_bytes)
    return True


def validate_bundled_registry(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    metadata_path: Path = DEFAULT_METADATA_PATH,
    min_entries: int = DEFAULT_MIN_ENTRIES,
    expected_source_url: str = IEEE_MA_L_CSV_URL,
) -> int:
    try:
        registry_bytes = registry_path.read_bytes()
    except OSError as exc:
        raise RegistryUpdateError(f"failed to read bundled registry: {exc}") from exc
    entries = parse_bundled_registry(registry_bytes)
    if len(entries) < min_entries:
        raise RegistryUpdateError(
            f"bundled registry contains only {len(entries)} entries; "
            f"expected at least {min_entries}"
        )

    metadata = _load_metadata(metadata_path)
    if metadata is None:
        raise RegistryUpdateError("failed to read valid OUI metadata JSON")

    expected = {
        "schema_version": SCHEMA_VERSION,
        "registry": "IEEE MA-L / OUI-24",
        "source_name": SOURCE_NAME,
        "source_url": expected_source_url,
        "entry_count": len(entries),
        "registry_sha256": _sha256(registry_bytes),
        "generator": "scripts/update_oui_registry.py",
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise RegistryUpdateError(
                f"OUI metadata mismatch for {key}: "
                f"expected {value!r}, got {metadata.get(key)!r}"
            )

    source_hash = metadata.get("source_sha256")
    if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise RegistryUpdateError("OUI metadata source_sha256 is invalid")
    retrieved_at = metadata.get("retrieved_at")
    if not isinstance(retrieved_at, str):
        raise RegistryUpdateError("OUI metadata retrieved_at is missing")
    _parse_retrieved_at(retrieved_at)

    duplicates = metadata.get("duplicate_assignments")
    duplicate_count = metadata.get("duplicate_assignment_count")
    if not isinstance(duplicates, list) or duplicate_count != len(duplicates):
        raise RegistryUpdateError("OUI metadata duplicate assignment data is invalid")
    for item in duplicates:
        if not isinstance(item, dict):
            raise RegistryUpdateError("OUI metadata duplicate assignment item is invalid")
        prefix = item.get("prefix")
        vendors = item.get("vendors")
        try:
            normalized_prefix = normalize_assignment(prefix if isinstance(prefix, str) else None)
        except RegistryUpdateError as exc:
            raise RegistryUpdateError("OUI metadata duplicate prefix is invalid") from exc
        if normalized_prefix != prefix or not isinstance(vendors, list) or len(vendors) < 2:
            raise RegistryUpdateError("OUI metadata duplicate assignment item is invalid")
        normalized_vendors = tuple(
            normalize_vendor(vendor if isinstance(vendor, str) else None)
            for vendor in vendors
        )
        if tuple(sorted(set(normalized_vendors), key=str.casefold)) != normalized_vendors:
            raise RegistryUpdateError("OUI metadata duplicate vendors are not canonical")
    return len(entries)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Update or validate PythonKni's bundled IEEE MA-L OUI registry."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    update = subparsers.add_parser("update", help="Download and normalize IEEE MA-L CSV.")
    update.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    update.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH)
    update.add_argument("--source-url", default=IEEE_MA_L_CSV_URL)
    update.add_argument("--source-file", type=Path)
    update.add_argument("--min-entries", type=int, default=DEFAULT_MIN_ENTRIES)
    update.add_argument(
        "--retrieved-at",
        help="Override the UTC retrieval timestamp (primarily for reproducible tests).",
    )

    validate = subparsers.add_parser(
        "validate", help="Validate the checked-in registry and metadata offline."
    )
    validate.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    validate.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH)
    validate.add_argument("--min-entries", type=int, default=DEFAULT_MIN_ENTRIES)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "update":
            changed = update_registry(
                registry_path=args.registry,
                metadata_path=args.metadata,
                source_url=args.source_url,
                source_file=args.source_file,
                min_entries=args.min_entries,
                retrieved_at=(
                    _parse_retrieved_at(args.retrieved_at)
                    if args.retrieved_at
                    else None
                ),
            )
            count = validate_bundled_registry(
                registry_path=args.registry,
                metadata_path=args.metadata,
                min_entries=args.min_entries,
                expected_source_url=args.source_url,
            )
            state = "updated" if changed else "already current"
            print(f"OUI registry {state}: {count} IEEE MA-L assignments.")
        else:
            count = validate_bundled_registry(
                registry_path=args.registry,
                metadata_path=args.metadata,
                min_entries=args.min_entries,
            )
            print(f"OUI registry valid: {count} IEEE MA-L assignments.")
    except RegistryUpdateError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
