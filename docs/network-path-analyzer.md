# Network Path Analyzer

`Network Path Analyzer` adds continuous, hop-by-hop path diagnostics to PythonKni. It complements the existing network domains instead of duplicating them:

```text
Network Explorer        -> what hosts/services exist?
Network Intelligence    -> what do we know about them over time?
Network Traffic Monitor -> what connections are happening now?
Network Path Analyzer   -> where does latency/path degradation begin?
```

The first-party UI and temporal analysis belong to PythonKni. Probe execution is delegated through a deliberately narrow adapter to the pinned Trippy CLI; PythonKni does not embed Trippy's TUI or import its application architecture.

## Runtime architecture

```text
explicit target + protocol/options
              |
              v
pythonkni/network_path/service.py
  validation / bounded configuration
              |
              v
pythonkni/network_path/backend.py
  pinned Trippy 0.13.0 JSON contract
              |
              v
TraceSnapshot (one observation round)
              |
              v
pythonkni/network_path/intelligence.py
  stable route + rolling hop/destination statistics
              |
      +-------+--------+
      |                |
      v                v
bounded history     PathEvent
JSONL                 |
                      v
             Change Notification inbox
                      |
                      v
                History Center
```

Qt never owns raw-socket/subprocess logic. Continuous execution uses the shared managed-worker lifecycle and cooperative cancellation contract.

## Trippy supply chain

PythonKni currently supports exactly **Trippy 0.13.0** for the Windows x86_64 MSVC runtime.

- `third_party/trippy.lock.json` pins the exact official GitHub Release archive and SHA-256.
- `scripts/fetch_trippy.ps1` downloads only the official `fujiapple852/trippy` release path during build/release staging.
- The archive digest is checked before extraction.
- `trip.exe` and the upstream license are required before staging succeeds.
- `source.json` records both the verified archive digest and the extracted executable digest.
- An already-staged executable is reused only after its digest and CLI contract are revalidated.
- `scripts/check_trippy_contract.ps1` verifies version `0.13.0` plus the reporting/protocol options consumed by PythonKni.
- PyInstaller packages the verified runtime. PythonKni does **not** download Trippy while the application is running.

Trippy remains licensed under Apache-2.0; see `third_party/NOTICE.md` and the upstream license bundled with the staged component.

## Windows privileges

Trippy's Windows tracing implementation requires Administrator privileges for the raw sockets used by its traceroute protocols. Network Path Analyzer detects this condition and reports it explicitly rather than silently falling back to a different measurement model.

Opening PythonKni normally remains valid for the rest of the application. Elevation is required only when the user chooses to run this path analyzer on Windows.

## Targets and protocols

The tool accepts exactly one explicit hostname or IP. CIDRs, address ranges, lists and URLs are rejected.

Supported protocol choices are:

| Protocol | Default target port | Notes |
| --- | ---: | --- |
| ICMP | n/a | Standard ICMP echo/time-exceeded path tracing. |
| UDP | 33434 | Uses Trippy's Dublin multipath strategy to make UDP tracing more stable across NAT/ECMP where possible. |
| TCP | 443 | Useful where ICMP/UDP probing is treated differently; the port can be overridden. |

Address-family selection is `Auto`, `IPv4` or `IPv6`. DNS resolution is forced through Trippy's **system resolver**. PythonKni does not enable Trippy's external ASN lookup in this module.

Probe intervals are bounded to 0.5–30 seconds and max TTL to 1–64. These limits prevent the GUI from becoming an unrestricted high-rate probing interface.

## Per-hop statistics

Each round is normalized to a framework-independent `TraceSnapshot`. Across rounds, PythonKni maintains bounded per-hop statistics:

- responding IP/hostname(s), including multipath observations;
- sent and received observations;
- loss percentage for that observed hop response stream;
- last RTT;
- average RTT;
- minimum RTT;
- maximum RTT;
- successive-sample jitter.

