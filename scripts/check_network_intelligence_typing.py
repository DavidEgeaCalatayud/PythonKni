from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path

NETWORK_INTELLIGENCE_DIR = Path("pythonkni/network_intelligence")
STRICT_MODULES = frozenset(
    {
        "automatic_snapshot.py",
        "classification.py",
        "models.py",
        "score.py",
    }
)


@dataclass(frozen=True, slots=True)
class ModuleMetrics:
    tracked_callables: int = 0
    fully_annotated_callables: int = 0
    annotation_slots: int = 0
    annotated_slots: int = 0
    explicit_any: int = 0

    @property
    def coverage_percent(self) -> float:
        if not self.annotation_slots:
            return 100.0
        return self.annotated_slots * 100.0 / self.annotation_slots

    def __add__(self, other: ModuleMetrics) -> ModuleMetrics:
        return ModuleMetrics(
            tracked_callables=self.tracked_callables + other.tracked_callables,
            fully_annotated_callables=(
                self.fully_annotated_callables + other.fully_annotated_callables
            ),
            annotation_slots=self.annotation_slots + other.annotation_slots,
            annotated_slots=self.annotated_slots + other.annotated_slots,
            explicit_any=self.explicit_any + other.explicit_any,
        )


@dataclass(frozen=True, slots=True)
class TypingPolicy:
    minimum_annotation_coverage: float = 0.0
    minimum_tracked_callables: int = 0
    maximum_explicit_any: int = 1_000_000
    strict_modules: frozenset[str] = STRICT_MODULES


@dataclass(frozen=True, slots=True)
class TypingReport:
    package: ModuleMetrics
    modules: dict[str, ModuleMetrics]


def _tracked_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node)
        elif isinstance(node, ast.ClassDef):
            functions.extend(
                item
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
    return functions


def _parameter_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    parameters = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
    parameters = [parameter for parameter in parameters if parameter.arg not in {"self", "cls"}]
    if function.args.vararg is not None:
        parameters.append(function.args.vararg)
    if function.args.kwarg is not None:
        parameters.append(function.args.kwarg)
    return parameters


def _explicit_any_count(annotation: ast.expr | None) -> int:
    if annotation is None:
        return 0
    return sum(
        1
        for node in ast.walk(annotation)
        if (isinstance(node, ast.Name) and node.id == "Any")
        or (isinstance(node, ast.Attribute) and node.attr == "Any")
    )


def analyze_source(source: str, *, filename: str = "<memory>") -> ModuleMetrics:
    tree = ast.parse(source, filename=filename)
    tracked_callables = 0
    fully_annotated_callables = 0
    annotation_slots = 0
    annotated_slots = 0
    explicit_any = 0

    for function in _tracked_functions(tree):
        tracked_callables += 1
        parameters = _parameter_nodes(function)
        annotations = [parameter.annotation for parameter in parameters]
        annotations.append(function.returns)

        annotation_slots += len(annotations)
        annotated_slots += sum(annotation is not None for annotation in annotations)
        explicit_any += sum(_explicit_any_count(annotation) for annotation in annotations)
        if all(annotation is not None for annotation in annotations):
            fully_annotated_callables += 1

    return ModuleMetrics(
        tracked_callables=tracked_callables,
        fully_annotated_callables=fully_annotated_callables,
        annotation_slots=annotation_slots,
        annotated_slots=annotated_slots,
        explicit_any=explicit_any,
    )


def analyze_directory(directory: Path) -> TypingReport:
    modules: dict[str, ModuleMetrics] = {}
    package = ModuleMetrics()
    for path in sorted(directory.glob("*.py")):
        if path.name == "__init__.py":
            continue
        metrics = analyze_source(path.read_text(encoding="utf-8"), filename=str(path))
        modules[path.name] = metrics
        package = package + metrics
    return TypingReport(package=package, modules=modules)


def evaluate_policy(report: TypingReport, policy: TypingPolicy) -> list[str]:
    failures: list[str] = []
    package = report.package
    if package.coverage_percent + 1e-9 < policy.minimum_annotation_coverage:
        failures.append(
            "annotation coverage regressed: "
            f"{package.coverage_percent:.2f}% < {policy.minimum_annotation_coverage:.2f}%"
        )
    if package.tracked_callables < policy.minimum_tracked_callables:
        failures.append(
            "tracked callable count regressed: "
            f"{package.tracked_callables} < {policy.minimum_tracked_callables}"
        )
    if package.explicit_any > policy.maximum_explicit_any:
        failures.append(
            f"explicit Any count increased: {package.explicit_any} > {policy.maximum_explicit_any}"
        )

    for module_name in sorted(policy.strict_modules):
        metrics = report.modules.get(module_name)
        if metrics is None:
            failures.append(f"strict module is missing: {module_name}")
            continue
        if metrics.annotated_slots != metrics.annotation_slots:
            failures.append(
                f"strict module {module_name} is not fully annotated: "
                f"{metrics.annotated_slots}/{metrics.annotation_slots} slots"
            )
        if metrics.explicit_any:
            failures.append(
                f"strict module {module_name} contains {metrics.explicit_any} explicit Any annotation(s)"
            )
    return failures


def report_payload(report: TypingReport) -> dict[str, object]:
    def metrics_payload(metrics: ModuleMetrics) -> dict[str, int | float]:
        return {
            "tracked_callables": metrics.tracked_callables,
            "fully_annotated_callables": metrics.fully_annotated_callables,
            "annotation_slots": metrics.annotation_slots,
            "annotated_slots": metrics.annotated_slots,
            "coverage_percent": round(metrics.coverage_percent, 2),
            "explicit_any": metrics.explicit_any,
        }

    return {
        "package": metrics_payload(report.package),
        "strict_modules": sorted(STRICT_MODULES),
        "modules": {
            module_name: metrics_payload(metrics)
            for module_name, metrics in sorted(report.modules.items())
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure and enforce incremental typing coverage for Network Intelligence."
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Print the current metrics without enforcing the ratchet policy.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    report = analyze_directory(repo_root / NETWORK_INTELLIGENCE_DIR)
    print("NI_TYPING_REPORT=" + json.dumps(report_payload(report), sort_keys=True))

    if args.report_only:
        return 0

    failures = evaluate_policy(report, TypingPolicy())
    if failures:
        for failure in failures:
            print(f"NI typing ratchet failed: {failure}")
        return 1
    print("Network Intelligence typing ratchet passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
