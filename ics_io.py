"""ics_io.py — iCalendar (RFC 5545) writing and tolerant reading for planr.

Scope and conventions:
* Times are exported as floating local datetimes (no TZID) — planr is a
  single-user local tool with naive wall-clock semantics throughout.
  On import, a trailing Z or a TZID parameter is ignored and the literal
  clock time is taken.
* Recurring series map naturally: the stored rule is already RRULE text
  (legacy values are translated, day-of-month clamping made explicit),
  exception dates become EXDATE, and per-occurrence overrides become
  components sharing the master's UID with a RECURRENCE-ID — standard
  iCal. Split segments export as separate UIDs (also standard practice).
* Tasks export as VTODO (DUE, STATUS, PRIORITY), with X-PLANR-* fields
  carrying planr-specific detail (effort, recurrence type) for lossless
  round-trips.
"""
from datetime import datetime, timedelta

# ── text escaping and line folding ────────────────────────────────────────────

def esc(s: str) -> str:
    return (str(s or "").replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n"))


def unesc(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            c = s[i + 1]
            out.append({"n": "\n", "N": "\n"}.get(c, c))
            i += 2
        else:
            out.append(s[i]); i += 1
    return "".join(out)


def fold(line: str) -> str:
    """RFC 5545 line folding: max 75 octets, continuation lines start
    with a space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not parts else 74):
            parts.append(cur); cur = b
        else:
            cur += b
    parts.append(cur)
    return ("\r\n ".join(p.decode("utf-8") for p in parts))


def unfold(text: str) -> list:
    lines, out = text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), []
    for ln in lines:
        if ln[:1] in (" ", "\t") and out:
            out[-1] += ln[1:]
        elif ln:
            out.append(ln)
    return out


# ── datetime conversion ───────────────────────────────────────────────────────

def dt_ics(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%Y%m%dT%H%M%S")


def date_ics(iso: str) -> str:
    return iso[:10].replace("-", "")


def ics_to_iso(v: str):
    """ICS datetime/date → naive local ISO. Trailing Z / any TZ ignored
    (literal clock time). Returns (iso, is_date)."""
    v = v.strip().rstrip("Zz")
    if "T" in v:
        return (datetime.strptime(v[:15], "%Y%m%dT%H%M%S")
                .isoformat(timespec="seconds"), False)
    d = datetime.strptime(v[:8], "%Y%m%d")
    return d.strftime("%Y-%m-%dT00:00:00"), True


# ── building ──────────────────────────────────────────────────────────────────

_PRIORITY = {"critical": 1, "high": 3, "normal": 5, "low": 7}
_PRIORITY_BACK = {1: "critical", 2: "critical", 3: "high", 4: "high",
                  5: "normal", 6: "normal", 7: "low", 8: "low", 9: "low"}


def _vevent(row: dict) -> list:
    """row: an events row dict, optionally with context_path and
    export_exdates (exceptions minus override-covered dates)."""
    L = ["BEGIN:VEVENT"]
    uid = row.get("export_uid") or f"{row['uuid']}@planr"
    L.append(f"UID:{uid}")
    L.append(f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}")
    if row.get("all_day"):
        L.append(f"DTSTART;VALUE=DATE:{date_ics(row['start_at'])}")
        if row.get("end_at"):
            end = (datetime.fromisoformat(row["end_at"][:10] + "T00:00:00")
                   + timedelta(days=1))
            L.append(f"DTEND;VALUE=DATE:{end.strftime('%Y%m%d')}")
    else:
        L.append(f"DTSTART:{dt_ics(row['start_at'])}")
        if row.get("end_at"):
            L.append(f"DTEND:{dt_ics(row['end_at'])}")
    L.append(f"SUMMARY:{esc(row.get('title'))}")
    if row.get("description"):
        L.append(f"DESCRIPTION:{esc(row['description'])}")
    if row.get("location"):
        L.append(f"LOCATION:{esc(row['location'])}")
    if row.get("context_path"):
        L.append(f"CATEGORIES:{esc(row['context_path'])}")
        L.append(f"X-PLANR-CONTEXT:{esc(row['context_path'])}")
    if row.get("export_rrule"):
        L.append(f"RRULE:{row['export_rrule']}")
    for ex in row.get("export_exdates") or []:
        if row.get("all_day"):
            L.append(f"EXDATE;VALUE=DATE:{date_ics(ex)}")
        else:
            L.append(f"EXDATE:{dt_ics(ex)}")
    if row.get("recurrence_id"):
        L.append(f"RECURRENCE-ID:{dt_ics(row['recurrence_id'])}")
    L.append("END:VEVENT")
    return L


def _vtodo(t: dict) -> list:
    L = ["BEGIN:VTODO", f"UID:{t['uuid']}@planr",
         f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
         f"SUMMARY:{esc(t.get('title'))}"]
    if t.get("due_at"):
        L.append(f"DUE:{dt_ics(t['due_at'])}")
    L.append("STATUS:" + ("COMPLETED" if t.get("status") == "done"
                          else "NEEDS-ACTION"))
    L.append(f"PRIORITY:{_PRIORITY.get(t.get('importance'), 5)}")
    if t.get("description"):
        L.append(f"DESCRIPTION:{esc(t['description'])}")
    if t.get("context_path"):
        L.append(f"CATEGORIES:{esc(t['context_path'])}")
        L.append(f"X-PLANR-CONTEXT:{esc(t['context_path'])}")
    if t.get("export_rrule"):
        L.append(f"RRULE:{t['export_rrule']}")
    if t.get("recur_type"):
        L.append(f"X-PLANR-RECURTYPE:{t['recur_type']}")
    if t.get("effort"):
        L.append(f"X-PLANR-EFFORT:{t['effort']}")
    if t.get("status"):
        L.append(f"X-PLANR-STATUS:{t['status']}")
    L.append("END:VTODO")
    return L


def build_calendar(event_rows: list, todo_rows: list) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//planr//EN", "CALSCALE:GREGORIAN"]
    for r in event_rows:
        lines += _vevent(r)
    for t in todo_rows:
        lines += _vtodo(t)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


# ── parsing ───────────────────────────────────────────────────────────────────

def _parse_prop(line: str):
    """'NAME;PARAM=V;PARAM2=V2:value' → (name, {params}, value)"""
    head, _, value = line.partition(":")
    bits = head.split(";")
    name = bits[0].upper()
    params = {}
    for b in bits[1:]:
        k, _, v = b.partition("=")
        params[k.upper()] = v
    return name, params, value


def parse_calendar(text: str):
    """→ {'events': [component dicts], 'todos': [...]}. Tolerant: unknown
    properties ignored; components missing DTSTART/SUMMARY skipped."""
    events, todos = [], []
    cur, kind = None, None
    for line in unfold(text):
        name, params, value = _parse_prop(line)
        if name == "BEGIN" and value.upper() in ("VEVENT", "VTODO"):
            cur, kind = {"exdates": []}, value.upper()
            continue
        if name == "END" and value.upper() in ("VEVENT", "VTODO") and cur is not None:
            (events if kind == "VEVENT" else todos).append(cur)
            cur, kind = None, None
            continue
        if cur is None:
            continue
        try:
            if name == "UID":
                cur["uid"] = value
            elif name == "SUMMARY":
                cur["title"] = unesc(value)
            elif name == "DESCRIPTION":
                cur["description"] = unesc(value)
            elif name == "LOCATION":
                cur["location"] = unesc(value)
            elif name in ("CATEGORIES", "X-PLANR-CONTEXT"):
                cur.setdefault("categories", unesc(value).split(",")[0].strip())
            elif name == "DTSTART":
                cur["start_at"], cur["all_day"] = ics_to_iso(value)
            elif name == "DTEND":
                iso, is_date = ics_to_iso(value)
                if is_date:  # exclusive → planr's inclusive 23:59:59
                    end = datetime.fromisoformat(iso) - timedelta(seconds=1)
                    cur["end_at"] = end.isoformat(timespec="seconds")
                else:
                    cur["end_at"] = iso
            elif name == "DUE":
                cur["due_at"], _ = ics_to_iso(value)
            elif name == "RRULE":
                cur["rrule"] = value
            elif name == "EXDATE":
                for v in value.split(","):
                    cur["exdates"].append(ics_to_iso(v)[0])
            elif name == "RECURRENCE-ID":
                cur["recurrence_id"], _ = ics_to_iso(value)
            elif name == "STATUS":
                cur["ics_status"] = value.upper()
            elif name == "PRIORITY":
                cur["importance"] = _PRIORITY_BACK.get(int(value or 5), "normal")
            elif name == "X-PLANR-EFFORT":
                cur["effort"] = value
            elif name == "X-PLANR-STATUS":
                cur["planr_status"] = value
            elif name == "X-PLANR-RECURTYPE":
                cur["recur_type"] = value
        except (ValueError, TypeError):
            continue  # tolerate malformed values, keep the component
    return {"events": [e for e in events if e.get("start_at") and e.get("title")],
            "todos": [t for t in todos if t.get("title")]}
