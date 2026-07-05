/**
 * search.js — Search view for planr v1.1.0
 */
import {
  api, fmtDate, esc, debounce,
  toast, initNav, initCapture,
  openTaskModal, openEventModal,
} from '/static/js/shared.js?v=6';

let typeFilter = '', ctxFilter = '', statusFilter = '';

document.addEventListener('DOMContentLoaded', async () => {
  initNav();
  initCapture(() => {});

  // Populate context filter
  const ctxs = await api.get('/contexts');
  const ctxSel = document.getElementById('ctx-filter');
  ctxs.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.id; opt.textContent = c.full_path;
    ctxSel.appendChild(opt);
  });

  const inp = document.getElementById('search-inp');

  document.getElementById('type-chips').addEventListener('click', e => {
    const chip = e.target.closest('.chip'); if (!chip) return;
    typeFilter = chip.dataset.type;
    document.querySelectorAll('#type-chips .chip').forEach(c =>
      c.classList.toggle('on', c === chip));
    doSearch(inp.value.trim());
  });

  ctxSel.onchange             = e => { ctxFilter    = e.target.value; doSearch(inp.value.trim()); };
  document.getElementById('status-filter').onchange = e => { statusFilter = e.target.value; doSearch(inp.value.trim()); };
  document.getElementById('date-from').onchange     = () => doSearch(inp.value.trim());
  document.getElementById('date-to').onchange       = () => doSearch(inp.value.trim());

  const doSearchDebounced = debounce(q => doSearch(q), 300);
  inp.addEventListener('input', e => doSearchDebounced(e.target.value.trim()));

  // Pre-fill from URL ?q=
  const urlQ = new URLSearchParams(location.search).get('q') || '';
  if (urlQ) { inp.value = urlQ; doSearch(urlQ); }

  inp.focus();
});

async function doSearch(q) {
  const results = document.getElementById('results');
  const count   = document.getElementById('result-count');
  const dateFrom = document.getElementById('date-from').value;
  const dateTo   = document.getElementById('date-to').value;

  const params = { q, obj_type: typeFilter };
  if (ctxFilter)    params.context_id = ctxFilter;
  if (statusFilter) params.status     = statusFilter;
  if (dateFrom)     params.date_from  = dateFrom;
  if (dateTo)       params.date_to    = dateTo;

  if (!q && !ctxFilter && !statusFilter && !dateFrom && !dateTo) {
    results.innerHTML = '<div class="empty"><span class="empty-icon">🔍</span>Start typing, or use the filters above</div>';
    count.textContent = '';
    return;
  }

  try {
    const hits = await api.get('/search', params);
    count.textContent = `${hits.length} result${hits.length !== 1 ? 's' : ''}`;
    renderResults(hits);
  } catch (err) {
    results.innerHTML = `<div class="empty">Error: ${esc(err.message)}</div>`;
  }
}

function renderResults(hits) {
  const results = document.getElementById('results');
  if (!hits.length) {
    results.innerHTML = '<div class="empty"><span class="empty-icon">∅</span>No results</div>';
    return;
  }
  results.innerHTML = '';
  for (const h of hits) {
    const el = document.createElement('div');
    el.className = 'sr';
    const meta = buildMeta(h);
    el.innerHTML = `
      <div class="sr-title">
        <span class="badge badge-ctx" style="margin-right:6px;">${h.type}</span>${esc(h.title)}
      </div>
      ${h.snippet ? `<div class="sr-snip">${h.snippet}</div>` : ''}
      <div class="sr-meta">${meta}</div>
    `;
    el.addEventListener('click', () => openResult(h));
    results.appendChild(el);
  }
}

function buildMeta(h) {
  const parts = [];
  if (h.type === 'task') {
    if (h.status)    parts.push(`<span class="badge badge-st ${h.status}">${h.status}</span>`);
    if (h.due_at)    parts.push(fmtDate(h.due_at));
    if (h.importance && h.importance !== 'normal') parts.push(h.importance);
  } else if (h.type === 'event') {
    if (h.start_at) parts.push(fmtDate(h.start_at));
  } else if (h.type === 'note') {
    if (h.modified_at) parts.push(`edited ${fmtDate(h.modified_at)}`);
  } else if (h.type === 'journal') {
    if (h.entry_date) parts.push(h.entry_date);
  }
  return parts.join(' · ');
}

async function openResult(h) {
  if (h.type === 'task') {
    const t = await api.get(`/tasks/${h.uuid}`);
    openTaskModal(t, () => {}, () => {});
  } else if (h.type === 'event') {
    const ev = await api.get(`/events/${h.uuid}`);
    openEventModal(ev, () => {}, () => {});
  } else if (h.type === 'note') {
    location.href = `/notes?uuid=${h.uuid}`;
  } else if (h.type === 'journal') {
    location.href = `/journal?uuid=${h.uuid}`;
  }
}
