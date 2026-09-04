from __future__ import annotations

import socket

from .models import WhoisSummary

WHOIS_TIMEOUT_SECONDS = 5.0
MAX_WHOIS_BYTES = 128 * 1024
MAX_WHOIS_EXCERPT_CHARS = 6000


def _query(server: str, query: str) -> str:
    chunks: list[bytes] = []
    total = 0
    with socket.create_connection((server, 43), timeout=WHOIS_TIMEOUT_SECONDS) as sock:
        sock.settimeout(WHOIS_TIMEOUT_SECONDS)
        sock.sendall((query + "\r\n").encode("ascii"))
        while total < MAX_WHOIS_BYTES:
            try:
                chunk = sock.recv(min(8192, MAX_WHOIS_BYTES - total))
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


def _pairs(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().casefold()
        value = value.strip()
        if key and value:
            pairs.append((key, value))
    return pairs


def _first(pairs: list[tuple[str, str]], *keys: str) -> str:
    wanted = {key.casefold() for key in keys}
    return next((value for key, value in pairs if key in wanted), "")


def inspect_whois(domain: str) -> WhoisSummary:
    try:
        iana = _query("whois.iana.org", domain)
        iana_pairs = _pairs(iana)
        referral = _first(iana_pairs, "refer", "whois")
        if referral.startswith("whois://"):
            referral = referral.removeprefix("whois://").split("/", 1)[0]
        raw = _query(referral, domain) if referral else iana
        pairs = _pairs(raw)
    except OSError as error:
        return WhoisSummary(error=str(error))

    nameservers = tuple(
        dict.fromkeys(
            value.rstrip(".") for key, value in pairs if key in {"name server", "nserver"}
        )
    )
    statuses = tuple(
        dict.fromkeys(value for key, value in pairs if key in {"domain status", "status"})
    )
    return WhoisSummary(
        registrar=_first(pairs, "registrar", "registrar name", "sponsoring registrar"),
        created=_first(pairs, "creation date", "created", "registered on"),
        expires=_first(
            pairs, "registry expiry date", "expiration date", "expiry date", "paid-till"
        ),
        nameservers=nameservers,
        statuses=statuses,
        referral_server=referral,
        raw_excerpt=raw[:MAX_WHOIS_EXCERPT_CHARS],
    )
