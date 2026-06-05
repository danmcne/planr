# backend/links.py
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel


class LinkedObject(BaseModel):
    id:    str
    title: str
    type:  str    # task | event | note | journal


class ExternalLink(BaseModel):
    id:  str
    url: str


class ContextSummary(BaseModel):
    id:    str
    name:  str
    color: str


class LinkPanel(BaseModel):
    """Everything the side panel needs for a single object."""
    object_id:      str
    object_title:   str
    object_type:    str
    backlinks:      List[LinkedObject]   # objects whose content [[links]] to this one
    outgoing_links: List[LinkedObject]   # objects this one [[links]] to
    dangling_links: List[str]            # [[titles]] that appear in content but don't resolve
    contexts:       List[ContextSummary]
    tags:           List[str]
    external_links: List[ExternalLink]


class TitleMatch(BaseModel):
    """One result from the [[Title]] autocomplete endpoint."""
    id:    str
    title: str
    type:  str    # shown in UI as "note:My Title" etc.
