from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConversionResult:
    """Structured result for converter operations."""

    success: bool
    outputs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()

    @classmethod
    def completed(
        cls,
        outputs: list[str] | tuple[str, ...],
        *,
        warnings: list[str] | tuple[str, ...] = (),
    ) -> "ConversionResult":
        return cls(True, tuple(outputs), tuple(warnings), ())

    @classmethod
    def failed(
        cls,
        *failures: str,
        warnings: list[str] | tuple[str, ...] = (),
    ) -> "ConversionResult":
        return cls(False, (), tuple(warnings), tuple(failures))
