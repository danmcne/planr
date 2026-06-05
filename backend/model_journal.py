# backend/journal.py
from __future__ import annotations

from datetime import date
from typing import List, Optional
from pydantic import BaseModel, Field


class ContextSummary(BaseModel):
    id:    str
    name:  str
    color: str


class JournalCreate(BaseModel):
    entry_date:  date
    title:       Optional[str] = None    # included in filename when provided
    content:     str = ""
    context_ids: List[str] = Field(default_factory=list)
    tag_names:   List[str] = Field(default_factory=list)


class JournalUpdate(BaseModel):
    title:       Optional[str] = None
    content:     Optional[str] = None
    context_ids: Optional[List[str]] = None
    tag_names:   Optional[List[str]] = None


class JournalResponse(BaseModel):
    id:             str
    entry_date:     date
    title:          Optional[str] = None
    filepath:       str
    content:        str
    created_at:     str
    updated_at:     str
    contexts:       List[ContextSummary] = []
    tags:           List[str] = []
    outgoing_links: List[str] = []