The destination RTT is also retained as a bounded timeline for the chart and local history.

### Important interpretation rule

A router can forward traffic normally while rate-limiting or completely ignoring TTL-expired/ICMP diagnostic traffic. Therefore:

> **No reply from an intermediate hop is not treated as proof of packet loss through that hop.**

The `Loss` column describes the response behavior observed for that hop. The `packet_loss` temporal event, by contrast, is based on **destination reachability across observation rounds**, not on an intermediate router failing to reply.

This distinction avoids one of the most common traceroute/MTR interpretation errors.

## Route-change detection

A first complete/reached route establishes the baseline without emitting a change.

A later route must be observed consistently for multiple rounds before PythonKni promotes it to the confirmed route. A temporarily silent intermediate hop inherits the previously confirmed identity for comparison while the destination remains reachable, preventing a single missing TTL-expired response from generating `hop_removed`.

Once confirmed, PythonKni can emit:

- `route_changed`
- `hop_added`
- `hop_removed`

The event records the target and, when applicable, the implicated TTL/IP. ECMP may legitimately produce multiple addresses at one TTL; host identity is therefore represented as a set rather than assuming exactly one router per hop.

## Latency diagnostics

Destination latency uses a bounded rolling history. `latency_spike` requires both:

1. a meaningful multiplicative increase from the recent median; and
2. a meaningful absolute RTT increase.

This avoids classifying ordinary sub-millisecond/small fluctuations as incidents.

For explainability, the analyzer also looks for the first **persistent RTT step** between responding hops. If a plausible step is visible, the event/status identifies that TTL as the first point where accumulated latency becomes materially larger. This is diagnostic evidence, not proof that the router at that TTL itself is faulty: return-path asymmetry, ICMP scheduling and downstream congestion can affect hop RTTs.

## Destination loss and unreachability

`destination_unreachable` requires repeated consecutive rounds without a destination response. A single missed round does not trigger it.

`packet_loss` is generated only after a minimum observation count and only from destination-level observations. Severity increases for substantial sustained loss. Recovery hysteresis is used so the event state does not flap around the threshold.

A destination that does not answer a chosen trace protocol may still be otherwise reachable. Event wording therefore preserves alternatives such as filtering or probe-response policy rather than claiming an outage as fact.

## Temporal integration

Discrete path events use the same canonical Change Notification inbox as Network Intelligence and Network Traffic Monitor:

```text
PathEvent
   |
   v
network_intelligence_notifications.json
   +--> Change Notification Engine
   +--> History Center / Telemetría temporal
```

The source is recorded as `Network Path Analyzer` and the scope as `network-path`. Replay of the exact same observation is deduplicated; a later occurrence receives a distinct temporal occurrence ID.

Periodic samples remain in bounded `data/network_path/history.jsonl`. The domain's `events.jsonl` is only a recovery fallback if canonical notification persistence fails.

Path observations do not create synthetic Network Intelligence assets and do not silently modify classification, security score or persisted risk.

## UI

The initial window provides:

- explicit Target;
- ICMP / UDP / TCP selector;
- Auto / IPv4 / IPv6 selector;
- bounded interval;
- optional UDP/TCP port;
- bounded max TTL;
- Start / Stop / Reset stats;
- Path table;
- destination RTT timeline;
- History tab;
- Alerts tab.

The UI remains responsive because all Trippy execution and analysis work runs through a managed worker.

## Safety and non-goals

Network Path Analyzer is a diagnostics feature, not a reconnaissance scanner:

- one explicit target only;
- no CIDR/range expansion;
- no port scanning;
- no credential/default-password attempts;
- no exploitation;
- no payload capture or decryption;
- no internet-wide discovery;
- no arbitrary user-supplied Trippy arguments;
- bounded TTL and probe cadence;
- cooperative cancellation.

Use active network diagnostics only against systems/networks you own or are authorized to test.
