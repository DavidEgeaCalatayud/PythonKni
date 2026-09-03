# Network service fingerprinting

PythonKni separates transport discovery, application identification and security-configuration checks so a normal port scan cannot silently escalate into broader probing. TCP service identification still starts from ports already confirmed open; Service Intelligence v2 adds explicit bounded UDP probing, capability-aware SCTP and an explicit Nerva misconfiguration action.

## Engine and trust model

The optional engine is [Praetorian Nerva](https://github.com/praetorian-inc/nerva), licensed under Apache-2.0. PythonKni does not install `latest` and does not execute an unverified download.

`third_party/nerva.lock.json` pins one exact Windows amd64 release archive and SHA-256 digest. `scripts/fetch_nerva.ps1` downloads only that URL, verifies SHA-256 **before extraction**, requires the upstream license to be present, stages `nerva.exe` plus license/source provenance under the ignored `third_party/nerva/` runtime directory, and records source metadata beside the executable.

The current pin is:

```text
Nerva v1.69.4
nerva_1.69.4_windows_amd64.zip
SHA-256 59e59eb54c8c5c581031387a0aa23c98983db94301e811f3c9b1802a05fc97f7
```

Updating Nerva is therefore an explicit repository change: update the lock metadata, review the upstream release, run tests/CI, and merge the new pin normally.

## Operational modes and safety boundary

Service Intelligence v2 exposes distinct actions rather than one broad scan button:

- **Identify services** keeps the original TCP contract and fingerprints only ports already confirmed open by Network Explorer.
- **UDP probing** is explicit and bounded to selected ports/profiles with strict timeouts. An identified responder is `open`; a probe with no conclusive response is `open|filtered`, never incorrectly treated as closed. The first-party model also represents `closed` and `unknown` when explicit evidence supports those states.
- **Check insecure configurations** is a separate explicit action that enables Nerva `--misconfigs`. Ordinary fingerprinting and scheduled monitoring never add this flag.
- **SCTP** is an advanced capability. Nerva v1.69.4 exposes SCTP only on Linux; PythonKni therefore refuses/disables SCTP on the validated Windows product instead of pretending the bundled Windows engine supports it.
- No mode performs password guessing, default-credential attempts, brute force or exploitation.

All subprocess launches remain argument-list based with `shell=False`, bounded worker/per-host limits, finite timeouts and cooperative cancellation. Use network capabilities only on systems and networks you own or are explicitly authorized to administer.

## First-party domain contract

Nerva JSON is normalized immediately into PythonKni-owned models. A service observation contains transport-aware identity plus zero or more normalized security findings:

```text
ServiceFingerprint
├─ host
├─ ip
├─ port
├─ protocol
├─ transport
├─ product
├─ version
├─ metadata
├─ state
└─ security_findings[]
     ├─ id
     ├─ severity
     ├─ title
     ├─ description
     ├─ impact
     ├─ recommendation
     ├─ cvss
     └─ evidence
```

The finding schema mirrors the useful fields emitted by Nerva v1.69.4 while keeping the rest of PythonKni independent from Nerva's raw JSON. Unknown useful service fields remain in `metadata`.

## Network Intelligence persistence

Manual Network Explorer enrichment remains conservative: accepted results can only be applied to one exact online, already-persisted Network Intelligence asset. Zero matches are rejected rather than synthesizing an asset, ambiguous matches are rejected, and the asset is reloaded before mutation.

Persistence is transport-aware:

- the legacy `open_ports`/`services` tuples remain TCP-only, so `53/tcp` and `53/udp` cannot collide;
- TCP service/product/version changes generate `service_changed` timeline events;
- new UDP/SCTP service evidence generates `service_observed` timeline events without polluting the TCP port tuple;
- newly accepted Nerva findings generate `security_finding` events;
- device kind, classification confidence and persisted `RiskLevel` are not rewritten merely because a service identity or finding exists.

The Security Score consumes persisted finding evidence through deterministic project rules rather than trusting an opaque upstream score. Current deductions are critical `-12`, high `-8`, medium `-4`, low `-1`, info/unknown `0`, capped at **20 points per asset**. This is a bounded review-prioritization heuristic, not a vulnerability or compromise probability.

Because snapshots already serialize the asset services/evidence/timeline state, accepted identity and security-finding changes participate in later history/comparison workflows without requiring a destructive inventory migration.

## Scheduled fingerprinting policy

Network Intelligence exposes four persisted policies:

```text
Disabled
Manual only
Automatic after discovery
Only assets with known changes
```

Automatic policies run only after a successful scheduled discovery/persistence step and before the automatic snapshot is published. They are deliberately narrower than the manual Service Intelligence actions:

- TCP only;
- existing known TCP ports only;
- maximum 32 assets per scheduled pass;
- maximum 16 ports per asset;
- 8 Nerva workers;
- maximum 2 simultaneous connections per host;
- 1500 ms Nerva probe timeout;
- `misconfigs=False` unconditionally;
- no UDP or SCTP automation.

If Nerva is unavailable or one asset times out, the valid inventory is preserved and the snapshot can still be published with degraded fingerprinting status. If the user deliberately cancels the automatic enrichment step, PythonKni does not publish a snapshot that would falsely imply the configured enrichment completed.

`Disabled` and `Manual only` preserve the historical scheduler behavior and publish the snapshot immediately after successful discovery/persistence.

## Runtime resolution

The engine is resolved in this order:

1. explicit path supplied by the caller (primarily tests/controlled integrations);
2. `PYTHONKNI_NERVA_PATH`;
3. packaged/source path `third_party/nerva/nerva.exe`;
4. an existing `nerva` executable on `PATH`.

If none exists, PythonKni reports the optional engine as unavailable instead of silently downloading software at runtime.

## Windows distribution

Normal source usage may omit the optional engine. Windows CI and future release builds stage the exact locked archive before PyInstaller, package `nerva.exe`, its upstream Apache-2.0 license and `source.json` provenance into the application bundle, then execute the packaged Nerva `--capabilities` smoke before the PythonKni frozen-app and installer lifecycle smokes.

The Windows package supports the Nerva modes available in the upstream Windows binary, including TCP, UDP and explicit misconfiguration checks. SCTP remains unavailable there because the pinned upstream version restricts SCTP to Linux.

Historical `v0.1.0` recovery remains intentionally pre-Nerva: recovery rebuilds the immutable release's original assets and does not inject a newer third-party binary into old tagged source.
