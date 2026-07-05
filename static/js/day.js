/**
 * day.js — Day view for planr v1.3.0
 *
 * Self-contained: imports only from shared.js. Honours the top-bar root
 * context filter. Multi-day events arrive segmented from the API: middle
 * days as all-day pills, first/last days as timed blocks with seg_* times
 * and "09:00 →" / "→ 16:00" labels.
 *
 * Colors: left edge = ROOT context color, fill/text = the item's own
 * (sub)context color — so work.project reads as work-with-a-twist.
 */
import {
  api, todayStr, getURLParam, setURLParam,
  addDays, fmtDateLong, isToday, esc, toast,
  initNav, initCapture, initRootFilter, filterByRoot,
  openTaskModal, openEventModal, openEventView, openTaskView, renderTaskItem,
} from '/static/js/shared.js?v=6';

const GRID_START  = 6;
const GRID_END    = 22;
const PX_PER_HOUR = 60;
const GRID_H      = (GRID_END - GRID_START) * PX_PER_HOUR;

let currentDate  = '';
let effortFilter = '';
let nowLineTimer = null;

document.addEventListener('DOMContentLoaded', () => {
  initNav();
  initCapture(load);
  initRootFilter(load);

  currentDate = getURLParam('date', todayStr());

  const grid = document.getElementById('time-grid');
  grid.style.height = GRID_H + 'px';
  for (let h = GRID_START; h <= GRID_END; h++) {
    const top = (h - GRID_START) * PX_PER_HOUR;
    const row = document.createElement('div');
    row.className = 'tg-hour';
    row.style.top = top + 'px';
    grid.appendChild(row);
    if (h < GRID_END) {
      const lbl = document.createElement('span');
      lbl.className = 'tg-label';
      lbl.style.top = top + 'px';
      lbl.textContent = `${String(h).padStart(2,'0')}:00`;
      grid.appendChild(lbl);
    }
  }

  document.getElementById('btn-prev').onclick  = () => goTo(addDays(currentDate, -1));
  document.getElementById('btn-next').onclick  = () => goTo(addDays(currentDate, 1));
  document.getElementById('btn-today').onclick = () => goTo(todayStr());
  document.getElementById('btn-add-task').onclick  = () => openTaskModal({}, load);
  document.getElementById('btn-add-event').onclick = () => openEventModal({}, load);

  document.getElementById('effort-chips').addEventListener('click', e => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    effortFilter = chip.dataset.effort;
    document.querySelectorAll('#effort-chips .chip').forEach(c =>
      c.classList.toggle('on', c === chip));
    loadTasks();
  });

  document.addEventListener('keydown', e => {
    if (e.target.matches('input, textarea, select') || e.ctrlKey || e.metaKey || e.altKey) return;
    if (!document.getElementById('modal-overlay')?.classList.contains('hidden')) return;
    if (e.key === 'ArrowLeft')  goTo(addDays(currentDate, -1));
    else if (e.key === 'ArrowRight') goTo(addDays(currentDate, 1));
    else if (e.key === 't') goTo(todayStr());
    else if (e.key === 'w') location.href = `/week?date=${currentDate}`;
    else if (e.key === 'm') location.href = `/month?date=${currentDate}`;
  });

  load();
});

function goTo(d) {
  currentDate = d;
  setURLParam('date', d);
  load();
}

async function load() {
  document.getElementById('day-label').textContent = fmtDateLong(currentDate);
  await Promise.all([loadEvents(), loadTasks()]);
  stopNowLine();
  if (isToday(currentDate)) startNowLine(document.getElementById('time-grid'));
}

async function loadEvents() {
  let data = { all_day_events: [], timed_events: [] };
  try {
    data = await api.get('/calendar/day', { date_str: currentDate });
  } catch (err) {
    toast(`Day data failed: ${err.message}`, 'err');
  }

  const strip = document.getElementById('allday-strip');
  strip.innerHTML = '';
  for (const ev of filterByRoot(data.all_day_events)) {
    const cc = ev.context_color || '#4B5563';
    const rc = ev.root_color || cc;
    const pill = document.createElement('div');
    pill.className = 'allday-pill';
    pill.style.background = cc;
    pill.style.borderLeft = `4px solid ${rc}`;
    const span = ev.total_days > 1
      ? ` <span class="pill-span">d${ev.day_index}/${ev.total_days}</span>` : '';
    pill.innerHTML = (ev.recurrence ? '↻ ' : '') + esc(ev.title) + span;
    pill.title = ev.total_days > 1
      ? `${ev.title} (${ev.start_date} → ${ev.end_date})` : ev.title;
    pill.onclick = () => openEventView(ev, load);
    strip.appendChild(pill);
  }

  const grid = document.getElementById('time-grid');
  grid.querySelectorAll('.ev-block').forEach(el => el.remove());
  for (const { ev, col, cols, sm, em } of layoutTimed(filterByRoot(data.timed_events))) {
    const block = makeTimedBlock(ev, col, cols, sm, em, 56, true);
    if (block) grid.appendChild(block);
  }
}

