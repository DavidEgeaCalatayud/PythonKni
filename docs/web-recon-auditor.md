# Web Recon Auditor

Web Recon Auditor is PythonKni's first-party web reconnaissance domain. It borrows the useful workflow of tools such as FinalRecon but is implemented natively for the Windows-focused PythonKni runtime and reuses PythonKni's verified Nerva integration instead of launching FinalRecon.

## Scope model

Every run starts from one explicit HTTP/HTTPS URL or DNS hostname. PythonKni does not accept CIDR/range input here and does not turn a web audit into internet-wide discovery.

The default run performs direct checks against that explicit target: address resolution, DNS/mail-security posture, WHOIS, TLS/certificate inspection and HTTP security/header/cookie analysis.

Two additional groups are opt-in:

- **External passive sources**: Certificate Transparency (`crt.sh`) and the Internet Archive CDX/Wayback API. Results are capped and the UI makes the external lookup explicit.
- **Active bounded discovery**: same-origin crawl, a small built-in set of common defensive paths and a fixed common-application port set. There is no arbitrary wordlist, credential testing or exploit traffic.

Nerva fingerprinting can be enabled only with active discovery. It receives only ports already observed open on the explicit target and uses the existing verified `pythonkni.network.fingerprinting` path.

## Modules

### DNS and mail security

The target is resolved with the local resolver. On Windows, richer MX/NS/TXT/CNAME/DNSKEY queries use the native PowerShell `Resolve-DnsName` command; no new Python DNS dependency is added.

SPF and DMARC are reported from TXT data. For targets such as `www.example.com`, PythonKni derives a conservative registrable-domain candidate for mail policy checks. The DNSSEC result is deliberately labelled as **DNSKEY publication observed/not observed**. It is not presented as cryptographic validation of the complete DNSSEC chain.

### WHOIS

PythonKni queries `whois.iana.org`, follows a bounded referral when available, caps response size, and extracts registrar, creation/expiry dates, nameservers and status values. WHOIS availability and field quality vary by registry and privacy policy.

### TLS

Python's verified TLS stack performs the handshake with SNI and certificate validation. The report includes negotiated protocol/cipher, subject, issuer, SANs, validity dates and expiry horizon. A failed verification is reported as an error rather than silently falling back to an insecure handshake.

### HTTP security

The response body is capped. Redirects are followed only while the hostname remains the same; an unrelated redirect is surfaced but not followed. Checks include:

- Strict-Transport-Security;
- Content-Security-Policy;
- X-Content-Type-Options;
- clickjacking protection through CSP `frame-ancestors` or X-Frame-Options;
- Referrer-Policy;
- Permissions-Policy;
- cookie Secure / HttpOnly / SameSite attributes.

Technology labels are evidence-based heuristics from headers, cookies and HTML markers. They are not claimed as definitive product/version identification. Nerva remains the application fingerprinting authority for discovered open ports.

### Subdomains and archives

Certificate Transparency names are restricted to the selected base domain and capped. Resolutions are best-effort. Wayback results are deduplicated and capped.

### Crawl and common paths

The crawler stays on the exact HTTP origin and is request/result capped. Common-path discovery uses a small fixed list (`robots.txt`, `sitemap.xml`, `security.txt`, login/admin/API/docs/health/status-style endpoints) and a phantom-path baseline to suppress soft-404 false positives. It is intentionally not a directory brute-forcer.

### Ports and Nerva

The TCP scan uses a fixed list of common application ports with short connect timeouts and bounded concurrency. Nerva is invoked only for ports already observed open and uses conservative worker/connection limits.

## Explicit non-goals

Web Recon Auditor does not perform exploit execution, credential attempts, password spraying, authentication bypass, payload injection, vulnerability-template execution, stealth/evasion, unrestricted directory fuzzing, zone-transfer abuse or mass scanning.

## Architecture

```text
pythonkni/web_recon/
├── models.py
├── service.py
├── dns.py
├── whois.py
├── tls.py
├── http.py
├── discovery.py
├── intelligence.py
└── window.py

tools/web_recon_tool.py
```

`models.py` and `service.py` remain framework-independent. The wrapper stays a thin compatibility adapter and the UI uses the existing managed `Worker` cancellation contract.
