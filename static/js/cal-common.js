/**
 * cal-common.js — shared time-grid helpers for day & week views (planr v1.2.1)
 *
 * Multi-day timed events arrive from the API as *segments*:
 *   first day  → timed block with cont_after  (label "09:00 →")
 *   middle days→ spanning bar (all-day strip / lanes)
 *   last day   → timed block with cont_before (label "→ 15:00")
 * Use seg_start_at / seg_end_at when present; fall back to start_at / end_at.
 */
import { esc, fmtTime, openEventModal } from '/static/js/shared.js';

export const GRID_START  = 6;    // 06:00
export const GRID_END    = 22;   // 22:00
export const PX_PER_HOUR = 60;
export const GRID_H      = (GRID_END - GRID_START) * PX_PER_HOUR;
export const DAY_NAMES   = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

export function isoToMins(iso) {
  const d = new Date(iso);
  return d.getHours() * 60 + d.getMinutes();
}

/**
 * Overlap-aware column layout. Events are grouped into clusters of
 * transitively overlapping intervals; within a cluster each event gets a
 * column and all share the cluster's column count.
 */
export function layoutTimed(events) {
  const items = events
    .filter(e => (e.seg_start_at || e.start_at))
    .map(e => {
      const sm = isoToMins(e.seg_start_at || e.start_at);
      const endIso = e.seg_end_at || e.end_at;
      let em = endIso ? isoToMins(endIso) : sm + 60;
      if (e.cont_after && endIso?.slice(11, 16) === '23:59') em = 24 * 60;
      if (em <= sm) em = sm + 30;
      return { ev: e, sm, em, col: 0, cols: 1 };
    })
    .sort((a, b) => a.sm - b.sm || b.em - a.em);

  const out = [];
  let cluster = [], colEnds = [], clusterEnd = -1;
  const flush = () => {
    const n = Math.max(1, colEnds.length);
    cluster.forEach(it => { it.cols = n; });
    out.push(...cluster);
    cluster = []; colEnds = []; clusterEnd = -1;
  };
  for (const it of items) {
    if (cluster.length && it.sm >= clusterEnd) flush();
    let c = 0;
    while (colEnds[c] !== undefined && colEnds[c] > it.sm) c++;
    colEnds[c] = it.em;
    it.col = c;
    cluster.push(it);
    clusterEnd = Math.max(clusterEnd, it.em);
  }
  flush();
  return out;
}

/**
 * Build a positioned timed-event block.
 * gutterPx — left offset reserved for time labels (56 day view, 2 week cols).
 * Returns null if the block falls entirely outside the visible grid.
 */
export function makeTimedBlock(ev, col, cols, sm, em, gutterPx, showRange, onChange) {
  const rawTop = (sm / 60 - GRID_START) * PX_PER_HOUR;
  const top    = Math.max(0, rawTop);
  let h = Math.max(20, (em - sm) / 60 * PX_PER_HOUR - (top - rawTop));
  h = Math.min(h, GRID_H - top);
  if (h <= 0) return null;

  const c = ev.context_color || '#4B5563';
  const el = document.createElement('div');
  el.className = 'ev-block'
    + (ev.cont_before ? ' cont-before' : '')
    + (ev.cont_after  ? ' cont-after'  : '');
  el.style.cssText = `
    top:${top}px; height:${h}px;
    background:${c}22; border-left-color:${c}; color:${c};
    left:calc(${gutterPx}px + (100% - ${gutterPx + 4}px) * ${col} / ${cols});
    width:calc((100% - ${gutterPx + 4}px) / ${cols} - 2px);
  `;
  let time;
  if (ev.cont_after)       time = `${fmtTime(ev.seg_start_at || ev.start_at)} →`;
  else if (ev.cont_before) time = `→ ${fmtTime(ev.seg_end_at || ev.end_at)}`;
  else {
    time = fmtTime(ev.start_at)
      + (showRange && ev.end_at ? ' – ' + fmtTime(ev.end_at) : '');
  }
  const days = ev.total_days > 1
    ? ` <span class="ev-days">(${ev.start_date} → ${ev.end_date})</span>` : '';
  el.innerHTML = `
    <div class="ev-title">${esc(ev.title)}</div>
    <div class="ev-time">${time}${days}</div>
  `;
  el.title = ev.total_days > 1
    ? `${ev.title}\n${ev.start_date} ${fmtTime(ev.start_at)} → ${ev.end_date} ${fmtTime(ev.end_at)}`
    : ev.title;
  el.onclick = () => openEventModal(ev, onChange, onChange);
  return el;
}

// ── Now line ──────────────────────────────────────────────────────────────────

let _nowTimer = null;

export function startNowLine(container) {
  const draw = () => {
    document.querySelectorAll('.tg-now').forEach(el => el.remove());
    const now  = new Date();
    const mins = now.getHours() * 60 + now.getMinutes();
    if (mins < GRID_START * 60 || mins > GRID_END * 60) return;
    const line = document.createElement('div');
    line.className = 'tg-now';
    line.style.top = ((mins / 60 - GRID_START) * PX_PER_HOUR) + 'px';
    container.appendChild(line);
  };
  draw();
  clearInterval(_nowTimer);
  _nowTimer = setInterval(draw, 60_000);
}

export function stopNowLine() {
  clearInterval(_nowTimer);
  document.querySelectorAll('.tg-now').forEach(el => el.remove());
}

// ── Hour scaffolding ──────────────────────────────────────────────────────────

export function addHourLines(el, withLabels) {
  for (let h = GRID_START; h <= GRID_END; h++) {
    const top = (h - GRID_START) * PX_PER_HOUR;
    const row = document.createElement('div');
    row.className = 'tg-hour';
    row.style.top = top + 'px';
    el.appendChild(row);
    if (withLabels && h < GRID_END) {
      const lbl = document.createElement('span');
      lbl.className = 'tg-label';
      lbl.style.top = top + 'px';
      lbl.textContent = `${String(h).padStart(2,'0')}:00`;
      el.appendChild(lbl);
    }
  }
}

// ── Cross-view keyboard shortcuts (d / w / m jump between views) ─────────────

export function initViewKeys(currentDate) {
  document.addEventListener('keydown', e => {
    if (e.target.matches('input, textarea, select') || e.ctrlKey || e.metaKey || e.altKey) return;
    if (!document.getElementById('modal-overlay').classList.contains('hidden')) return;
    const dest = { d: '/day', w: '/week', m: '/month' }[e.key];
    if (dest && location.pathname !== dest)
      location.href = `${dest}?date=${currentDate()}`;
    else if (e.key === 'ArrowLeft')  document.getElementById('btn-prev')?.click();
    else if (e.key === 'ArrowRight') document.getElementById('btn-next')?.click();
    else if (e.key === 't')          document.getElementById('btn-today')?.click();
  });
}
