# backend/note.py
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class ContextSummary(BaseModel):
    id:    str
    name:  str
    color: str


class NoteCreate(BaseModel):
    title:       str = Field(min_length=1, max_length=500)
    content:     str = ""
    context_ids: List[str] = Field(default_factory=list)
    tag_names:   List[str] = Field(default_factory=list)


class NoteUpdate(BaseModel):
    title:       Optional[str] = Field(None, min_length=1, max_length=500)
    content:     Optional[str] = None
    context_ids: Optional[List[str]] = None
    tag_names:   Optional[List[str]] = None


class NoteResponse(BaseModel):
    id:             str
    title:          str
    filepath:       str
    content:        str
    created_at:     str
    updated_at:     str
    contexts:       List[ContextSummary] = []
    tags:           List[str] = []
    outgoing_links: List[str] = []   # [[Title]] targets found in body
