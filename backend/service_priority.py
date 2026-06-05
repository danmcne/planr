"""
Priority scoring for tasks.

Combined score:
    score = urgency_w    * urgency(due_date)
          + importance_w * importance(enum)
          - effort_w     * effort(time_estimate_min)
          + staleness_w  * staleness(updated_at)

All component scores are normalised to [0, 1].
The combined score is clamped to [0, 1].

Weights come from the active priority_profile row — never hardcoded here.
"""

import math
from datetime import date, datetime, timezone
from typing import Optional

IMPORTANCE_MAP = {
    "low":      0.10,
    "normal":   0.40,
    "high":     0.70,
    "critical": 1.00,
}


def _urgency(due_date: Optional[date]) -> float:
    """
    Exponential decay: high when deadline is close.
    k=7: 7 days left → 0.63, 1 day → 0.999, overdue → 1.0, no date → 0.0.
    """
    if due_date is None:
        return 0.0
    today = datetime.now(timezone.utc).date()
    days_left = (due_date - today).days
    if days_left <= 0:
        return 1.0
    return 1.0 - math.exp(-7.0 / days_left)


def _importance(importance: str) -> float:
    return IMPORTANCE_MAP.get(importance, 0.40)


def _effort(time_estimate_min: Optional[int]) -> float:
    """
    Penalty grows with estimated size. Unknown → neutral 0.5.
    60 min → 0.63, 120 min → 0.86, 240 min → 0.98.
    """
    if not time_estimate_min or time_estimate_min <= 0:
        return 0.5
    return 1.0 - math.exp(-time_estimate_min / 60.0)


def _staleness(updated_at: datetime) -> float:
    """
    Log decay: 0 at last update, approaches 1.0 after ~1 year.
    Small bonus for tasks that haven't been touched in a while.
    """
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    days = max(0, (datetime.now(timezone.utc) - updated_at).days)
    return min(1.0, math.log1p(days) / math.log1p(365))


def compute_priority_score(
    importance: str,
    due_date: Optional[date],
    time_estimate_min: Optional[int],
    updated_at: datetime,
    weights: dict,
) -> float:
    score = (
        weights["urgency_weight"]    * _urgency(due_date)
        + weights["importance_weight"] * _importance(importance)
        - weights["effort_weight"]     * _effort(time_estimate_min)
        + weights["staleness_weight"]  * _staleness(updated_at)
    )
    return round(max(0.0, min(1.0, score)), 4)
