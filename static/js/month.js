/**
 * month.js — Month view for planr v1.2.1
 *
 * Grid is built by walking forward from the Monday on/before the 1st, so
 * adjacent-month cells always carry the correct date (the old version
 * broke on January/December and had a duplicate-declaration SyntaxError).
 */
import {
  api, todayStr, getURLParam, setURLParam,
  fmtMonth, fmtTime, esc,
  initNav, initCapture, IMP_COLOR,
} from '/static/js/shared.js';
import { initViewKeys } from '/static/js/cal-common.js';

let year  = 0;
let month = 0;

document.addEventListener('DOMContentLoaded', () => {
  initNav();
  initCapture(load);
  initViewKeys(() => `${year}-${String(month).padStart(2,'0')}-01`);

  const ref = new Date(getURLParam('date', todayStr()) + 'T12:00:00');
  year  = ref.getFullYear();
  month = ref.getMonth() + 1;

  document.getElementById('btn-prev').onclick  = () => navigate(-1);
  document.getElementById('btn-next').onclick  = () => navigate(1);
  document.getElementById('btn-today').onclick = () => {
    const n = new Date();
    year = n.getFullYear(); month = n.getMonth() + 1;
    sync(); load();
  };

  load();
});

function navigate(delta) {
  month += delta;
  if (month > 12) { month = 1;  year++; }
  if (month < 1)  { month = 12; year--; }
  sync(); load();
}
function sync() {
  setURLParam('date', `${year}-${String(month).padStart(2,'0')}-01`);
}

async function load() {
  document.getElementById('month-label').textContent = fmtMonth(year, month);
  const data = await api.get('/calendar/month', { year, month });

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

  const events = data.events_by_day[ds] || [];
  for (const ev of events.slice(0, 3)) {
    const c = ev.context_color || '#4B5563';
    const cls = 'mc-ev'
      + (ev.spanning && !ev.is_start ? ' cont-l' : '')
      + (ev.spanning && !ev.is_end   ? ' cont-r' : '');
    let label;
    if (ev.spanning) {
      label = ev.is_start
        ? (ev.all_day ? esc(ev.title)
                      : `<span class="mc-time">${fmtTime(ev.start_at)}</span> ${esc(ev.title)}`)
        : '&nbsp;';
    } else {
      label = `<span class="mc-time">${fmtTime(ev.start_at)}</span> ${esc(ev.title)}`;
    }
    html += `<div class="${cls}" style="background:${c};" title="${esc(ev.title)}">${label}</div>`;
  }
  if (events.length > 3)
    html += `<div class="mc-more">+${events.length - 3} more</div>`;

  const tasks = data.tasks_by_day[ds] || [];
  if (tasks.length) {
    html += '<div class="mc-tasks">';
    for (const t of tasks.slice(0, 6))
      html += `<div class="mc-dot" style="background:${IMP_COLOR[t.importance] || IMP_COLOR.normal};" title="${esc(t.title)}"></div>`;
    if (tasks.length > 6)
      html += `<span class="mc-more">+${tasks.length - 6}</span>`;
    html += '</div>';
  }

  cell.innerHTML = html;
  if (!isOther) cell.addEventListener('click', () => location.href = `/day?date=${ds}`);
  return cell;
}
