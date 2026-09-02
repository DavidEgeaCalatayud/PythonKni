# Network service fingerprinting

PythonKni's port scanner intentionally answers a narrow question first: **which TCP ports are open?** Service fingerprinting is a separate, explicit enrichment step that can identify the application-layer protocol actually responding on those known-open ports.

## Engine and trust model

The optional engine is [Praetorian Nerva](https://github.com/praetorian-inc/nerva), licensed under Apache-2.0. PythonKni does not install `latest` and does not execute an unverified download.

`third_party/nerva.lock.json` pins one exact Windows amd64 release archive and SHA-256 digest. `scripts/fetch_nerva.ps1` downloads only that URL, verifies SHA-256 **before extraction**, stages `nerva.exe` under the ignored `third_party/nerva/` runtime directory, and records source metadata beside the executable.

The initial pin is:

```text
Nerva v1.69.4
nerva_1.69.4_windows_amd64.zip
SHA-256 59e59eb54c8c5c581031387a0aa23c98983db94301e811f3c9b1802a05fc97f7
```

Updating Nerva is therefore an explicit repository change: update the lock metadata, review the upstream release, run tests/CI, and merge the new pin normally.

## Safety boundary

The first milestone is **service identification only**:

- input is a target plus ports already known to be open;
- TCP only;
- bounded Nerva worker count, per-probe timeout and per-host connection limit;
- cooperative cancellation terminates the child process;
- Nerva `--misconfigs` is deliberately not enabled;
- UDP/SCTP modes are deliberately not enabled;
- no credentials, password guessing or exploitation are performed.

Use network capabilities only on systems and networks you own or are explicitly authorized to administer.

## Domain contract

Nerva's JSON is normalized immediately into PythonKni's `ServiceFingerprint` model:

```text
ServiceFingerprint
├─ host
├─ ip
├─ port
├─ protocol
├─ transport
├─ product
├─ version
└─ metadata
```

Presentation and Network Intelligence code should consume that model instead of depending directly on Nerva's raw JSON schema. Unknown useful upstream fields are preserved in `metadata` so protocol-specific evidence is not discarded.

## Runtime resolution

The engine is resolved in this order:

1. explicit path supplied by the caller (primarily tests/controlled integrations);
2. `PYTHONKNI_NERVA_PATH`;
3. packaged/source path `third_party/nerva/nerva.exe`;
4. an existing `nerva` executable on `PATH`.

If none exists, PythonKni reports the optional engine as unavailable instead of silently downloading software at runtime.
