"""
models.py — Pydantic models for planr API
"""
from typing import Optional
from pydantic import BaseModel


# ── Tasks ────────────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str
    description: str = ""
    context_id: Optional[int] = None
    status: str = "inbox"
    importance: str = "normal"
    effort: str = "medium"
    user_urgency: float = 0.0
    due_at: Optional[str] = None
    scheduled_at: Optional[str] = None
    recurrence: str = ""
    recurrence_type: str = "fixed"
    parent_uuid: Optional[str] = None
    location: str = ""


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    context_id: Optional[int] = None
    status: Optional[str] = None
    importance: Optional[str] = None
    effort: Optional[str] = None
    user_urgency: Optional[float] = None
    due_at: Optional[str] = None
    scheduled_at: Optional[str] = None
    recurrence: Optional[str] = None
    recurrence_type: Optional[str] = None
    location: Optional[str] = None
    deferred_until: Optional[str] = None


# ── Events ───────────────────────────────────────────────────────────────────

class EventCreate(BaseModel):
    title: str
    description: str = ""
    context_id: Optional[int] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    all_day: bool = False
    recurrence: str = ""
    location: str = ""


class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    context_id: Optional[int] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    all_day: Optional[bool] = None
    recurrence: Optional[str] = None
    location: Optional[str] = None


# ── Notes ────────────────────────────────────────────────────────────────────

class NoteCreate(BaseModel):
    title: str
    content: str = ""
    context_id: Optional[int] = None


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    context_id: Optional[int] = None


# ── Journal ──────────────────────────────────────────────────────────────────

class JournalCreate(BaseModel):
    title: str = ""
    content: str = ""
    context_id: Optional[int] = None
    entry_date: Optional[str] = None   # YYYY-MM-DD; defaults to today


class JournalUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    context_id: Optional[int] = None


# ── Contexts ─────────────────────────────────────────────────────────────────

class ContextCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None
    color: str = "#6B7280"
    sort_order: int = 0


class ContextUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


# ── Links ────────────────────────────────────────────────────────────────────

class LinkCreate(BaseModel):
    source_uuid: str
    source_type: str
    target_uuid: Optional[str] = None
    target_type: str = "internal"
    target_ref: Optional[str] = None
    link_type: str = "related_to"
    display_text: Optional[str] = None


# ── Misc ─────────────────────────────────────────────────────────────────────

class QuickCapture(BaseModel):
    text: str


class SavedSearchCreate(BaseModel):
    name: str
    query_json: str

class OpenPath(BaseModel):
    path: str
