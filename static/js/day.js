/**
 * day.js — Day view for planr v1.2.1
 */
import {
  api, todayStr, getURLParam, setURLParam,
  addDays, fmtDateLong, isToday, esc,
  initNav, initCapture,
  openTaskModal, openEventModal, renderTaskItem,
} from '/static/js/shared.js';
import {
  layoutTimed, makeTimedBlock, addHourLines,
  startNowLine, stopNowLine, initViewKeys, GRID_H,
} from '/static/js/cal-common.js';

let currentDate  = '';
let effortFilter = '';

document.addEventListener('DOMContentLoaded', () => {
  initNav();
  initCapture(load);
  initViewKeys(() => currentDate);

  currentDate = getURLParam('date', todayStr());

  const grid = document.getElementById('time-grid');
  grid.style.height = GRID_H + 'px';
  addHourLines(grid, true);

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
  const data = await api.get('/calendar/day', { date_str: currentDate });

  // All-day strip: true all-day events + middle days of multi-day events
  const strip = document.getElementById('allday-strip');
  strip.innerHTML = '';
  for (const ev of data.all_day_events) {
    const pill = document.createElement('div');
    pill.className = 'allday-pill';
    pill.style.background = ev.context_color || '#4B5563';
    const span = ev.total_days > 1
      ? ` <span class="pill-span">d${ev.day_index}/${ev.total_days}</span>` : '';
    pill.innerHTML = esc(ev.title) + span;
    pill.title = ev.total_days > 1
      ? `${ev.title} (${ev.start_date} → ${ev.end_date})` : ev.title;
    pill.onclick = () => openEventModal(ev, load, load);
    strip.appendChild(pill);
  }

  // Timed events (including first/last-day segments of multi-day events)
  const grid = document.getElementById('time-grid');
  grid.querySelectorAll('.ev-block').forEach(el => el.remove());
  for (const { ev, col, cols, sm, em } of layoutTimed(data.timed_events)) {
    const block = makeTimedBlock(ev, col, cols, sm, em, 56, true, load);
    if (block) grid.appendChild(block);
  }
}

async function loadTasks() {
  const tasks = await api.get(`/tasks/day/${currentDate}`, { effort: effortFilter });
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
function onOpen(t) { openTaskModal(t, load, load); }
