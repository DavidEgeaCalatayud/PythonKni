from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


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


class OutputTransaction:
    """Stage one or more outputs and publish them atomically as a logical batch.

    Staging and backups live in the destination directory so ``os.replace`` stays
    on the same filesystem. Existing outputs are only moved aside during commit;
    if any publish step fails, every previously published output is rolled back.
    """

    def __init__(self, destination_dir: str | Path):
        self.destination_dir = Path(destination_dir)
        self.destination_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir = Path(
            tempfile.mkdtemp(prefix=".pythonkni-converter-", dir=self.destination_dir)
        )
        self._entries: list[tuple[Path, Path]] = []
        self._committed = False

    def stage_for(self, final_path: str | Path) -> Path:
        final = Path(final_path)
        if final.parent.resolve(strict=False) != self.destination_dir.resolve(strict=False):
            raise ValueError("Todos los destinos de una transacción deben compartir carpeta.")
        index = len(self._entries)
        stage = self.staging_dir / f"{index:04d}_{final.stem}.stage{final.suffix}"
        self._entries.append((stage, final))
        return stage

    def commit(self) -> list[str]:
        states: list[tuple[Path, Path | None]] = []
        try:
            for index, (stage, final) in enumerate(self._entries):
                if not stage.exists():
                    raise FileNotFoundError(f"No existe el resultado temporal: {stage}")

                backup = None
                if final.exists():
                    backup = self.staging_dir / f"{index:04d}_{final.name}.backup"
                    os.replace(final, backup)
                states.append((final, backup))
                os.replace(stage, final)
        except Exception:
            for final, backup in reversed(states):
                try:
                    if final.exists():
                        final.unlink()
                    if backup is not None and backup.exists():
                        os.replace(backup, final)
                except OSError:
                    pass
            raise

        self._committed = True
        outputs = [str(final) for _, final in self._entries]
        self._cleanup()
        return outputs

    def _cleanup(self) -> None:
        shutil.rmtree(self.staging_dir, ignore_errors=True)

    def abort(self) -> None:
        if not self._committed:
            self._cleanup()

    def __enter__(self) -> "OutputTransaction":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if not self._committed:
            self.abort()
