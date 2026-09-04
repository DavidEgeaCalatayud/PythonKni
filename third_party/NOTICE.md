# Third-party runtime components

## Nerva

PythonKni can optionally bundle **Nerva**, Copyright Praetorian Security, Inc., licensed under the Apache License 2.0.

The Nerva executable is **not committed to this repository**. Build and release automation obtains only the exact Windows amd64 archive pinned in `nerva.lock.json`, verifies its SHA-256 digest before extraction, and then packages the verified executable when the integration is enabled.

Upstream project: https://github.com/praetorian-inc/nerva

The upstream license and notices remain applicable to the bundled Nerva component.

## Tailcat

PythonKni can bundle **Tailcat**, Copyright Tailscale Inc. & contributors, licensed under the BSD 3-Clause License.

The Tailcat executable is **not committed to this repository**. Build and release automation obtains only the official Windows amd64 archive pinned in `tailcat.lock.json`, verifies its SHA-256 digest before extraction, and packages the exact supported runtime together with its upstream license/source metadata.

Upstream project: https://github.com/tailscale/tailcat

Secure Transfer currently pins Tailcat v0.5.0 because upstream does not guarantee API, CLI or wire-format stability. PythonKni's adapter and safety restrictions are project-specific and do not modify Tailcat's upstream license or security model.

PythonKni itself remains licensed under its repository `LICENSE`.
