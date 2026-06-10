/**
 * week.js — Week view for planr v1.2.1
 *
 * Spanning bars (all-day events + middle days of multi-day timed events)
 * live in the lane row under the header. First/last days of multi-day
 * timed events appear as timed blocks with "09:00 →" / "→ 15:00" labels.
 */
import {
  api, todayStr, getURLParam, setURLParam,
  addDays, mondayOf, fmtWeekRange, fmtTime, esc,
  initNav, initCapture, openTaskModal, openEventModal, IMP_COLOR,
} from '/static/js/shared.js';
import {
  layoutTimed, makeTimedBlock, addHourLines,
  startNowLine, stopNowLine, initViewKeys, GRID_H, DAY_NAMES,
} from '/static/js/cal-common.js';

let weekStart = '';

document.addEventListener('DOMContentLoaded', () => {
  initNav();
  initCapture(load);
  initViewKeys(() => weekStart);

  weekStart = mondayOf(getURLParam('date', todayStr()));

  const gutter = document.getElementById('week-time-col');
  gutter.style.height = GRID_H + 'px';
  addHourLines(gutter, true);

  document.getElementById('btn-prev').onclick  = () => goTo(addDays(weekStart, -7));
  document.getElementById('btn-next').onclick  = () => goTo(addDays(weekStart, 7));
  document.getElementById('btn-today').onclick = () => goTo(mondayOf(todayStr()));
  document.getElementById('btn-add-event').onclick = () => openEventModal({}, load);

  load();
});

function goTo(d) {
  weekStart = d;
  setURLParam('date', d);
  load();
}

async function load() {
  document.getElementById('week-label').textContent = fmtWeekRange(weekStart);

  const data   = await api.get('/calendar/week', { start_date: weekStart });
  const header = document.getElementById('week-header');
  const body   = document.getElementById('week-body');
  const today  = todayStr();

  header.querySelectorAll('.week-dh-wrap').forEach(el => el.remove());
  body.querySelectorAll('.week-day-col').forEach(el => el.remove());
  stopNowLine();

  renderSpanning(data.spanning_events);

  let todayCol = null;
  for (let i = 0; i < 7; i++) {
    const dateStr = data.days[i];
    const isT = dateStr === today;

    // Header cell
    const hd = document.createElement('div');
    hd.className = `week-header-col week-dh-wrap${isT ? ' today' : ''}`;
    hd.innerHTML = `<div class="week-dh${isT ? ' today' : ''}">
      <div class="dn">${DAY_NAMES[i]}</div>
      <div class="dd">${dateStr.slice(8)}</div>
    </div>`;
    hd.addEventListener('click', () => location.href = `/day?date=${dateStr}`);
    header.appendChild(hd);

    // Day column
    const col = document.createElement('div');
    col.className = 'week-day-col';
    col.style.height = GRID_H + 'px';
    col.dataset.date = dateStr;
    addHourLines(col, false);

    for (const { ev, col: c, cols, sm, em } of layoutTimed(data.timed_by_day[dateStr] || [])) {
      const block = makeTimedBlock(ev, c, cols, sm, em, 2, false, load);
      if (block) col.appendChild(block);
    }

    // Task deadlines pinned at the bottom of the column
    const dayTasks = data.tasks_by_day[dateStr] || [];
    if (dayTasks.length) {
      const tray = document.createElement('div');
      tray.className = 'week-task-tray';
      for (const t of dayTasks.slice(0, 3)) {
        const chip = document.createElement('div');
        chip.className = 'week-task-chip';
        chip.style.borderLeftColor = IMP_COLOR[t.importance] || IMP_COLOR.normal;
        chip.textContent = t.title;
        chip.title = `${t.title} — due ${t.due_at.slice(0,10)}`;
        chip.onclick = e => { e.stopPropagation(); openTaskModal(t, load, load); };
        tray.appendChild(chip);
      }
      if (dayTasks.length > 3) {
        const more = document.createElement('div');
        more.className = 'week-task-more';
        more.textContent = `+${dayTasks.length - 3} tasks`;
        more.onclick = () => location.href = `/day?date=${dateStr}`;
        tray.appendChild(more);
      }
      col.appendChild(tray);
    }

    if (isT) todayCol = col;
    body.appendChild(col);
  }

  if (todayCol) startNowLine(todayCol);
}

/** Stack spanning bars into lanes (greedy interval scheduling). */
function renderSpanning(events) {
  const lanesEl = document.getElementById('week-allday-lanes');
  lanesEl.innerHTML = '';
  const laneEnds = [];
  const placed = [];

  for (const ev of [...events].sort((a, b) =>
      a.col_start - b.col_start || b.col_span - a.col_span)) {
    let lane = 0;
    while (laneEnds[lane] !== undefined && laneEnds[lane] > ev.col_start) lane++;
    laneEnds[lane] = ev.col_start + ev.col_span;
    placed.push({ ev, lane });
  }

  lanesEl.style.height = (placed.length ? laneEnds.length * 22 + 4 : 8) + 'px';

  for (const { ev, lane } of placed) {
    const c   = ev.context_color || '#4B5563';
    const bar = document.createElement('div');
    bar.className = 'week-span-bar'
      + (ev.continues_before ? ' cont-l' : '')
      + (ev.continues_after  ? ' cont-r' : '');
    bar.style.cssText = `
      left: ${ev.col_start / 7 * 100}%;
      width: calc(${ev.col_span / 7 * 100}% - ${ev.continues_after ? 0 : 6}px);
      top: ${lane * 22 + 2}px;
      background: ${c}33; border-color: ${c}; color: ${c};
    `;
    bar.innerHTML = `${ev.continues_before ? '◂ ' : ''}${esc(ev.title)}${ev.continues_after ? ' ▸' : ''}`;
    bar.title = ev.all_day
      ? `${ev.title} (${ev.start_date} → ${ev.end_date})`
      : `${ev.title}\n${ev.start_date} ${fmtTime(ev.start_at)} → ${ev.end_date} ${fmtTime(ev.end_at)}`;
    bar.onclick = () => openEventModal(ev, load, load);
    lanesEl.appendChild(bar);
  }
}
