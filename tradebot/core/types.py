from dataclasses import dataclass, field
from typing import Any

@dataclass
class ModuleResult:
    score: float = 0.0
    direction: str = "NEUTRAL"
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
