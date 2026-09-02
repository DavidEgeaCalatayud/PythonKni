from __future__ import annotations

from pathlib import Path

from scripts.check_network_intelligence_typing import (
    ModuleMetrics,
    TypingPolicy,
    TypingReport,
    analyze_directory,
    analyze_source,
    evaluate_policy,
)


def test_analyze_source_tracks_methods_parameters_and_returns_without_self():
    metrics = analyze_source(
        """
class Example:
    def run(self, value: int, *, enabled: bool) -> str:
        return str(value) if enabled else ""
"""
    )

    assert metrics.tracked_callables == 1
    assert metrics.fully_annotated_callables == 1
    assert metrics.annotation_slots == 3
    assert metrics.annotated_slots == 3
    assert metrics.coverage_percent == 100.0


def test_analyze_source_counts_missing_annotations_varargs_and_kwargs():
    metrics = analyze_source(
        """
def incomplete(value, *items: str, flag=False, **options) -> None:
    return None
"""
    )

    assert metrics.tracked_callables == 1
    assert metrics.fully_annotated_callables == 0
    assert metrics.annotation_slots == 5
    assert metrics.annotated_slots == 2
    assert metrics.coverage_percent == 40.0


def test_analyze_source_detects_bare_and_qualified_explicit_any():
    metrics = analyze_source(
        """
from typing import Any
import typing

def dynamic(value: Any, other: list[typing.Any]) -> Any:
    return value
"""
    )

    assert metrics.explicit_any == 3


def test_analyze_source_ignores_nested_local_functions():
    metrics = analyze_source(
        """
def outer(value: int) -> int:
    def local(untyped):
        return untyped
    return local(value)
"""
    )

    assert metrics.tracked_callables == 1
    assert metrics.fully_annotated_callables == 1


def test_analyze_directory_aggregates_python_modules_and_skips_package_init(tmp_path: Path):
    (tmp_path / "__init__.py").write_text("def ignored(value): return value\n", encoding="utf-8")
    (tmp_path / "one.py").write_text("def one(value: int) -> int: return value\n", encoding="utf-8")
    (tmp_path / "two.py").write_text("def two(value) -> None: return None\n", encoding="utf-8")

    report = analyze_directory(tmp_path)

    assert set(report.modules) == {"one.py", "two.py"}
    assert report.package.tracked_callables == 2
    assert report.package.fully_annotated_callables == 1
    assert report.package.annotation_slots == 4
    assert report.package.annotated_slots == 3


def test_policy_reports_global_ratchet_regressions():
    report = TypingReport(
        package=ModuleMetrics(
            tracked_callables=9,
            fully_annotated_callables=4,
            annotation_slots=20,
            annotated_slots=15,
            explicit_any=2,
        ),
        modules={},
    )
    policy = TypingPolicy(
        minimum_annotation_coverage=80.0,
        minimum_tracked_callables=10,
        maximum_explicit_any=1,
        strict_modules=frozenset(),
    )

    failures = evaluate_policy(report, policy)

    assert any("annotation coverage regressed" in failure for failure in failures)
    assert any("tracked callable count regressed" in failure for failure in failures)
    assert any("explicit Any count increased" in failure for failure in failures)


def test_policy_requires_strict_modules_to_exist_be_complete_and_avoid_any():
    report = TypingReport(
        package=ModuleMetrics(),
        modules={
            "partial.py": ModuleMetrics(
                tracked_callables=1,
                annotation_slots=2,
                annotated_slots=1,
                explicit_any=1,
            )
        },
    )
    policy = TypingPolicy(strict_modules=frozenset({"partial.py", "missing.py"}))

    failures = evaluate_policy(report, policy)

    assert "strict module is missing: missing.py" in failures
    assert any("partial.py is not fully annotated" in failure for failure in failures)
    assert any("partial.py contains 1 explicit Any" in failure for failure in failures)
