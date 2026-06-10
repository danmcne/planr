/**
 * journal.js — Journal view for planr v1.1.0
 */
import {
  api, todayStr, fmtDate, esc,
  toast, initNav, initCapture, initWikiAC, debounce, renderLinksPanel,
} from '/static/js/shared.js';

const UNSAFE_RE = /[/\\:*?"<>|]/g;
let currentUUID = null, saving = false;

document.addEventListener('DOMContentLoaded', async () => {
  initNav();
  initCapture(() => {});

  const ta    = document.getElementById('editor-ta');
  const title = document.getElementById('editor-title');

  initWikiAC(ta);

  // Title sanitization hint
  const titleHint = document.createElement('div');
  titleHint.className = 'title-hint';
  title.parentNode.insertBefore(titleHint, title.nextSibling);
  title.addEventListener('input', () => {
    titleHint.textContent = UNSAFE_RE.test(title.value)
      ? '⚠ Special characters will be removed from the filename' : '';
  });

  document.getElementById('btn-new').onclick = newEntry;

  const autoSave    = debounce(saveCurrentEntry, 1200);
  const updateLinks = debounce(() =>
    renderLinksPanel(document.getElementById('links-panel'), ta.value, currentUUID), 900);

  ta.addEventListener('input',    () => { autoSave(); updateLinks(); });
  title.addEventListener('input', autoSave);

  await loadList();

  // Deep-link support: ?uuid=
  const targetUUID = new URLSearchParams(location.search).get('uuid');
  if (targetUUID) {
    const full = await api.get(`/journal/${targetUUID}`).catch(()=>null);
    if (full) { await openEntry(full); return; }
  }

  const today = await api.get('/journal/today');
  await openEntry(today);
});

async function loadList() {
  const entries = await api.get('/journal');
  const list    = document.getElementById('entry-list');
  list.innerHTML = '';
  for (const e of entries) {
    const el = document.createElement('div');
    el.className = `s-item${e.uuid === currentUUID ? ' active' : ''}`;
    el.dataset.uuid = e.uuid;
    el.innerHTML = `<div class="s-item-title">${esc(e.title || e.entry_date)}</div>
      <div class="s-item-meta">${e.entry_date}</div>`;
    el.onclick = async () => {
      if (currentUUID) await saveCurrentEntry();
      const full = await api.get(`/journal/${e.uuid}`);
      await openEntry(full);
    };
    list.appendChild(el);
  }
}

function highlightActive() {
  document.querySelectorAll('#entry-list .s-item').forEach(el =>
    el.classList.toggle('active', el.dataset.uuid === currentUUID));
}

async function openEntry(entry) {
  currentUUID = entry.uuid;
  document.getElementById('editor-title').value = entry.title || '';
  document.getElementById('editor-ta').value    = entry.content || '';
  document.getElementById('editor-date').textContent = entry.entry_date;
  document.getElementById('save-badge').textContent  = '';
  highlightActive();
  renderLinksPanel(document.getElementById('links-panel'), entry.content || '', currentUUID);
}

async function saveCurrentEntry() {
  if (!currentUUID || saving) return;
  saving = true;
  const badge = document.getElementById('save-badge');
  badge.textContent = 'Saving…';
  try {
    await api.put(`/journal/${currentUUID}`, {
      title:   document.getElementById('editor-title').value,
      content: document.getElementById('editor-ta').value,
    });
    badge.textContent = 'Saved';
    setTimeout(() => { badge.textContent = ''; }, 1500);
    loadList();
  } catch (err) {
    badge.textContent = 'Error saving';
    toast(err.message, 'err');
  } finally { saving = false; }
}

async function newEntry() {
  if (currentUUID) await saveCurrentEntry();
  const entry = await api.post('/journal', { entry_date: todayStr() });
  await loadList(); await openEntry(entry);
}
