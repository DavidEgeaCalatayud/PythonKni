from __future__ import annotations

import json
import platform
import shutil
import socket
import subprocess
from collections.abc import Iterable

from .models import DnsRecord, DnsSummary

DNS_QUERY_TYPES = ("MX", "NS", "TXT", "CNAME", "DNSKEY")
MAX_DNS_RECORDS = 200
POWERSHELL_TIMEOUT_SECONDS = 8.0

COMMON_MULTIPART_SUFFIXES = frozenset(
    {
        "co.uk",
        "org.uk",
        "ac.uk",
        "com.au",
        "net.au",
        "org.au",
        "co.jp",
        "com.br",
        "com.mx",
        "com.ar",
        "com.tr",
        "com.cn",
        "co.in",
        "com.es",
    }
)


def registrable_domain_candidate(hostname: str) -> str:
    labels = hostname.rstrip(".").lower().split(".")
    if len(labels) <= 2:
        return ".".join(labels)
    suffix2 = ".".join(labels[-2:])
    if suffix2 in COMMON_MULTIPART_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return suffix2


def resolve_addresses(hostname: str) -> tuple[str, ...]:
    values: set[str] = set()
    for family, _socktype, _proto, _canonname, sockaddr in socket.getaddrinfo(
        hostname, None, type=socket.SOCK_STREAM
    ):
        if family in {socket.AF_INET, socket.AF_INET6}:
            values.add(str(sockaddr[0]).split("%", 1)[0])
    return tuple(sorted(values, key=lambda value: (":" in value, value)))


def _powershell_executable() -> str | None:
    candidates = ("powershell.exe", "powershell", "pwsh")
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _record_value(item: dict[str, object]) -> tuple[str, int | None]:
    preference = item.get("Preference")
    pref = int(preference) if isinstance(preference, (int, float)) else None
    for key in ("IPAddress", "NameExchange", "NameHost"):
        value = item.get(key)
        if value:
            return str(value).rstrip("."), pref
    key = item.get("Key")
    if key:
        algorithm = item.get("Algorithm")
        value = f"algorithm={algorithm}; key={key}" if algorithm is not None else str(key)
        return value, pref
    digest = item.get("Digest")
    if digest:
        return str(digest), pref
    strings = item.get("Strings")
    if isinstance(strings, list):
        return "".join(str(part) for part in strings), pref
    if strings:
        return str(strings), pref
    return "", pref


def query_windows_dns(hostname: str, record_type: str) -> tuple[DnsRecord, ...]:
    normalized = record_type.upper()
    if normalized not in DNS_QUERY_TYPES:
        raise ValueError(f"Unsupported DNS record type: {record_type}")
    executable = _powershell_executable()
    if executable is None or platform.system().lower() != "windows":
        return ()
    # hostname is normalized/validated before this module is called; record type is allow-listed.
    script = (
        f"Resolve-DnsName -Name '{hostname}' -Type {normalized} -ErrorAction Stop | "
        "Select-Object Name,Type,IPAddress,NameExchange,NameHost,Strings,Preference,"
        "Flags,Protocol,Algorithm,Key,KeyTag,Digest,DigestType | "
        "ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=POWERSHELL_TIMEOUT_SECONDS,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return ()
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ()
    items: Iterable[object] = payload if isinstance(payload, list) else (payload,)
    records: list[DnsRecord] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        value, preference = _record_value(raw)
        if not value:
            continue
        records.append(
            DnsRecord(
                record_type=normalized,
                name=str(raw.get("Name") or hostname).rstrip("."),
                value=value,
                preference=preference,
            )
        )
        if len(records) >= MAX_DNS_RECORDS:
            break
    return tuple(records)


def _dmarc_policy(records: Iterable[str]) -> str:
    for record in records:
        for part in record.split(";"):
            name, separator, value = part.strip().partition("=")
            if separator and name.strip().lower() == "p":
                return value.strip().lower()
    return ""


def collect_dns(
    hostname: str,
    addresses: tuple[str, ...],
    *,
    mail_domain: str | None = None,
) -> DnsSummary:
    records: list[DnsRecord] = []
    for address in addresses:
        records.append(DnsRecord("AAAA" if ":" in address else "A", hostname, address))
    try:
        for record_type in DNS_QUERY_TYPES:
            query_name = (mail_domain or hostname) if record_type == "DNSKEY" else hostname
            records.extend(query_windows_dns(query_name, record_type))
        txt_values = tuple(item.value for item in records if item.record_type == "TXT")
        spf = tuple(value for value in txt_values if value.lower().startswith("v=spf1"))
        email_domain = mail_domain or registrable_domain_candidate(hostname)
        dmarc_records = query_windows_dns(f"_dmarc.{email_domain}", "TXT")
        records.extend(dmarc_records)
        dmarc = tuple(
            item.value for item in dmarc_records if item.value.lower().startswith("v=dmarc1")
        )
        dnssec = any(item.record_type == "DNSKEY" for item in records)
        return DnsSummary(
            records=tuple(records[:MAX_DNS_RECORDS]),
            spf=spf,
            dmarc=dmarc,
            dmarc_policy=_dmarc_policy(dmarc),
            dnssec_published=dnssec,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        return DnsSummary(records=tuple(records), error=str(error))
