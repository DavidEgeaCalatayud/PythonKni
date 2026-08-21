from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class StartupItem:
    active: bool
    name: str
    source: str
    command: str
    item_type: str
    exists: str
    risk: str
    origin_kind: str
    root_name: str = ""
    key_path: str = ""
    value_name: str = ""
    value_type: int = 0
    file_path: str = ""
    backup_path: str = ""
    metadata_path: str = ""
    disabled_id: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
