# backend/service_ics.py
"""
ICS (iCalendar RFC 5545) generation for events and tasks.
No external library needed — the format is simple enough to generate directly.
"""

import json
from datetime import datetime, timezone

PRODID = '-//Planr//Planr//EN'

# ── formatting helpers ────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    return (text
            .replace('\\', '\\\\')
            .replace(';', '\\;')
            .replace(',', '\\,')
            .replace('\n', '\\n')
            .replace('\r', ''))


def _fold(line: str) -> str:
    """Fold lines > 75 octets per RFC 5545 §3.1."""
    out, raw = [], line.encode('utf-8')
    while len(raw) > 75:
        # Back off until we have a valid UTF-8 boundary
        n = 75
        while n > 0:
            try:
                chunk = raw[:n].decode('utf-8')
                break
            except UnicodeDecodeError:
                n -= 1
        out.append(chunk)
        raw = b' ' + raw[n:]
    out.append(raw.decode('utf-8'))
    return '\r\n'.join(out)


def _ical_dt(iso: str) -> str:
    """ISO datetime → iCal UTC string (20260601T090000Z)."""
    from dateutil.parser import isoparse
    dt = isoparse(iso)
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y%m%dT%H%M%SZ')


def _ical_date(iso_date: str) -> str:
    return iso_date.replace('-', '')


def _dtstamp() -> str:
    """RFC 5545 DTSTAMP — always the current UTC moment, not module-load time."""
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')

_IMPORTANCE_TO_PRIORITY = {
    'critical': '1',
    'high':     '3',
    'normal':   '5',
    'low':      '7',
}

_TASK_STATUS = {
    'inbox':    'NEEDS-ACTION',
    'active':   'IN-PROCESS',
    'done':     'COMPLETED',
    'deferred': 'NEEDS-ACTION',
    'someday':  'NEEDS-ACTION',
}


# ── VEVENT ────────────────────────────────────────────────────────────────────

def event_to_vevent(row: dict) -> str:
    lines = ['BEGIN:VEVENT']
    lines.append(_fold(f'UID:{row["id"]}@planr'))
    lines.append(_fold(f'SUMMARY:{_esc(row["title"])}'))

    if row.get('all_day'):
        lines.append(_fold(f'DTSTART;VALUE=DATE:{_ical_date(row["start_datetime"][:10])}'))
        lines.append(_fold(f'DTEND;VALUE=DATE:{_ical_date(row["end_datetime"][:10])}'))
    else:
        lines.append(_fold(f'DTSTART:{_ical_dt(row["start_datetime"])}'))
        lines.append(_fold(f'DTEND:{_ical_dt(row["end_datetime"])}'))

    if row.get('rrule'):
        rrule_val = row['rrule']
        if row.get('rrule_until'):
            # UNTIL must live inside the RRULE property, not as a separate EXDATE.
            # EXDATE excludes specific occurrences; UNTIL ends the series.
            rrule_val += f';UNTIL={_ical_date(row["rrule_until"])}'
        lines.append(_fold(f'RRULE:{rrule_val}'))
    if row.get('location'):
        lines.append(_fold(f'LOCATION:{_esc(row["location"])}'))
    if row.get('description'):
        lines.append(_fold(f'DESCRIPTION:{_esc(row["description"])}'))
    if row.get('status', 'confirmed').upper() == 'CANCELLED':
        lines.append('STATUS:CANCELLED')

    lines.append(_fold(f'DTSTAMP:{_dtstamp()}'))
    lines.append('END:VEVENT')
    return '\r\n'.join(lines)


# ── VTODO ─────────────────────────────────────────────────────────────────────

def task_to_vtodo(row: dict) -> str:
    lines = ['BEGIN:VTODO']
    lines.append(_fold(f'UID:{row["id"]}@planr'))
    lines.append(_fold(f'SUMMARY:{_esc(row["title"])}'))

    if row.get('description'):
        lines.append(_fold(f'DESCRIPTION:{_esc(row["description"])}'))
    if row.get('due_date'):
        lines.append(_fold(f'DUE;VALUE=DATE:{_ical_date(row["due_date"])}'))
    if row.get('time_estimate_min'):
        h, m = divmod(row['time_estimate_min'], 60)
        lines.append(_fold(f'DURATION:PT{h}H{m}M'))

    lines.append(_fold(f'STATUS:{_TASK_STATUS.get(row.get("status", "inbox"), "NEEDS-ACTION")}'))
    lines.append(_fold(f'PRIORITY:{_IMPORTANCE_TO_PRIORITY.get(row.get("importance", "normal"), "5")}'))

    if row.get('recurrence_rule'):
        try:
            rule = json.loads(row['recurrence_rule'])
            freq = {'day': 'DAILY', 'week': 'WEEKLY', 'month': 'MONTHLY'}.get(rule.get('unit', 'day'), 'DAILY')
            lines.append(_fold(f'RRULE:FREQ={freq};INTERVAL={rule.get("interval", 1)}'))
        except Exception:
            pass

    lines.append(_fold(f'DTSTAMP:{_dtstamp()}'))
    lines.append('END:VTODO')
    return '\r\n'.join(lines)


# ── calendar envelope ─────────────────────────────────────────────────────────

def build_ical(*blocks: str) -> str:
    parts = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        f'PRODID:{PRODID}',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
    ]
    parts.extend(b for b in blocks if b)
    parts.append('END:VCALENDAR')
    return '\r\n'.join(parts)
