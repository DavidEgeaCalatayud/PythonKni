# WiFi Auditor

`WiFi Auditor` is PythonKni's defensive wireless-security auditing tool. It combines a Windows-visible network inventory, deterministic security findings, an automatically ranked defensive review plan, optional offline PCAP/PCAPNG inspection and verifiable evidence reporting in one menu.

```text
Windows visible-network snapshot
             ↓
SSID / BSSID normalization
             ↓
band / channel / signal / security inventory
             ↓
configuration findings + score
             ↓
ranked defensive audit plan
             ↓
optional offline capture inspection
             ↓
JSON evidence report + SHA-256 integrity digest
```

The tool is intended for systems and wireless environments you own or are explicitly authorized to assess.

## Full Auto defensive workflow

Choose **WiFi Auditor** from the `Red` category and press **Escanear redes visibles**. One managed background task performs discovery, normalization, analysis, scoring and plan generation; no manual chaining with other PythonKni tools is required.

The table records the information exposed by Windows for each visible BSSID:

- SSID;
- BSSID;
- inferred or explicitly reported band;
- channel;
- signal percentage;
- authentication scheme;
- encryption scheme;
- a simple configuration rating.

The parser accepts the English and Spanish labels currently produced by `netsh wlan show networks mode=bssid` and does not require stored WiFi credentials.

## Findings and score

The rules are deterministic and explainable. They can flag:

- open wireless networks;
- legacy WiFi security configurations, including WEP/TKIP;
- the same SSID appearing with inconsistent visible security policies across BSSID;
- a channel with a high number of simultaneously visible BSSID;
- an empty snapshot when Windows exposes no visible access points.

The score starts at `100` and applies documented penalties for findings. It is a triage aid, not a certification score and not proof that an access point is compromised.

SSID-policy inconsistencies are deliberately described as items for manual verification. They can be caused by legitimate mixed deployments, migration states, guest infrastructure or misconfiguration; the tool does not attribute a BSSID as a rogue access point solely from that observation.

## Ranked defensive audit plan

The audit report contains a deterministic `plan[]` ordered by priority. The plan is inspired by the useful orchestration idea of target-aware wireless tooling, but the actions are defensive review steps rather than password-recovery strategies.

Depending on the visible inventory, the plan can prioritize:

1. encryption/security-policy review;
2. SSID/BSSID consistency and authorized-inventory review;
3. completion of unknown security capabilities;
4. RF/channel-planning review;
5. offline inspection of an already existing authorized capture;
6. preservation of a SHA-256-verifiable baseline.

Every plan item contains a stable code, priority, title, rationale and recommended action. The plan is part of the canonical report payload and therefore covered by the report integrity digest.

## Offline PCAP/PCAPNG inspection

Press **Analizar captura offline** to inspect an existing capture file without interacting with the wireless interface or target network.

The inspection:

- accepts recognized PCAP/PCAPNG file headers;
- records file size and SHA-256;
- supports cooperative cancellation while hashing large files;
- optionally uses a locally installed `tshark` executable to count EAPOL and RSN frames;
- degrades to built-in metadata-only inspection when `tshark` is unavailable or fails.

This is protocol/evidence inspection only. PythonKni does not extract password hashes, PMKID material, keys or credentials from the capture and does not submit the capture to a cracking engine.

`tshark` is an optional external executable and is outside PythonKni's Python dependency lock/SBOM. Capture files are untrusted parser input, so only analyze files from a trusted or intentionally isolated assessment workflow.

## Cancellation and errors

Both visible-network inventory and offline capture inspection run through PythonKni's managed `Worker` lifecycle and support cooperative cancellation. A second operation cannot replace one that is already running.

Technical failures use the shared structured-feedback contract: the primary message remains actionable while the original exception is retained in expandable diagnostic details.

## Evidence report

The current report schema (`schema_version = 2`) includes:

```text
schema_version
generated_at
score
access_points[]
findings[]
plan[]
limitations[]
evidence_sha256
```

Before the `evidence_sha256` field is added, the report payload is serialized into canonical JSON (sorted keys and stable separators). PythonKni calculates SHA-256 over that canonical payload.

Report publication is transactional at the filesystem level: PythonKni writes a same-directory temporary file, flushes and `fsync`s it, then publishes it with `os.replace`. If publication fails, a previous destination is not intentionally replaced by a partial report and temporary output is cleaned up where possible.

### Integrity semantics

The SHA-256 value detects accidental or deliberate changes to the exported payload when it is re-verified. It is **not a digital signature**, does not prove who generated the report and does not establish chain-of-custody authenticity by itself.

For stronger provenance in a future release, the evidence format could be extended with optional signing using a user-controlled key without changing the current deterministic report model.

## Offline verification

A report can be verified directly from the repository:

```powershell
python scripts/verify_wifi_audit_report.py .\wifi-audit.json
```

The command returns `VALID` with exit code `0` when the stored digest matches the canonical payload, `INVALID` with exit code `1` when it does not, and exit code `2` for file/JSON errors.

## Docker verification

Docker support is intentionally limited to **offline evidence verification**. The container does not attempt to control the host WiFi adapter or reproduce the live Windows scan.

Build the verifier image from the repository root:

```powershell
docker build -f docker/wifi-auditor/Dockerfile -t pythonkni-wifi-audit-verifier .
```

Verify an exported report from the current directory:

```powershell
docker run --rm -v "${PWD}:/data:ro" pythonkni-wifi-audit-verifier /data/wifi-audit.json
```

The report directory is mounted read-only.

## Explicit scope boundaries

WiFi Auditor does **not**:

- enable wireless monitor mode;
- inject management/data frames;
- force clients to reconnect or send deauthentication frames;
- perform active WPS attacks or PIN guessing;
- capture authentication exchanges from a live target for password recovery;
- extract PMKID/EAPOL material for cracking;
- obtain or validate WiFi passwords;
- generate target-specific password lists or personal-data wordlists;
- run password cracking;
- create deceptive/clone access points or captive portals that collect credentials;
- verify submitted passwords against a real target PSK.

These boundaries are intentional. They preserve the useful security-engineering aspects of inventory, protocol analysis, target-aware prioritization, evidence integrity, worker orchestration and reporting without creating an automated credential-acquisition pipeline.

## Platform limitations

The live inventory is Windows-specific and currently delegates discovery to:

```text
netsh wlan show networks mode=bssid
```

Consequences include:

- results depend on the installed adapter/driver and Windows permissions;
- this is not monitor-mode capture;
- Windows may omit radio metadata for some access points;
- when an explicit band is unavailable, PythonKni infers a display band from the channel;
- the snapshot is point-in-time and can change immediately as RF conditions change;
- channel counts indicate visible co-channel density, not a full RF spectrum/interference measurement.

## Architecture

WiFi Auditor is a normal first-party layered domain:

```text
pythonkni/wifi_auditor/models.py
             ↑
pythonkni/wifi_auditor/service.py
             ↑
pythonkni/wifi_auditor/window.py
             ↑
tools/wifi_auditor_tool.py
```

The service remains Qt-independent, the window owns orchestration/presentation, and the loader-facing adapter stays thin. `tests/test_architecture_boundaries.py` includes the domain in the same dependency checks as the rest of PythonKni.

Dedicated CI/release coverage ratchets protect both the service and window at `>=98.0%` branch coverage.