async function loadTasks() {
  let tasks = [];
  try {
    tasks = await api.get(`/tasks/day/${currentDate}`, { effort: effortFilter });
  } catch (err) {
    toast(`Tasks failed: ${err.message}`, 'err');
  }
  tasks = filterByRoot(tasks);
  const list = document.getElementById('task-list');
  list.innerHTML = '';
  if (!tasks.length) {
    list.innerHTML = '<div class="empty"><span class="empty-icon">✓</span>Nothing due today</div>';
    return;
  }
  for (const t of tasks) list.appendChild(renderTaskItem(t, onCheck, onOpen));
}

async function onCheck(t, el) {
  const ns = t.status === 'done' ? 'active' : 'done';
  await api.put(`/tasks/${t.uuid}`, { status: ns });
  t.status = ns;
  el.classList.toggle('done', ns === 'done');
  el.querySelector('.t-check').textContent = ns === 'done' ? '✓' : '';
}
function onOpen(t) { openTaskView(t, load); }

// ── Timed-event layout (inlined for standalone deploy) ───────────────────────

function isoToMins(iso) {
  const d = new Date(iso);
  return d.getHours() * 60 + d.getMinutes();
}

function layoutTimed(events) {
  const items = events
    .filter(e => (e.seg_start_at || e.start_at))
    .map(e => {
      const sm = isoToMins(e.seg_start_at || e.start_at);
      const endIso = e.seg_end_at || e.end_at;
      let em = endIso ? isoToMins(endIso) : sm + 60;
      if (endIso?.slice(11, 16) === '23:59') em = 24 * 60;
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

function makeTimedBlock(ev, col, cols, sm, em, gutterPx, showRange) {
  const rawTop = (sm / 60 - GRID_START) * PX_PER_HOUR;
  const top    = Math.max(0, rawTop);
  let h = Math.max(20, (em - sm) / 60 * PX_PER_HOUR - (top - rawTop));
  h = Math.min(h, GRID_H - top);
  if (h <= 0) return null;

  const cc = ev.context_color || '#4B5563';
  const rc = ev.root_color || cc;
  const el = document.createElement('div');
  el.className = 'ev-block'
    + (ev.cont_before ? ' cont-before' : '')
    + (ev.cont_after  ? ' cont-after'  : '');
  el.style.cssText = `
    top:${top}px; height:${h}px;
    background:${cc}22; border-left-color:${rc}; color:${cc};
    left:calc(${gutterPx}px + (100% - ${gutterPx + 4}px) * ${col} / ${cols});
    width:calc((100% - ${gutterPx + 4}px) / ${cols} - 2px);
  `;
  let time;
  if (ev.cont_after)       time = `${fmtTime(ev.seg_start_at || ev.start_at)} →`;
  else if (ev.cont_before) time = `→ ${fmtTime(ev.seg_end_at || ev.end_at)}`;
  else time = fmtTime(ev.start_at)
    + (showRange && ev.end_at ? ' – ' + fmtTime(ev.end_at) : '');
  const days = ev.total_days > 1
    ? ` <span class="ev-days">(${ev.start_date} → ${ev.end_date})</span>` : '';
  el.innerHTML = `
    <div class="ev-title">${ev.recurrence ? '↻ ' : ''}${esc(ev.title)}</div>
    <div class="ev-time">${time}${days}</div>
  `;
  el.title = ev.total_days > 1
    ? `${ev.title}\n${ev.start_date} ${fmtTime(ev.start_at)} → ${ev.end_date} ${fmtTime(ev.end_at)}`
    : ev.title;
  el.onclick = () => openEventView(ev, load);
  return el;
}

function fmtTime(iso) {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}

function startNowLine(container) {
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
  clearInterval(nowLineTimer);
  nowLineTimer = setInterval(draw, 60_000);
}
function stopNowLine() {
  clearInterval(nowLineTimer);
  document.querySelectorAll('.tg-now').forEach(el => el.remove());
}
