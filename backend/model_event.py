from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class EventStatus(str, Enum):
    confirmed = "confirmed"
    tentative = "tentative"
    cancelled = "cancelled"


class EditMode(str, Enum):
    this   = "this"    # this occurrence only → stored override
    future = "future"  # this and all future  → truncate master, new master
    all    = "all"     # all occurrences      → edit master, delete children


class ContextSummary(BaseModel):
    id:    str
    name:  str
    color: str


class EventCreate(BaseModel):
    title:          str = Field(min_length=1, max_length=500)
    start_datetime: datetime
    end_datetime:   datetime
    all_day:        bool = False
    location:       Optional[str] = None
    description:    Optional[str] = None
    status:         EventStatus = EventStatus.confirmed
    rrule:          Optional[str] = None     # iCal RRULE e.g. "FREQ=WEEKLY;BYDAY=MO"
    context_ids:    List[str] = Field(default_factory=list)
    tag_names:      List[str] = Field(default_factory=list)


class EventUpdate(BaseModel):
    title:          Optional[str] = Field(None, min_length=1, max_length=500)
    start_datetime: Optional[datetime] = None
    end_datetime:   Optional[datetime] = None
    all_day:        Optional[bool] = None
    location:       Optional[str] = None
    description:    Optional[str] = None
    status:         Optional[EventStatus] = None
    rrule:          Optional[str] = None
    context_ids:    Optional[List[str]] = None
    tag_names:      Optional[List[str]] = None


class OccurrenceResponse(BaseModel):
    # id is a real UUID for stored rows, or "{master_id}::{YYYY-MM-DD}" for virtual ones
    id:              str
    title:           str
    start_datetime:  datetime
    end_datetime:    datetime
    all_day:         bool
    location:        Optional[str] = None
    description:     Optional[str] = None
    status:          str
    rrule:           Optional[str] = None
    rrule_until:     Optional[date] = None
    is_recurring:    bool                    # master has an rrule
    is_override:     bool                    # this is a stored child (one-off edit)
    is_virtual:      bool                    # generated at query time, not in DB
    parent_event_id: Optional[str] = None
    root_event_id:   Optional[str] = None
    original_date:   Optional[date] = None   # slot in the series this replaces
    created_at:      str
    updated_at:      str
    contexts:        List[ContextSummary] = []
    tags:            List[str] = []
