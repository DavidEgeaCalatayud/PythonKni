from __future__ import annotations

import re
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
HASH_RE = re.compile(r"--hash=sha256:([0-9a-f]{64})(?=\s|\\|$)", re.IGNORECASE)
HASH_TOKEN_RE = re.compile(r"--hash=([^\s\\]+)")


def _load_direct_requirements(path: Path) -> list[Requirement]:
    requirements: list[Requirement] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-", "--")):
            raise ValueError(f"{path.name}:{line_number}: no se permiten opciones")
        try:
            requirements.append(Requirement(line))
        except Exception as error:
            raise ValueError(f"{path.name}:{line_number}: requisito inválido: {line}") from error
    return requirements


def _validate_exact_pin(path: Path, requirement: Requirement) -> tuple[str, Version]:
    if requirement.url or requirement.marker or requirement.extras:
        raise ValueError(
            f"{path.name}: {requirement} debe ser un pin reproducible sin URL, marker o extras"
        )
    specifiers = list(requirement.specifier)
    if len(specifiers) != 1 or specifiers[0].operator != "==" or "*" in specifiers[0].version:
        raise ValueError(f"{path.name}: {requirement} no está fijado con una versión exacta ==")
    return canonicalize_name(requirement.name), Version(specifiers[0].version)


def _locked_versions(path: Path) -> tuple[dict[str, Version], int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    locked: dict[str, Version] = {}
    hash_count = 0
    index = 0

    while index < len(lines):
        raw_line = lines[index]
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        if raw_line[:1].isspace():
            raise ValueError(f"{path.name}:{index + 1}: continuación huérfana en el lock")
        if stripped.startswith(("-", "--")):
            raise ValueError(f"{path.name}:{index + 1}: no se permiten opciones globales en el lock")

        start_line = index + 1
        block = [raw_line]
        index += 1
        while index < len(lines):
            candidate = lines[index]
            candidate_stripped = candidate.strip()
            if candidate_stripped and not candidate[:1].isspace() and not candidate_stripped.startswith("#"):
                break
            block.append(candidate)
            index += 1

        first_line = stripped.removesuffix("\\").strip()
        requirement_text = first_line.split(" --hash=", maxsplit=1)[0].strip()
        try:
            requirement = Requirement(requirement_text)
        except Exception as error:
            raise ValueError(
                f"{path.name}:{start_line}: requisito inválido: {requirement_text}"
            ) from error

        name, version = _validate_exact_pin(path, requirement)
        if name in locked:
            raise ValueError(f"{path.name}:{start_line}: dependencia duplicada: {requirement.name}")

        block_text = "\n".join(block)
        hash_tokens = HASH_TOKEN_RE.findall(block_text)
        valid_hashes = HASH_RE.findall(block_text)
        if len(hash_tokens) != len(valid_hashes):
            raise ValueError(
                f"{path.name}:{start_line}: {requirement.name} contiene un hash no SHA-256 o malformado"
            )
        if not valid_hashes:
            raise ValueError(
                f"{path.name}:{start_line}: {requirement.name} no tiene ningún hash SHA-256"
            )

        locked[name] = version
        hash_count += len(valid_hashes)

    if not locked:
        raise ValueError(f"{path.name}: el lock está vacío")
    return locked, hash_count


def _validate_direct_requirements(
    input_path: Path, lock_path: Path
) -> tuple[dict[str, Version], int]:
    locked, hash_count = _locked_versions(lock_path)
    for requirement in _load_direct_requirements(input_path):
        name = canonicalize_name(requirement.name)
        version = locked.get(name)
        if version is None:
            raise ValueError(f"{lock_path.name}: falta la dependencia directa {requirement.name}")
        if requirement.specifier and version not in requirement.specifier:
            raise ValueError(
                f"{lock_path.name}: {requirement.name}=={version} no satisface {requirement.specifier}"
            )
    return locked, hash_count


def main() -> int:
    try:
        runtime, runtime_hashes = _validate_direct_requirements(
            ROOT / "requirements.in", ROOT / "requirements.txt"
        )
        development, development_hashes = _validate_direct_requirements(
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
        "Dependency locks are structurally valid and SHA-256 hashed: "
        f"{len(runtime)} runtime pins/{runtime_hashes} hashes, "
        f"{len(development)} development pins/{development_hashes} hashes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
