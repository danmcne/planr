from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# Tailwind color names recognised throughout the app.
# The frontend maps these to bg-{color}-100 / text-{color}-800 etc.
TAILWIND_COLORS = frozenset([
    "slate", "gray", "zinc", "neutral", "stone",
    "red", "orange", "amber", "yellow", "lime",
    "green", "emerald", "teal", "cyan", "sky",
    "blue", "indigo", "violet", "purple", "fuchsia",
    "pink", "rose",
])

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _validate_color(v: str) -> str:
    if _HEX_RE.match(v) or v in TAILWIND_COLORS:
        return v
    allowed = ", ".join(sorted(TAILWIND_COLORS))
    raise ValueError(
        f"color must be a 6-digit hex (#rrggbb) or a Tailwind name ({allowed})"
    )


class ContextCreate(BaseModel):
    name:      str = Field(min_length=1, max_length=100)
    parent_id: Optional[str] = None
    color:     str = Field(default="slate")

    @field_validator("color")
    @classmethod
    def check_color(cls, v: str) -> str:
        return _validate_color(v)


class ContextUpdate(BaseModel):
    name:      Optional[str] = Field(None, min_length=1, max_length=100)
    parent_id: Optional[str] = None
    color:     Optional[str] = None

    @field_validator("color")
    @classmethod
    def check_color(cls, v: Optional[str]) -> Optional[str]:
        return _validate_color(v) if v is not None else None


class ContextResponse(BaseModel):
    id:               str
    name:             str
    parent_id:        Optional[str] = None
    color:            str
    is_system:        bool
    subcontext_count: int = 0
    default_for:      Optional[str] = None   # 'tasks' | 'notes' | None
