from __future__ import annotations

import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from .http import HTTP_TIMEOUT_SECONDS, MAX_HTTP_BODY_BYTES, USER_AGENT
from .models import DiscoveredUrl, PortResult, ReconTarget, SubdomainResult

MAX_CT_SUBDOMAINS = 50
MAX_WAYBACK_URLS = 60
MAX_CRAWL_URLS = 30
MAX_CRAWL_REQUESTS = 12
MAX_PATH_RESULTS = 20
PORT_WORKERS = 8
PORT_TIMEOUT_SECONDS = 0.75
COMMON_PORTS = (
    22,
    25,
    53,
    80,
    110,
    143,
    389,
    443,
    445,
    465,
    587,
    636,
    993,
    995,
    1433,
    3306,
    3389,
    5432,
    6379,
    8080,
    8443,
)
SERVICE_NAMES = {
    22: "SSH",
    25: "SMTP",
    53: "DNS",
    80: "HTTP",
    110: "POP3",
    143: "IMAP",
    389: "LDAP",
    443: "HTTPS",
    445: "SMB",
    465: "SMTPS",
    587: "SMTP-SUBMISSION",
    636: "LDAPS",
    993: "IMAPS",
    995: "POP3S",
    1433: "MSSQL",
    3306: "MYSQL",
    3389: "RDP",
    5432: "POSTGRESQL",
    6379: "REDIS",
    8080: "HTTP-ALT",
    8443: "HTTPS-ALT",
}
COMMON_PATHS = (
    "/robots.txt",
    "/sitemap.xml",
    "/.well-known/security.txt",
    "/login",
    "/admin/",
    "/api/",
    "/docs/",
    "/swagger/",
    "/health",
    "/status",
    "/wp-login.php",
)


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name.casefold() in {"href", "src", "action"} and value:
                self.links.append(value)


def _canonical(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _same_origin(url: str, target: ReconTarget) -> bool:
    parsed = urlsplit(url)
    if (parsed.hostname or "").casefold() != target.hostname.casefold():
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme in {"http", "https"} and port == target.port


def certificate_transparency_subdomains(hostname: str) -> tuple[SubdomainResult, ...]:
    try:
        response = requests.get(
            "https://crt.sh/",
            params={"q": f"%.{hostname}", "output": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return ()
    names: set[str] = set()
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            raw = str(item.get("name_value") or "")
            for value in raw.splitlines():
                candidate = value.strip().lower().lstrip("*.").rstrip(".")
                if candidate == hostname or candidate.endswith(f".{hostname}"):
                    names.add(candidate)
                if len(names) >= MAX_CT_SUBDOMAINS:
                    break
            if len(names) >= MAX_CT_SUBDOMAINS:
                break
    results: list[SubdomainResult] = []
    for name in sorted(names)[:MAX_CT_SUBDOMAINS]:
        try:
            addresses = tuple(sorted({item[4][0] for item in socket.getaddrinfo(name, None)}))
        except OSError:
            addresses = ()
        results.append(SubdomainResult(name, addresses))
    return tuple(results)


def wayback_urls(hostname: str) -> tuple[DiscoveredUrl, ...]:
    try:
        response = requests.get(
            "https://web.archive.org/cdx/search/cdx",
            params={
                "url": f"{hostname}/*",
                "output": "json",
                "fl": "original",
                "collapse": "urlkey",
                "filter": "statuscode:200",
                "limit": str(MAX_WAYBACK_URLS + 1),
            },
            headers={"User-Agent": USER_AGENT},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return ()
    urls: list[DiscoveredUrl] = []
    seen: set[str] = set()
    rows = payload[1:] if isinstance(payload, list) and payload else ()
    for row in rows:
        if not isinstance(row, list) or not row:
            continue
        url = str(row[0])
        if url not in seen:
            seen.add(url)
            urls.append(DiscoveredUrl(url, "wayback"))
        if len(urls) >= MAX_WAYBACK_URLS:
            break
    return tuple(urls)


def _get_small(url: str) -> tuple[int | None, str]:
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=HTTP_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
        )
        data = response.raw.read(MAX_HTTP_BODY_BYTES, decode_content=True)
        text = data.decode(response.encoding or "utf-8", errors="replace")
        status = response.status_code
        response.close()
        return status, text
    except requests.RequestException:
        return None, ""


def crawl_same_origin(
    target: ReconTarget,
    initial_html: str,
    *,
    stop_event: threading.Event | None = None,
) -> tuple[DiscoveredUrl, ...]:
    stop_event = stop_event or threading.Event()
    queue = [target.url]
    html_by_url = {target.url: initial_html}
    seen: set[str] = set()
    found: dict[str, DiscoveredUrl] = {}
    requests_made = 0
    while (
        queue
        and not stop_event.is_set()
        and len(found) < MAX_CRAWL_URLS
        and requests_made <= MAX_CRAWL_REQUESTS
    ):
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        html = html_by_url.pop(current, "")
        if not html and requests_made < MAX_CRAWL_REQUESTS:
            status, html = _get_small(current)
            requests_made += 1
            if status is None:
                continue
        parser = _LinkCollector()
        try:
            parser.feed(html)
        except Exception:
            continue
        for raw in parser.links:
            candidate = _canonical(urljoin(current, raw))
            if not _same_origin(candidate, target):
                continue
            if candidate not in found:
                found[candidate] = DiscoveredUrl(candidate, "crawl")
                queue.append(candidate)
            if len(found) >= MAX_CRAWL_URLS:
                break
    return tuple(found.values())


def probe_common_paths(
    target: ReconTarget,
    *,
    stop_event: threading.Event | None = None,
) -> tuple[DiscoveredUrl, ...]:
    stop_event = stop_event or threading.Event()
    phantom_url = urljoin(target.origin + "/", ".pythonkni-not-found-probe-7f9c2b")
    phantom_status, phantom_body = _get_small(phantom_url)
    results: list[DiscoveredUrl] = []
    for path in COMMON_PATHS:
        if stop_event.is_set():
            break
        url = urljoin(target.origin + "/", path.lstrip("/"))
        status, body = _get_small(url)
        if status is None or status == 404:
            continue
        soft_404 = (
            phantom_status is not None
            and status == phantom_status
            and abs(len(body) - len(phantom_body)) <= max(32, int(len(phantom_body) * 0.15))
        )
        if soft_404:
            continue
        results.append(DiscoveredUrl(url, "common-path", status))
        if len(results) >= MAX_PATH_RESULTS:
            break
    return tuple(results)


def _port_open(hostname: str, port: int) -> bool:
    try:
        with socket.create_connection((hostname, port), timeout=PORT_TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


def scan_common_ports(
    hostname: str,
    *,
    stop_event: threading.Event | None = None,
) -> tuple[PortResult, ...]:
    stop_event = stop_event or threading.Event()
    found: list[PortResult] = []
    with ThreadPoolExecutor(max_workers=PORT_WORKERS) as executor:
        future_to_port = {
            executor.submit(_port_open, hostname, port): port for port in COMMON_PORTS
        }
        for future in as_completed(future_to_port):
            if stop_event.is_set():
                for pending in future_to_port:
                    pending.cancel()
                break
            port = future_to_port[future]
            try:
                opened = future.result()
            except OSError:
                opened = False
            if opened:
                found.append(PortResult(port, SERVICE_NAMES.get(port, "TCP")))
    return tuple(sorted(found, key=lambda item: item.port))
