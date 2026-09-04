from __future__ import annotations

import re
import threading
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

from .discovery import (
    certificate_transparency_subdomains,
    crawl_same_origin,
    probe_common_paths,
    scan_common_ports,
    wayback_urls,
)
from .dns import collect_dns, registrable_domain_candidate, resolve_addresses
from .http import detect_technologies, inspect_http
from .intelligence import enrich_ports_with_nerva
from .models import (
    FindingSeverity,
    ReconFinding,
    ReconProgress,
    ReconReport,
    ReconTarget,
)
from .tls import inspect_tls
from .whois import inspect_whois

_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
    re.IGNORECASE,
)


def normalize_target(value: str) -> ReconTarget:
    raw = value.strip()
    if not raw:
        raise ValueError("Introduce una URL o dominio.")
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlsplit(candidate)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("Solo se admiten objetivos HTTP o HTTPS.")
    if parsed.username or parsed.password:
        raise ValueError("No introduzcas credenciales en la URL de reconocimiento.")
    hostname = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
    if not hostname or not _HOST_RE.fullmatch(hostname):
        raise ValueError("El hostname del objetivo no es válido.")
    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as error:
        raise ValueError("El puerto de la URL no es válido.") from error
    if port < 1 or port > 65535:
        raise ValueError("El puerto de la URL no es válido.")
    path = parsed.path or "/"
    netloc = hostname
    if not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{hostname}:{port}"
    url = urlunsplit((scheme, netloc, path, parsed.query, ""))
    return ReconTarget(raw, url, scheme, hostname, port)


def _finding(
    finding_id: str,
    severity: FindingSeverity,
    category: str,
    title: str,
    description: str,
    evidence: str = "",
) -> ReconFinding:
    return ReconFinding(finding_id, severity, category, title, description, evidence)


def build_findings(report: ReconReport) -> tuple[ReconFinding, ...]:
    findings: list[ReconFinding] = []
    if report.dns.dmarc_policy in {"", "none"}:
        findings.append(
            _finding(
                "web.dmarc.weak",
                FindingSeverity.WARNING,
                "DNS",
                "DMARC policy is absent or monitoring-only",
                "A missing DMARC record or p=none does not request quarantine/reject enforcement.",
                report.dns.dmarc[0] if report.dns.dmarc else "No DMARC record observed",
            )
        )
    if report.dns.dnssec_published is False:
        findings.append(
            _finding(
                "web.dnssec.not-published",
                FindingSeverity.INFO,
                "DNS",
                "DNSSEC records were not observed",
                "PythonKni did not observe DNSKEY publication for this hostname; "
                "this is a presence check, not full chain validation.",
            )
        )
    if report.tls.available and report.tls.expires_in_days is not None:
        if report.tls.expires_in_days < 0:
            findings.append(
                _finding(
                    "web.tls.expired",
                    FindingSeverity.HIGH,
                    "TLS",
                    "TLS certificate is expired",
                    "The certificate validity period has ended.",
                    report.tls.not_after,
                )
            )
        elif report.tls.expires_in_days <= 30:
            findings.append(
                _finding(
                    "web.tls.expiring",
                    FindingSeverity.WARNING,
                    "TLS",
                    "TLS certificate expires soon",
                    f"Certificate expires in {report.tls.expires_in_days} day(s).",
                    report.tls.not_after,
                )
            )
    for check in report.http.checks:
        if not check.passed:
            findings.append(
                _finding(
                    f"web.http.{check.name.casefold().replace(' ', '-').replace('/', '-')}",
                    FindingSeverity.WARNING,
                    "HTTP Security",
                    f"{check.name} missing or weak",
                    check.recommendation,
                    check.observed or "Header not observed",
                )
            )
    for cookie in report.http.cookies:
        if not cookie.secure or not cookie.httponly:
            findings.append(
                _finding(
                    f"web.cookie.{cookie.name}.attributes",
                    FindingSeverity.WARNING,
                    "HTTP Security",
                    f"Cookie {cookie.name} lacks defensive attributes",
                    "Session/security-sensitive cookies should normally use Secure and "
                    "HttpOnly; SameSite should be reviewed for the application flow.",
                    f"Secure={cookie.secure}; HttpOnly={cookie.httponly}; "
                    f"SameSite={cookie.samesite or 'unset'}",
                )
            )
    return tuple(findings)


def run_recon(
    target_value: str,
    *,
    include_external_sources: bool = False,
    include_active_discovery: bool = False,
    include_nerva: bool = True,
    stop_event: threading.Event | None = None,
    on_progress: Callable[[ReconProgress], None] | None = None,
) -> ReconReport:
    stop_event = stop_event or threading.Event()

    def progress(stage: str, message: str) -> None:
        if stop_event.is_set():
            return
        if on_progress is not None:
            on_progress(ReconProgress(stage, message))

    target = normalize_target(target_value)
    progress("target", f"Resolviendo {target.hostname}...")
    addresses = resolve_addresses(target.hostname)
    if stop_event.is_set():
        return ReconReport(target=target, addresses=addresses)

    base_domain = registrable_domain_candidate(target.hostname)
    progress("dns", "Analizando DNS, SPF, DMARC y publicación DNSSEC...")
    dns = collect_dns(target.hostname, addresses, mail_domain=base_domain)
    progress("whois", f"Consultando WHOIS de {base_domain}...")
    whois = inspect_whois(base_domain)
    progress("tls", "Inspeccionando TLS y certificado...")
    tls = (
        inspect_tls(target.hostname, target.port)
        if target.scheme == "https"
        else inspect_tls(target.hostname, 443)
    )
    progress("http", "Auditando respuesta HTTP, headers y cookies...")
    http = inspect_http(target)
    technologies = detect_technologies(http)

    subdomains = ()
    archived = ()
    if include_external_sources and not stop_event.is_set():
        progress(
            "external",
            "Consultando Certificate Transparency y Wayback con límites estrictos...",
        )
        subdomains = certificate_transparency_subdomains(base_domain)
        archived = wayback_urls(target.hostname)

    discovered = list(archived)
    ports = ()
    if include_active_discovery and not stop_event.is_set():
        progress("crawl", "Crawling same-origin y comprobando rutas comunes acotadas...")
        discovered.extend(crawl_same_origin(target, http.body_text, stop_event=stop_event))
        discovered.extend(probe_common_paths(target, stop_event=stop_event))
        progress("ports", "Comprobando un conjunto reducido de puertos de aplicación...")
        ports = scan_common_ports(target.hostname, stop_event=stop_event)
        if include_nerva and ports and not stop_event.is_set():
            progress(
                "nerva",
                "Entregando los puertos abiertos a Nerva para fingerprinting de aplicación...",
            )
            ports = enrich_ports_with_nerva(target.hostname, ports, stop_event=stop_event)

    dedup_urls = {item.url: item for item in discovered}
    report = ReconReport(
        target=target,
        addresses=addresses,
        dns=dns,
        whois=whois,
        tls=tls,
        http=http,
        technologies=technologies,
        subdomains=subdomains,
        discovered_urls=tuple(dedup_urls.values()),
        ports=ports,
    )
    return ReconReport(
        target=report.target,
        addresses=report.addresses,
        dns=report.dns,
        whois=report.whois,
        tls=report.tls,
        http=report.http,
        technologies=report.technologies,
        subdomains=report.subdomains,
        discovered_urls=report.discovered_urls,
        ports=report.ports,
        findings=build_findings(report),
    )
