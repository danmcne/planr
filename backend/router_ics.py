# backend/router_ics.py
"""
ICS export routes.

  GET /api/export/events.ics   all event masters (+ their RRULE)
  GET /api/export/tasks.ics    scheduled tasks (due date or recurrence) as VTODO
  GET /api/export/all.ics      combined feed
"""

import aiosqlite
from fastapi import APIRouter, Depends
from fastapi.responses import Response

from db import get_db
from service_ics import build_ical, event_to_vevent, task_to_vtodo

router = APIRouter(prefix='/export', tags=['export'])
_MIME = 'text/calendar; charset=utf-8'

_EVENT_SQL = (
    "SELECT o.id, o.title, e.start_datetime, e.end_datetime, "
    "       e.all_day, e.location, e.description, e.status, "
    "       e.rrule, e.rrule_until "
    "FROM objects o JOIN events e ON e.id = o.id "
    "WHERE e.parent_event_id IS NULL "   # masters only — RRULE covers the series
    "ORDER BY e.start_datetime"
)

_TASK_SQL = (
    "SELECT o.id, o.title, t.description, t.status, t.importance, "
    "       t.time_estimate_min, t.due_date, t.recurrence_rule "
    "FROM objects o JOIN tasks t ON t.id = o.id "
    "WHERE t.status NOT IN ('done') "
    "  AND (t.due_date IS NOT NULL OR t.recurrence_rule IS NOT NULL) "
    "ORDER BY t.due_date NULLS LAST"
)


@router.get('/events.ics')
async def export_events(db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute(_EVENT_SQL)
    blocks = [event_to_vevent(dict(r)) for r in await cur.fetchall()]
    return Response(
        content=build_ical(*blocks), media_type=_MIME,
        headers={'Content-Disposition': 'attachment; filename="planr-events.ics"'},
    )


@router.get('/tasks.ics')
async def export_tasks(db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute(_TASK_SQL)
    blocks = [task_to_vtodo(dict(r)) for r in await cur.fetchall()]
    return Response(
        content=build_ical(*blocks), media_type=_MIME,
        headers={'Content-Disposition': 'attachment; filename="planr-tasks.ics"'},
    )


@router.get('/all.ics')
async def export_all(db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute(_EVENT_SQL)
    event_blocks = [event_to_vevent(dict(r)) for r in await cur.fetchall()]
    cur = await db.execute(_TASK_SQL)
    task_blocks  = [task_to_vtodo(dict(r)) for r in await cur.fetchall()]
    return Response(
        content=build_ical(*event_blocks, *task_blocks), media_type=_MIME,
        headers={'Content-Disposition': 'attachment; filename="planr-all.ics"'},
    )
