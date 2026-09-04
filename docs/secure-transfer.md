# Secure Transfer

Secure Transfer adds an AirDrop-style peer-to-peer workflow to PythonKni using a pinned Tailcat transport. PythonKni does not implement or decode Tailcat's wire format; all Tailcat-specific command construction and output parsing are isolated in `pythonkni.secure_transfer.tailcat_backend`.

## Transport

The packaged Windows build pins **Tailcat v0.5.0**. Tailcat uses Tailscale's userspace data plane: WireGuard encryption between peers, DERP for bootstrap/fallback, and NAT traversal to upgrade to a direct UDP path when possible. It does not require a Tailscale account and does not modify the host routing table or DNS configuration.

Tailcat explicitly does **not** guarantee API, CLI or wire-format stability. PythonKni therefore treats the Tailcat executable as a replaceable transport backend and verifies the exact supported version before starting a session.

## Workflows

### Files

- **Receive file** starts a Tailcat write-only drop box in a user-selected directory.
- **Receive folder** is a separate opt-in because upstream documents a larger metadata surface when directory trees are accepted.
- **Send file/folder** validates the supplied Tailcat address with `tailcat parse`, then uses `tailcat cp`.

Tailcat v0.5.0 implements `cp` by invoking the system `scp`. On Windows, sending files or directories therefore requires the optional **OpenSSH Client** feature (`scp.exe`) to be available on `PATH`. Receiving files, transferring text, and tunnel/forward workflows do not depend on `scp.exe`.

### Text

Text uses Tailcat's generic encrypted stdin/stdout pipe. PythonKni caps a text message at 1 MiB to keep the GUI workflow bounded.

### Secure tunnel

A local TCP service can be exposed through a Tailcat address by serving one explicit port. PythonKni does not expose Tailcat exit-node or auth-free SSH modes.

### Port forwarding

A peer's explicitly served TCP port can be forwarded to an explicit local port. PythonKni always constructs the forward with `--bind=127.0.0.1`; there is intentionally no UI path to bind `0.0.0.0`.

## Session identity and tokens

Every server/client command created by PythonKni includes `--key=new`. This prevents an existing saved Tailcat `default` or `client-default` key from being silently reused and keeps PythonKni sessions ephemeral by default.

Connection addresses are treated as untrusted input. Before a client transfer or forward, the pinned Tailcat runtime must accept the address through `tailcat parse`. PythonKni never parses Tailcat's CBOR address payload itself.

## Security boundaries

Secure Transfer intentionally does not expose:

- exit-node routing;
- auth-free SSH;
- read-write file shares;
- saved/stable Tailcat keys;
- arbitrary `0.0.0.0` forwarding binds;
- automatic LAN/range discovery.

Tailcat's core transport is built from WireGuard, magicsock and DERP, but the Tailcat wrapper is still described upstream as experimental for mutually untrusted parties. Use connection tokens only with the intended peer and stop the session when the transfer/tunnel is no longer needed.

## Runtime packaging

`third_party/tailcat.lock.json` pins the official Windows amd64 release archive and its SHA-256 digest. `scripts/fetch_tailcat.ps1` downloads only the official Tailscale GitHub Release, verifies the digest, extracts `tailcat.exe` and the upstream license, and writes source metadata. The executable itself is not committed to PythonKni.
