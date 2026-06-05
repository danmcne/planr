from __future__ import annotations

from datetime import date
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    inbox    = "inbox"
    active   = "active"
    done     = "done"
    deferred = "deferred"
    someday  = "someday"


class Importance(str, Enum):
    low      = "low"
    normal   = "normal"
    high     = "high"
    critical = "critical"


class RecurrenceRule(BaseModel):
    type:     Literal["fixed", "cyclic"]
    interval: int = Field(ge=1)
    unit:     Literal["day", "week", "month"]


class ContextSummary(BaseModel):
    id:    str
    name:  str
    color: str


class TaskCreate(BaseModel):
    title:             str = Field(min_length=1, max_length=500)
    description:       Optional[str] = None
    status:            TaskStatus = TaskStatus.inbox
    importance:        Importance = Importance.normal
    time_estimate_min: Optional[int] = Field(None, ge=1, le=1440)
    due_date:          Optional[date] = None
    recurrence_rule:   Optional[RecurrenceRule] = None
    parent_task_id:    Optional[str] = None
    context_ids:       List[str] = Field(default_factory=list)
    tag_names:         List[str] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title:             Optional[str] = Field(None, min_length=1, max_length=500)
    description:       Optional[str] = None
    status:            Optional[TaskStatus] = None
    importance:        Optional[Importance] = None
    time_estimate_min: Optional[int] = Field(None, ge=1, le=1440)
    due_date:          Optional[date] = None
    recurrence_rule:   Optional[RecurrenceRule] = None
    parent_task_id:    Optional[str] = None
    context_ids:       Optional[List[str]] = None
    tag_names:         Optional[List[str]] = None


class TaskResponse(BaseModel):
    id:                str
    title:             str
    description:       Optional[str] = None
    status:            str
    importance:        str
    time_estimate_min: Optional[int] = None
    due_date:          Optional[date] = None
    recurrence_rule:   Optional[RecurrenceRule] = None
    parent_task_id:    Optional[str] = None
    created_at:        str
    updated_at:        str
    contexts:          List[ContextSummary] = []
    tags:              List[str] = []
    subtask_count:     int = 0
    priority_score:    Optional[float] = None
