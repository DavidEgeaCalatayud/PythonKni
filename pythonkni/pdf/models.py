from __future__ import annotations

"""Framework-independent value objects for the PDF domain.

The current PDF service operates primarily on paths and page indices, so no
custom value object is required yet. Keeping this module explicit preserves the
same models -> service -> window -> adapter boundary used by every domain.
"""

__all__: list[str] = []
