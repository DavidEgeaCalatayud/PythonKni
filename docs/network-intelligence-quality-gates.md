# Network Intelligence quality gates

Network Intelligence uses an incremental structural typing ratchet so type-annotation quality can improve without requiring a one-shot rewrite of the entire subsystem.

The gate is implemented by `scripts/check_network_intelligence_typing.py` and runs in both normal CI and the tag-driven Release workflow.

## What the gate measures

The analyzer parses the Python AST for every `pythonkni/network_intelligence/*.py` module except `__init__.py` and tracks:

- module-level functions;
- methods directly declared on classes;
- all positional, positional-only, keyword-only, `*args` and `**kwargs` parameters except `self` and `cls`;
- return annotations;
- whether each tracked callable is fully annotated;
- explicit `Any` references in tracked annotations.

Nested local functions are intentionally excluded. They are implementation details rather than the module/class API surface protected by this ratchet.

Each tracked parameter or return position is one annotation slot.

## Enforced baseline

After the first incremental cleanup in #64, the package policy is:

```text
tracked callables                         >= 303
fully annotated callables                 >= 263
annotated slots                           >= 668
annotation-slot coverage                  >= 92.64%
explicit Any annotations                  <= 39
```

The absolute slot/callable floors and the percentage floor are complementary. Removing typed APIs cannot improve the score, and adding a meaningful amount of untyped API surface cannot silently dilute the package while keeping the absolute totals unchanged.

The `Any` ceiling is a debt ratchet: existing explicit dynamic annotations in legacy parsing/reporting paths remain visible, but new `Any` usage cannot increase the total without an explicit policy change.

## Strict modules

Modules that are already fully annotated and contain no explicit `Any` are placed in the strict set. They must remain at 100% structural annotation coverage and zero explicit `Any`:

```text
auditors.py
automatic_snapshot.py
classification.py
history.py
identity.py
models.py
oui.py
physical_import.py
relationships.py
reporting_window.py
retention.py
risk_window.py
scheduler.py
score.py
topology.py
```

#64 also completed the missing annotations in `auditors.py`, `relationships.py` and `topology.py` before promoting them into this strict set.

## Commands

Enforce the policy exactly as CI/Release do:

```powershell
python -m scripts.check_network_intelligence_typing
```

Inspect the current metrics without failing on the policy:

```powershell
python -m scripts.check_network_intelligence_typing --report-only
```

`--report-only` is for local diagnosis and future ratchet planning. CI and Release use the enforcing form.

## Incremental improvement process

When a module is improved:

1. annotate the real API/callback contract rather than using `Any` as a shortcut;
2. run the analyzer and the relevant tests;
3. raise the absolute/percentage floors when the package baseline improves;
4. lower the explicit-`Any` ceiling when dynamic annotations are removed;
5. add a module to the strict set once it reaches 100% and zero explicit `Any`;
6. never lower a ratchet merely to make an unrelated change pass.

This makes typing debt monotonic: future work may improve it or preserve it, but cannot silently regress it.

## What this is not

This gate checks annotation presence and explicit `Any` usage structurally. It does **not** perform semantic type inference, protocol compatibility checking or cross-module type analysis, and it must not be described as a replacement for `mypy`, `pyright` or another static type checker.

A future semantic checker can be introduced on top of this baseline once its dependency/stub policy is validated against the Windows + CPython 3.13.15 build. The structural ratchet remains useful even then because it independently prevents annotation coverage from drifting backwards.
