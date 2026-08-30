from __future__ import annotations

import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


ROOT = Path(__file__).resolve().parents[1]


def _load_requirements(path: Path) -> list[Requirement]:
    requirements: list[Requirement] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-", "--")):
            raise ValueError(f"{path.name}:{line_number}: no se permiten opciones en este lock")
        try:
            requirements.append(Requirement(line))
        except Exception as error:
            raise ValueError(f"{path.name}:{line_number}: requisito inválido: {line}") from error
    return requirements


def _locked_versions(path: Path) -> dict[str, Version]:
    locked: dict[str, Version] = {}
    for requirement in _load_requirements(path):
        if requirement.url or requirement.marker or requirement.extras:
            raise ValueError(
                f"{path.name}: {requirement} debe ser un pin simple y reproducible sin URL, marker o extras"
            )
        specifiers = list(requirement.specifier)
        if len(specifiers) != 1 or specifiers[0].operator != "==" or "*" in specifiers[0].version:
            raise ValueError(f"{path.name}: {requirement} no está fijado con una versión exacta ==")
        name = canonicalize_name(requirement.name)
        if name in locked:
            raise ValueError(f"{path.name}: dependencia duplicada: {requirement.name}")
        locked[name] = Version(specifiers[0].version)
    return locked


def _validate_direct_requirements(input_path: Path, lock_path: Path) -> dict[str, Version]:
    locked = _locked_versions(lock_path)
    for requirement in _load_requirements(input_path):
        name = canonicalize_name(requirement.name)
        version = locked.get(name)
        if version is None:
            raise ValueError(f"{lock_path.name}: falta la dependencia directa {requirement.name}")
        if requirement.specifier and version not in requirement.specifier:
            raise ValueError(
                f"{lock_path.name}: {requirement.name}=={version} no satisface {requirement.specifier}"
            )
    return locked


def main() -> int:
    try:
        runtime = _validate_direct_requirements(ROOT / "requirements.in", ROOT / "requirements.txt")
        development = _validate_direct_requirements(
            ROOT / "requirements-dev.in", ROOT / "requirements-dev.txt"
        )

        conflicts = []
        for name in sorted(runtime.keys() & development.keys()):
            if runtime[name] != development[name]:
                conflicts.append(f"{name}: runtime={runtime[name]} dev={development[name]}")
        if conflicts:
            raise ValueError("Pins incompatibles entre locks: " + "; ".join(conflicts))
    except (OSError, ValueError) as error:
        print(f"Dependency lock validation failed: {error}", file=sys.stderr)
        return 1

    print(
        "Dependency locks are structurally valid: "
        f"{len(runtime)} runtime pins, {len(development)} development pins."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
