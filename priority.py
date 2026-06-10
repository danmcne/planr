"""
priority.py — Task priority computation for planr

Score is in [0, 1]; higher means the task should surface sooner.

Weights:  urgency 40 %  |  importance 30 %  |  staleness 15 %  |  effort 15 %
"""
import math
from datetime import datetime, timezone
from typing import Optional

_IMPORTANCE = {"low": 0.10, "normal": 0.35, "high": 0.70, "critical": 1.00}

# Easier tasks get a slight boost (more likely to actually get done)
_EFFORT = {"low": 0.90, "medium": 0.55, "high": 0.20}


def _urgency(due_at: Optional[str], user_urgency: float) -> float:
    if not due_at:
        return max(0.0, min(1.0, user_urgency / 10.0))
    try:
        due = datetime.fromisoformat(due_at)
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        days = (due - datetime.now(timezone.utc)).total_seconds() / 86_400
        if days <= 0:
            return min(1.0, 0.95 + 0.05 * (1 - math.exp(days / 7)))
        if days <= 1:   return 0.95
        if days <= 3:   return 0.85
        if days <= 7:   return 0.70
        if days <= 14:  return 0.50
        if days <= 30:  return 0.35
        return max(0.05, 0.35 * math.exp(-0.02 * (days - 30)))
    except Exception:
        return max(0.0, min(1.0, user_urgency / 10.0))


def _staleness(created_at: str, last_active_at: Optional[str], defer_count: int) -> float:
    try:
        ref = datetime.fromisoformat(last_active_at or created_at)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - ref).total_seconds() / 86_400
        base  = min(1.0, math.log1p(days) / math.log1p(90))
        bonus = min(0.30, defer_count * 0.06)
        return min(1.0, base + bonus)
    except Exception:
        return 0.0


def compute_priority_score(
    status: str,
    importance: str,
    effort: str,
    user_urgency: float,
    due_at: Optional[str],
    created_at: str,
    last_active_at: Optional[str],
    defer_count: int = 0,
) -> float:
    if status in ("done", "someday"):
        return 0.0
    u = _urgency(due_at, user_urgency)
    i = _IMPORTANCE.get(importance, 0.35)
    e = _EFFORT.get(effort, 0.55)
    s = _staleness(created_at, last_active_at, defer_count)
    return round(0.40 * u + 0.30 * i + 0.15 * s + 0.15 * e, 4)
