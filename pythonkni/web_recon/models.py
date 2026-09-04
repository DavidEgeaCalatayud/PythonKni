from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FindingSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class ReconTarget:
    input_value: str
    url: str
    scheme: str
    hostname: str
    port: int

    @property
    def origin(self) -> str:
        default = (self.scheme == "https" and self.port == 443) or (
            self.scheme == "http" and self.port == 80
        )
        suffix = "" if default else f":{self.port}"
        return f"{self.scheme}://{self.hostname}{suffix}"


@dataclass(frozen=True, slots=True)
class DnsRecord:
    record_type: str
    name: str
    value: str
    preference: int | None = None


@dataclass(frozen=True, slots=True)
class DnsSummary:
    records: tuple[DnsRecord, ...] = ()
    spf: tuple[str, ...] = ()
    dmarc: tuple[str, ...] = ()
    dmarc_policy: str = ""
    dnssec_published: bool | None = None
    error: str = ""


@dataclass(frozen=True, slots=True)
class WhoisSummary:
    registrar: str = ""
    created: str = ""
    expires: str = ""
    nameservers: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    referral_server: str = ""
    raw_excerpt: str = ""
    error: str = ""


@dataclass(frozen=True, slots=True)
class TlsSummary:
    available: bool = False
    version: str = ""
    cipher: str = ""
    subject: str = ""
    issuer: str = ""
    serial_number: str = ""
    not_before: str = ""
    not_after: str = ""
    expires_in_days: int | None = None
    sans: tuple[str, ...] = ()
    error: str = ""


@dataclass(frozen=True, slots=True)
class HttpCheck:
    name: str
    passed: bool
    observed: str = ""
    recommendation: str = ""


@dataclass(frozen=True, slots=True)
class CookieAssessment:
    name: str
    secure: bool
    httponly: bool
    samesite: str = ""


@dataclass(frozen=True, slots=True)
class HttpSummary:
    final_url: str = ""
    status_code: int | None = None
    headers: tuple[tuple[str, str], ...] = ()
    checks: tuple[HttpCheck, ...] = ()
    cookies: tuple[CookieAssessment, ...] = ()
    body_text: str = ""
    error: str = ""


@dataclass(frozen=True, slots=True)
class TechnologyEvidence:
    name: str
    evidence: str
    confidence: str = "medium"


@dataclass(frozen=True, slots=True)
class SubdomainResult:
    hostname: str
    addresses: tuple[str, ...] = ()
    source: str = "certificate-transparency"


@dataclass(frozen=True, slots=True)
class DiscoveredUrl:
    url: str
    source: str
    status_code: int | None = None


@dataclass(frozen=True, slots=True)
class PortResult:
    port: int
    service: str
    open: bool = True
    product: str = ""
    version: str = ""
    fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class ReconFinding:
    finding_id: str
    severity: FindingSeverity
    category: str
    title: str
    description: str
    evidence: str = ""


@dataclass(frozen=True, slots=True)
class ReconReport:
    target: ReconTarget
    addresses: tuple[str, ...] = ()
    dns: DnsSummary = field(default_factory=DnsSummary)
    whois: WhoisSummary = field(default_factory=WhoisSummary)
    tls: TlsSummary = field(default_factory=TlsSummary)
    http: HttpSummary = field(default_factory=HttpSummary)
    technologies: tuple[TechnologyEvidence, ...] = ()
    subdomains: tuple[SubdomainResult, ...] = ()
    discovered_urls: tuple[DiscoveredUrl, ...] = ()
    ports: tuple[PortResult, ...] = ()
    findings: tuple[ReconFinding, ...] = ()


@dataclass(frozen=True, slots=True)
class ReconProgress:
    stage: str
    message: str
