from __future__ import annotations

import re
from http.cookies import SimpleCookie
from urllib.parse import urljoin, urlsplit

import requests

from .models import (
    CookieAssessment,
    HttpCheck,
    HttpSummary,
    ReconTarget,
    TechnologyEvidence,
)

HTTP_TIMEOUT_SECONDS = 6.0
MAX_HTTP_BODY_BYTES = 512 * 1024
MAX_REDIRECTS = 3
USER_AGENT = "PythonKni-WebRecon/1.0"


def _same_host(url: str, target: ReconTarget) -> bool:
    parsed = urlsplit(url)
    return (parsed.hostname or "").casefold() == target.hostname.casefold()


def _read_bounded(response: requests.Response) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=16384):
        if not chunk:
            continue
        remaining = MAX_HTTP_BODY_BYTES - total
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        total += min(len(chunk), remaining)
        if total >= MAX_HTTP_BODY_BYTES:
            break
    return b"".join(chunks)


def fetch_target(target: ReconTarget) -> tuple[requests.Response, str, str]:
    current = target.url
    session = requests.Session()
    for _ in range(MAX_REDIRECTS + 1):
        response = session.get(
            current,
            headers={"User-Agent": USER_AGENT},
            timeout=HTTP_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
        )
        body = _read_bounded(response)
        encoding = response.encoding or "utf-8"
        text = body.decode(encoding, errors="replace")
        location = response.headers.get("Location")
        if response.is_redirect and location:
            candidate = urljoin(current, location)
            if not _same_host(candidate, target):
                return response, current, text
            current = candidate
            response.close()
            continue
        return response, current, text
    return response, current, text


def _header_checks(
    headers: requests.structures.CaseInsensitiveDict[str],
) -> tuple[HttpCheck, ...]:
    csp = headers.get("Content-Security-Policy", "")
    frame = headers.get("X-Frame-Options", "")
    checks = (
        HttpCheck(
            "HSTS",
            bool(headers.get("Strict-Transport-Security")),
            headers.get("Strict-Transport-Security", ""),
            "Enable Strict-Transport-Security on HTTPS sites.",
        ),
        HttpCheck(
            "CSP",
            bool(csp),
            csp,
            "Define a restrictive Content-Security-Policy.",
        ),
        HttpCheck(
            "X-Content-Type-Options",
            headers.get("X-Content-Type-Options", "").lower() == "nosniff",
            headers.get("X-Content-Type-Options", ""),
            "Set X-Content-Type-Options: nosniff.",
        ),
        HttpCheck(
            "Clickjacking protection",
            bool(frame) or "frame-ancestors" in csp.lower(),
            frame or csp,
            "Use frame-ancestors in CSP or X-Frame-Options.",
        ),
        HttpCheck(
            "Referrer-Policy",
            bool(headers.get("Referrer-Policy")),
            headers.get("Referrer-Policy", ""),
            "Set an explicit Referrer-Policy.",
        ),
        HttpCheck(
            "Permissions-Policy",
            bool(headers.get("Permissions-Policy")),
            headers.get("Permissions-Policy", ""),
            "Set an explicit Permissions-Policy where applicable.",
        ),
    )
    return checks


def _cookies(response: requests.Response) -> tuple[CookieAssessment, ...]:
    raw_headers = getattr(response.raw, "headers", None)
    values = []
    if raw_headers is not None and hasattr(raw_headers, "getlist"):
        values = list(raw_headers.getlist("Set-Cookie"))
    if not values and response.headers.get("Set-Cookie"):
        values = [response.headers["Set-Cookie"]]
    assessments: list[CookieAssessment] = []
    for value in values:
        cookie = SimpleCookie()
        try:
            cookie.load(value)
        except Exception:
            continue
        for name, morsel in cookie.items():
            assessments.append(
                CookieAssessment(
                    name=name,
                    secure=bool(morsel["secure"]),
                    httponly=bool(morsel["httponly"]),
                    samesite=str(morsel["samesite"] or ""),
                )
            )
    return tuple(assessments)


def inspect_http(target: ReconTarget) -> HttpSummary:
    try:
        response, final_url, body = fetch_target(target)
    except requests.RequestException as error:
        return HttpSummary(error=str(error))
    try:
        return HttpSummary(
            final_url=final_url,
            status_code=response.status_code,
            headers=tuple(
                sorted((str(key), str(value)) for key, value in response.headers.items())
            ),
            checks=_header_checks(response.headers),
            cookies=_cookies(response),
            body_text=body,
        )
    finally:
        response.close()


def detect_technologies(summary: HttpSummary) -> tuple[TechnologyEvidence, ...]:
    headers = {key.casefold(): value for key, value in summary.headers}
    body = summary.body_text.casefold()
    evidence: dict[str, TechnologyEvidence] = {}

    server = headers.get("server", "").strip()
    if server:
        evidence[f"Server: {server}"] = TechnologyEvidence(
            server, f"Server header: {server}", "high"
        )
    powered = headers.get("x-powered-by", "").strip()
    if powered:
        evidence[f"Powered: {powered}"] = TechnologyEvidence(
            powered, f"X-Powered-By: {powered}", "high"
        )
    if "cf-ray" in headers or "cloudflare" in server.casefold():
        evidence["Cloudflare"] = TechnologyEvidence(
            "Cloudflare", "Cloudflare response headers", "high"
        )
    if "wp-content/" in body or "wp-includes/" in body:
        evidence["WordPress"] = TechnologyEvidence(
            "WordPress", "HTML references wp-content/wp-includes", "high"
        )
    if re.search(r"<meta[^>]+name=[\"']generator[\"'][^>]+wordpress", body):
        evidence["WordPress"] = TechnologyEvidence(
            "WordPress", "Generator meta tag", "high"
        )
    cookie_names = {item.name.casefold() for item in summary.cookies}
    if "phpsessid" in cookie_names:
        evidence["PHP"] = TechnologyEvidence("PHP", "PHPSESSID cookie", "medium")
    if "jsessionid" in cookie_names:
        evidence["Java/Jakarta"] = TechnologyEvidence(
            "Java/Jakarta", "JSESSIONID cookie", "medium"
        )
    if "asp.net_sessionid" in cookie_names:
        evidence["ASP.NET"] = TechnologyEvidence(
            "ASP.NET", "ASP.NET_SessionId cookie", "medium"
        )
    if "laravel_session" in cookie_names:
        evidence["Laravel"] = TechnologyEvidence(
            "Laravel", "laravel_session cookie", "medium"
        )
    return tuple(sorted(evidence.values(), key=lambda item: item.name.casefold()))
