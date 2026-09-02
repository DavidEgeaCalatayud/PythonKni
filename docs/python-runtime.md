# Python runtime contract

PythonKni's canonical interpreter is **CPython 3.13.15** on Windows. The supported source/runtime contract is the **Python 3.13 series** (`>=3.13,<3.14`).

## Why 3.13

The migration deliberately moves the project from CPython 3.10.11 to the maintained 3.13 line without combining that change with an immediate jump to Python 3.14. This keeps the runtime upgrade independently reviewable while preserving the existing PyQt5/PyInstaller application stack.

The canonical build uses the normal CPython build with the GIL. PythonKni does not currently claim support for the optional/free-threaded interpreter build.

## What is pinned

The exact runtime is pinned consistently in:

- `.github/workflows/ci.yml`;
- `.github/workflows/release.yml`;
- `.github/workflows/oui-registry-maintenance.yml`.

`pyproject.toml` declares `requires-python = ">=3.13,<3.14"` and Ruff targets `py313`.

`tests/test_python_runtime_contract.py` protects those declarations from drifting apart.

## Dependency compatibility

The migration does not widen or silently replace the dependency graph. The existing SHA-256-locked runtime and development graphs are required to install unchanged under CPython 3.13.15 and still pass:

```text
pip --require-hashes
pip check
runtime pip-audit
development pip-audit
CycloneDX SBOM generation
```

A dependency change remains a separate reviewed operation: modify the corresponding `.in` policy, regenerate the lock on Windows / CPython 3.13.15, inspect the diff and pass the complete CI pipeline.

## Validation contract

A runtime migration is accepted only when the canonical Windows pipeline completes all of the existing gates under CPython 3.13.15:

```text
hash-locked install
→ dependency validation and audits
→ compileall
→ bundled OUI validation
→ pytest + branch coverage ratchets
→ Network Intelligence benchmark smoke
→ Ruff lint + format
→ PyInstaller Windows build
→ frozen PythonKni.exe --smoke-test
→ ZIP/checksum/artifact publication
```

Passing source tests alone is not sufficient because PythonKni is distributed as a frozen Windows desktop application.

## Future Python versions

Python 3.14 and later are intentionally not claimed by `requires-python` until the same dependency, test, PyInstaller and frozen-smoke validation has been performed on that series. This avoids implying compatibility merely because the source happens to import on a newer interpreter.
