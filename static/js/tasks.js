/**
 * tasks.js — Tasks view for planr
 */
import {
  api, initNav, initCapture,
  openTaskModal, openTaskView, renderTaskItem, toast,
  initRootFilter, filterByRoot,
} from '/static/js/shared.js?v=6';

let statusFilter = '';
let effortFilter = '';
let ctxFilter    = '';
let sortOrder    = 'priority';

document.addEventListener('DOMContentLoaded', async () => {
  initNav();
  initRootFilter(load);
  initCapture(load);

  // Populate context select
  const ctxs = await api.get('/contexts');
  const sel  = document.getElementById('ctx-filter');
  ctxs.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.id; opt.textContent = c.full_path;
    sel.appendChild(opt);
  });

  document.getElementById('status-chips').addEventListener('click', e => {
    const chip = e.target.closest('.chip'); if (!chip) return;
    statusFilter = chip.dataset.status;
    document.querySelectorAll('#status-chips .chip').forEach(c =>
      c.classList.toggle('on', c === chip));
    load();
  });
  document.getElementById('ctx-filter').onchange    = e => { ctxFilter    = e.target.value; load(); };
  document.getElementById('effort-filter').onchange = e => { effortFilter = e.target.value; load(); };
  document.getElementById('sort-select').onchange   = e => { sortOrder    = e.target.value; load(); };
  document.getElementById('btn-new').onclick        = () => openTaskModal({}, load);

  load();
});

async function load() {
  const params = {
    sort:   sortOrder,
    limit:  200,
    offset: 0,
  };
  if (statusFilter) params.status     = statusFilter;
  if (effortFilter) params.effort     = effortFilter;
  if (ctxFilter)    params.context_id = ctxFilter;

  const tasks = filterByRoot(await api.get('/tasks', params));
  render(tasks);
}

function render(tasks) {
  const list = document.getElementById('task-list');
  list.innerHTML = '';

  if (!tasks.length) {
    list.innerHTML = '<div class="empty"><span class="empty-icon">✓</span>No tasks match this filter</div>';
    return;
  }

  for (const t of tasks) {
    const el = renderTaskItem(t, onCheck, onOpen);
    list.appendChild(el);
  }
}

async function onCheck(t, el) {
  const ns = t.status === 'done' ? 'active' : 'done';
  await api.put(`/tasks/${t.uuid}`, { status: ns });
  t.status = ns;
  el.classList.toggle('done', ns === 'done');
  el.querySelector('.t-check').textContent = ns === 'done' ? '✓' : '';
  // Re-fetch after brief delay to update priority sort
  setTimeout(load, 800);
}

function onOpen(t) {
  openTaskView(t, load);
}
