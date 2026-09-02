# Third-party runtime components

PythonKni can optionally bundle **Nerva**, Copyright Praetorian Security, Inc., licensed under the Apache License 2.0.

The Nerva executable is **not committed to this repository**. Build and release automation obtains only the exact Windows amd64 archive pinned in `nerva.lock.json`, verifies its SHA-256 digest before extraction, and then packages the verified executable when the integration is enabled.

Upstream project: https://github.com/praetorian-inc/nerva

The upstream license and notices remain applicable to the bundled Nerva component. PythonKni itself remains licensed under its repository `LICENSE`.
