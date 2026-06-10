/**
 * review.js — GTD-style review flow for planr
 */
import {
  api, todayStr, addDays, fmtDate, esc,
  toast, initNav, initCapture,
  openTaskModal, openEventModal, renderTaskItem,
} from '/static/js/shared.js';

const STEPS = [
  { id: 'inbox',    label: '① Inbox',    sub: 'Process every inbox item: assign a context, set status, or delete.' },
  { id: 'stalled',  label: '② Stalled',  sub: 'Active tasks with no activity in 7+ days. Defer, delegate, or delete.' },
  { id: 'someday',  label: '③ Someday',  sub: 'Review someday items. Promote to active or drop if no longer relevant.' },
  { id: 'upcoming', label: '④ Upcoming', sub: 'Events and deadlines in the next 14 days.' },
  { id: 'done',     label: '⑤ Done',     sub: 'Tasks completed since the last review. Celebrate wins.' },
];

let currentStep = 0;
const done      = new Set();

document.addEventListener('DOMContentLoaded', () => {
  initNav();
  initCapture(() => loadStep());

  document.getElementById('btn-next-step').onclick = () => { if (currentStep < 4) goStep(currentStep + 1); };
  document.getElementById('btn-prev-step').onclick = () => { if (currentStep > 0) goStep(currentStep - 1); };

  document.getElementById('review-steps').addEventListener('click', e => {
    const tab = e.target.closest('.review-step');
    if (tab) goStep(+tab.dataset.step);
  });

  goStep(0);
});

function goStep(idx) {
  done.add(currentStep);
  currentStep = idx;
  updateTabs();
  loadStep();
}

function updateTabs() {
  document.querySelectorAll('.review-step').forEach((el, i) => {
    el.classList.toggle('active', i === currentStep);
    el.classList.toggle('done',   done.has(i) && i !== currentStep);
  });
  document.getElementById('step-counter').textContent = `Step ${currentStep+1} of ${STEPS.length}`;
  document.getElementById('btn-prev-step').disabled = currentStep === 0;
  document.getElementById('btn-next-step').disabled = currentStep === STEPS.length - 1;
}

async function loadStep() {
  const content = document.getElementById('review-content');
  content.innerHTML = `<div class="empty"><div class="spinner" style="width:18px;height:18px;border-width:2px;"></div></div>`;

  const step = STEPS[currentStep];
  let items  = [];

  if (step.id === 'inbox') {
    items = await api.get('/tasks', { status: 'inbox', limit: 100 });
  } else if (step.id === 'stalled') {
    const all = await api.get('/tasks', { status: 'active', limit: 200 });
    const cutoff = addDays(todayStr(), -7);
    items = all.filter(t => {
      const ref = t.last_active_at || t.modified_at || t.created_at;
      return ref < cutoff;
    });
  } else if (step.id === 'someday') {
    items = await api.get('/tasks', { status: 'someday', limit: 100 });
  } else if (step.id === 'upcoming') {
    await renderUpcoming(content, step); return;
  } else if (step.id === 'done') {
    items = await api.get('/tasks', { status: 'done', limit: 50 });
  }

  renderTasks(content, step, items);
}

