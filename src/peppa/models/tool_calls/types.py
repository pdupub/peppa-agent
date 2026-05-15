from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    id: str | None
    name: str
    arguments_raw: Any
    arguments: dict[str, Any] | None
    parse_error: str | None = None
