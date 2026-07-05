/**
 * month.js — Month view for planr v1.3.0
 *
 * Self-contained: imports only from shared.js. Honours the top-bar root
 * context filter. The grid renders immediately from local date math, then
 * events/tasks fill in — a failed API call can no longer leave the page
 * silently blank.
 */
import {
  api, todayStr, getURLParam, setURLParam,
  fmtMonth, fmtTime, esc, toast, openEventView, openEventModal, openTaskModal,
  initNav, initCapture, initRootFilter, filterByRoot, IMP_COLOR,
} from '/static/js/shared.js?v=6';

let year  = 0;
let month = 0;

document.addEventListener('DOMContentLoaded', () => {
  initNav();
  initCapture(load);
  initRootFilter(load);

  const ref = new Date(getURLParam('date', todayStr()) + 'T12:00:00');
  year  = ref.getFullYear();
  month = ref.getMonth() + 1;

  document.getElementById('btn-add-event').onclick = () => openEventModal({}, load);
  document.getElementById('btn-add-task').onclick  = () => openTaskModal({}, load);
  document.getElementById('btn-prev').onclick  = () => navigate(-1);
  document.getElementById('btn-next').onclick  = () => navigate(1);
  document.getElementById('btn-today').onclick = () => {
    const n = new Date();
    year = n.getFullYear(); month = n.getMonth() + 1;
    sync(); load();
  };

  document.addEventListener('keydown', e => {
    if (e.target.matches('input, textarea, select') || e.ctrlKey || e.metaKey || e.altKey) return;
    if (!document.getElementById('modal-overlay')?.classList.contains('hidden')) return;
    if (e.key === 'ArrowLeft')  navigate(-1);
    else if (e.key === 'ArrowRight') navigate(1);
    else if (e.key === 't') document.getElementById('btn-today').click();
    else if (e.key === 'd') location.href = `/day?date=${anchor()}`;
    else if (e.key === 'w') location.href = `/week?date=${anchor()}`;
  });

  load();
});

function anchor() { return `${year}-${String(month).padStart(2,'0')}-01`; }
function sync()   { setURLParam('date', anchor()); }

function navigate(delta) {
  month += delta;
  if (month > 12) { month = 1;  year++; }
  if (month < 1)  { month = 12; year--; }
  sync(); load();
}

async function load() {
  document.getElementById('month-label').textContent = fmtMonth(year, month);

  // Render the grid immediately; fill with data when it arrives.
  renderGrid({ events_by_day: {}, tasks_by_day: {} });
  try {
    renderGrid(await api.get('/calendar/month', { year, month }));
  } catch (err) {
    toast(`Month data failed: ${err.message}`, 'err');
  }
}

function renderGrid(data) {
  const body = document.getElementById('month-body');
  body.innerHTML = '';

  const first       = new Date(year, month - 1, 1);
  const offset      = (first.getDay() + 6) % 7;          // Monday-first
  const daysInMonth = new Date(year, month, 0).getDate();
  const numRows     = Math.ceil((offset + daysInMonth) / 7);
  body.style.gridTemplateRows = `repeat(${numRows}, 1fr)`;

  const gridStart = new Date(year, month - 1, 1 - offset);
  const today     = todayStr();

  for (let i = 0; i < numRows * 7; i++) {
    const d  = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    const ds = d.toLocaleDateString('en-CA');
    body.appendChild(makeCell(ds, d.getDate(),
      d.getMonth() !== month - 1, data, today));
  }
}

function makeCell(ds, dayNum, isOther, data, today) {
  const cell = document.createElement('div');
  cell.className = `month-cell${ds === today ? ' today' : ''}${isOther ? ' other' : ''}`;

  let html = `<div class="mc-date">${dayNum}</div>`;

  const events = filterByRoot(data.events_by_day[ds] || []);
  for (const ev of events.slice(0, 3)) {
    const cc = ev.context_color || '#4B5563';
    const rc = ev.root_color || cc;
    const cls = 'mc-ev'
      + (ev.spanning && !ev.is_start ? ' cont-l' : '')
      + (ev.spanning && !ev.is_end   ? ' cont-r' : '');
    let label;
    if (ev.spanning) {
      label = ev.is_start
        ? (ev.all_day ? (ev.recurrence ? '↻ ' : '') + esc(ev.title)
                      : `<span class="mc-time">${fmtTime(ev.start_at)}</span> ${ev.recurrence ? '↻ ' : ''}${esc(ev.title)}`)
        : '&nbsp;';
    } else {
      label = `<span class="mc-time">${fmtTime(ev.start_at)}</span> ${ev.recurrence ? '↻ ' : ''}${esc(ev.title)}`;
    }
    html += `<div class="${cls}" style="background:${cc};border-left:3px solid ${rc};" title="${esc(ev.title)}">${label}</div>`;
  }
  if (events.length > 3)
    html += `<div class="mc-more">+${events.length - 3} more</div>`;

  const tasks = filterByRoot(data.tasks_by_day[ds] || []);
  if (tasks.length) {
    html += '<div class="mc-tasks">';
    for (const t of tasks.slice(0, 6))
      html += `<div class="mc-dot" style="background:${IMP_COLOR[t.importance] || IMP_COLOR.normal};" title="${esc(t.title)}"></div>`;
    if (tasks.length > 6)
      html += `<span class="mc-more">+${tasks.length - 6}</span>`;
    html += '</div>';
  }

  cell.innerHTML = html;
  if (!isOther) {
    // The cell (header/empty space) opens the day; a chip opens its event.
    cell.addEventListener('click', () => location.href = `/day?date=${ds}`);
    const shown = events.slice(0, 3);
    cell.querySelectorAll('.mc-ev').forEach((el, i) => {
      el.addEventListener('click', e => {
        e.stopPropagation();
        openEventView(shown[i], load);
      });
    });
  }
  return cell;
}
