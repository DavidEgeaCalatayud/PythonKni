from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path

from .models import AddressFamily, PathEvent, PathHistoryPoint, TraceProtocol, TraceRequest

MIN_INTERVAL_SECONDS = 0.5
MAX_INTERVAL_SECONDS = 30.0
MIN_TTL = 1
MAX_TTL = 64
JSONL_TRIM_BYTES = 8 * 1024 * 1024
JSONL_MAX_RECORDS = 10_000
HOST_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def validate_target(value: str) -> str:
    target = str(value).strip().rstrip(".")
    if not target:
        raise ValueError("Introduce un hostname o una dirección IP de destino.")
    if len(target) > 253:
        raise ValueError("El destino es demasiado largo.")
    if any(character.isspace() for character in target):
        raise ValueError("El destino debe ser un único hostname o IP, sin espacios.")
    if "/" in target or "\\" in target or "," in target or ";" in target:
        raise ValueError("Network Path Analyzer acepta un único hostname o IP, no rangos ni listas.")
    if "://" in target:
        raise ValueError("Introduce solo el hostname o IP, sin esquema URL.")

    try:
        return str(ipaddress.ip_address(target))
    except ValueError:
        pass

    try:
        ascii_target = target.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValueError("El hostname no tiene un formato DNS válido.") from error
    labels = ascii_target.split(".")
    if not labels or any(not HOST_LABEL_PATTERN.fullmatch(label) for label in labels):
        raise ValueError("El hostname no tiene un formato DNS válido.")
    return ascii_target.lower()


def normalize_protocol(value: TraceProtocol | str) -> TraceProtocol:
    if isinstance(value, TraceProtocol):
        return value
    try:
        return TraceProtocol(str(value).strip().lower())
    except ValueError as error:
        raise ValueError("El protocolo debe ser ICMP, UDP o TCP.") from error


def normalize_address_family(value: AddressFamily | str) -> AddressFamily:
    if isinstance(value, AddressFamily):
        return value
    try:
        return AddressFamily(str(value).strip().lower())
    except ValueError as error:
        raise ValueError("La familia de direcciones debe ser automática, IPv4 o IPv6.") from error


def normalize_interval(value: float | int | str) -> float:
    try:
        interval = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("El intervalo debe ser numérico.") from error
    if interval < MIN_INTERVAL_SECONDS or interval > MAX_INTERVAL_SECONDS:
        raise ValueError(
            f"El intervalo debe estar entre {MIN_INTERVAL_SECONDS:g} y {MAX_INTERVAL_SECONDS:g} s."
        )
    return interval


def normalize_max_ttl(value: int | str) -> int:
    try:
        ttl = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Max TTL debe ser un número entero.") from error
    if ttl < MIN_TTL or ttl > MAX_TTL:
        raise ValueError(f"Max TTL debe estar entre {MIN_TTL} y {MAX_TTL}.")
    return ttl


def normalize_port(value: int | str | None) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        port = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("El puerto debe ser un número entero.") from error
    if port < 1 or port > 65535:
        raise ValueError("El puerto debe estar entre 1 y 65535.")
    return port


def build_request(
    target: str,
    *,
    protocol: TraceProtocol | str = TraceProtocol.ICMP,
    interval_seconds: float | int | str = 1.0,
    max_ttl: int | str = 30,
    port: int | str | None = None,
    address_family: AddressFamily | str = AddressFamily.AUTO,
) -> TraceRequest:
    normalized_protocol = normalize_protocol(protocol)
    normalized_port = normalize_port(port)
    if normalized_protocol is TraceProtocol.ICMP:
        normalized_port = None
    return TraceRequest(
        target=validate_target(target),
        protocol=normalized_protocol,
        interval_seconds=normalize_interval(interval_seconds),
        max_ttl=normalize_max_ttl(max_ttl),
        port=normalized_port,
        address_family=normalize_address_family(address_family),
    )


def _append_jsonl_bounded(path: Path, records: tuple[dict[str, object], ...]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    try:
        oversized = path.stat().st_size > JSONL_TRIM_BYTES
    except OSError:
        return
    if not oversized:
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-JSONL_MAX_RECORDS:]
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
        temporary.replace(path)
    except OSError:
        return


def append_history_jsonl(path: Path, point: PathHistoryPoint) -> None:
    _append_jsonl_bounded(
        path,
        (
            {
                "timestamp": point.timestamp,
                "target": point.target,
                "destination_rtt_ms": point.destination_rtt_ms,
                "destination_loss_pct": point.destination_loss_pct,
                "hop_count": point.hop_count,
                "reached_destination": point.reached_destination,
                "issue_hop_ttl": point.issue_hop_ttl,
            },
        ),
    )


def append_events_jsonl(path: Path, events: tuple[PathEvent, ...]) -> None:
    _append_jsonl_bounded(
        path,
        tuple(
            {
                "event_id": event.event_id,
                "kind": event.kind,
                "severity": event.severity.value,
                "timestamp": event.timestamp,
                "title": event.title,
                "description": event.description,
                "target": event.target,
                "hop_ttl": event.hop_ttl,
                "hop_ip": event.hop_ip,
            }
            for event in events
        ),
    )