function renderTasks(content, step, tasks) {
  let html = `
    <div class="review-section-title">${step.label}</div>
    <div class="review-section-sub">${step.sub}</div>
  `;
  if (!tasks.length) {
    html += '<div class="empty"><span class="empty-icon">✓</span>Nothing here — all clear!</div>';
    content.innerHTML = html;
    return;
  }
  content.innerHTML = html;

  const list = document.createElement('div');
  for (const t of tasks) {
    const el = renderTaskItem(t, onCheck, onOpen);
    // Add quick-action buttons for this step
    const actions = document.createElement('div');
    actions.style.cssText = 'display:flex;gap:4px;padding:0 14px 6px;';
    if (step.id === 'inbox') {
      actions.innerHTML = `
        <button class="btn btn-secondary btn-sm" data-act="activate">Activate</button>
        <button class="btn btn-secondary btn-sm" data-act="someday">Someday</button>
        <button class="btn btn-danger    btn-sm" data-act="delete">Delete</button>
      `;
    } else if (step.id === 'stalled') {
      actions.innerHTML = `
        <button class="btn btn-secondary btn-sm" data-act="defer">Defer 7d</button>
        <button class="btn btn-secondary btn-sm" data-act="someday">Someday</button>
        <button class="btn btn-danger    btn-sm" data-act="delete">Delete</button>
      `;
    } else if (step.id === 'someday') {
      actions.innerHTML = `
        <button class="btn btn-primary   btn-sm" data-act="activate">Activate</button>
        <button class="btn btn-danger    btn-sm" data-act="delete">Delete</button>
      `;
    }
    actions.addEventListener('click', async e => {
      const btn = e.target.closest('[data-act]'); if (!btn) return;
      const act = btn.dataset.act;
      try {
        if (act === 'activate') await api.put(`/tasks/${t.uuid}`, { status: 'active' });
        else if (act === 'someday') await api.put(`/tasks/${t.uuid}`, { status: 'someday' });
        else if (act === 'defer') {
          const dt = addDays(todayStr(), 7);
          await api.put(`/tasks/${t.uuid}`, { status: 'deferred', deferred_until: dt });
        } else if (act === 'delete') {
          if (!confirm('Delete task?')) return;
          await api.delete(`/tasks/${t.uuid}`);
        }
        toast('Updated');
        // Remove from list
        el.remove(); actions.remove();
      } catch (err) { toast(err.message, 'err'); }
    });
    list.appendChild(el);
    list.appendChild(actions);
  }
  content.appendChild(list);
}

async function renderUpcoming(content, step) {
  const end    = addDays(todayStr(), 14);
  const events = await api.get('/events', { start: todayStr(), end });
  const tasks  = await api.get('/tasks',  { limit: 200 });
  const dueSoon = tasks.filter(t => t.due_at && t.due_at.slice(0,10) <= end && t.status !== 'done');

  let html = `
    <div class="review-section-title">${step.label}</div>
    <div class="review-section-sub">${step.sub}</div>
  `;
  if (!events.length && !dueSoon.length) {
    html += '<div class="empty"><span class="empty-icon">🗓</span>Nothing coming up in 14 days</div>';
    content.innerHTML = html;
    return;
  }
  content.innerHTML = html;

  if (events.length) {
    const sec = document.createElement('div');
    sec.innerHTML = '<div class="section-label">Events</div>';
    for (const ev of events) {
      const row = document.createElement('div');
      row.className = 't-item';
      row.style.cursor = 'pointer';
      row.innerHTML = `
        <div class="t-body">
          <div class="t-title">${esc(ev.title)}</div>
          <div class="t-meta"><span class="badge badge-due">${fmtDate(ev.start_at)}</span></div>
        </div>
      `;
      row.onclick = () => openEventModal(ev, () => loadStep(), () => loadStep());
      sec.appendChild(row);
    }
    content.appendChild(sec);
  }

  if (dueSoon.length) {
    const sec = document.createElement('div');
    sec.innerHTML = '<div class="section-label">Task deadlines</div>';
    for (const t of dueSoon) {
      const el = renderTaskItem(t, onCheck, onOpen);
      sec.appendChild(el);
    }
    content.appendChild(sec);
  }
}

async function onCheck(t, el) {
  const ns = t.status === 'done' ? 'active' : 'done';
  await api.put(`/tasks/${t.uuid}`, { status: ns });
  t.status = ns;
  el.classList.toggle('done', ns === 'done');
  el.querySelector('.t-check').textContent = ns === 'done' ? '✓' : '';
}
function onOpen(t) { openTaskModal(t, () => loadStep(), () => loadStep()); }
