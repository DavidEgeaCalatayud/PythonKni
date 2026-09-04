from __future__ import annotations

import socket
import ssl
from datetime import datetime, timezone

from .models import TlsSummary

TLS_TIMEOUT_SECONDS = 5.0


def _name(value: object) -> str:
    parts: list[str] = []
    if isinstance(value, tuple):
        for group in value:
            if not isinstance(group, tuple):
                continue
            for item in group:
                if isinstance(item, tuple) and len(item) == 2:
                    parts.append(f"{item[0]}={item[1]}")
    return ", ".join(parts)


def inspect_tls(hostname: str, port: int) -> TlsSummary:
    context = ssl.create_default_context()
    try:
        with socket.create_connection((hostname, port), timeout=TLS_TIMEOUT_SECONDS) as raw:
            with context.wrap_socket(raw, server_hostname=hostname) as tls_socket:
                certificate = tls_socket.getpeercert()
                cipher = tls_socket.cipher()
                version = tls_socket.version() or ""
    except (OSError, ssl.SSLError) as error:
        return TlsSummary(error=str(error))

    not_after = str(certificate.get("notAfter") or "")
    expires_in_days = None
    if not_after:
        try:
            expiry = datetime.fromtimestamp(
                ssl.cert_time_to_seconds(not_after), tz=timezone.utc
            )
            expires_in_days = int((expiry - datetime.now(timezone.utc)).total_seconds() // 86400)
        except (ValueError, OverflowError):
            expires_in_days = None
    sans = tuple(
        str(value)
        for kind, value in certificate.get("subjectAltName", ())
        if kind == "DNS"
    )
    return TlsSummary(
        available=True,
        version=version,
        cipher=str(cipher[0]) if cipher else "",
        subject=_name(certificate.get("subject")),
        issuer=_name(certificate.get("issuer")),
        serial_number=str(certificate.get("serialNumber") or ""),
        not_before=str(certificate.get("notBefore") or ""),
        not_after=not_after,
        expires_in_days=expires_in_days,
        sans=sans,
    )
