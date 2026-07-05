/**
 * notes.js — Notes view for planr v1.2.0
 *
 * Sidebar lists all notes; clicking one opens it in a tab. Multiple notes
 * can be open at once; the tab bar sits above the editor. Open tabs and
 * the active tab persist in localStorage. Unsaved edits in a background
 * tab are kept in memory and autosaved when you switch back or close.
 */
import {
  api, esc, toast,
  initNav, initCapture, initWikiAC, debounce, renderLinksPanel, initRootFilter, filterByRoot,
} from '/static/js/shared.js?v=6';

const UNSAFE_RE = /[/\\:*?"<>|]/g;
const LS_KEY    = 'planr.notes.tabs';

let allNotes   = [];
let openTabs   = [];          // ordered note uuids
let activeUuid = null;
const tabState = new Map();   // uuid → {title, content, context_id, dirty}
let saving = false;

// ── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  initNav();
  initCapture(() => {});
  initRootFilter(() => renderList(allNotes));

  const ta    = document.getElementById('editor-ta');
  const title = document.getElementById('editor-title');
  const ctx   = document.getElementById('editor-ctx');

  initWikiAC(ta);

  const ctxs = await api.get('/contexts');
  ctx.innerHTML = '<option value="">— no context —</option>' +
    ctxs.map(c => `<option value="${c.id}">${esc(c.full_path)}</option>`).join('');

  document.getElementById('btn-new').onclick    = newNote;
  document.getElementById('btn-delete').onclick = deleteActive;

  // Filename-safety hint
  const titleHint = document.createElement('div');
  titleHint.className = 'title-hint';
  title.parentNode.insertBefore(titleHint, title.nextSibling);
  title.addEventListener('input', () => {
    titleHint.textContent = UNSAFE_RE.test(title.value)
      ? '⚠ Special characters will be removed from the filename' : '';
  });

  const autoSave    = debounce(saveActive, 1200);
  const updateLinks = debounce(() =>
    renderLinksPanel(document.getElementById('links-panel'), ta.value, activeUuid), 900);

  const markDirty = () => {
    const st = tabState.get(activeUuid);
    if (st) { st.title = title.value; st.content = ta.value;
              st.context_id = +ctx.value || null; st.dirty = true; }
  };
  ta.addEventListener('input',    () => { markDirty(); autoSave(); updateLinks(); });
  title.addEventListener('input', () => { markDirty(); autoSave(); renderTabs(); });
  ctx.addEventListener('change',  () => { markDirty(); autoSave(); });

  document.getElementById('note-search').addEventListener('input', e => {
    const q = e.target.value.toLowerCase();
    renderList(q ? allNotes.filter(n => n.title.toLowerCase().includes(q)) : allNotes);
  });

  await loadList();
  restoreTabs();

  // Deep link (?uuid=) takes precedence
  const target = new URLSearchParams(location.search).get('uuid');
  if (target && allNotes.some(n => n.uuid === target)) {
    await openInTab(target);
  } else if (activeUuid) {
    await activateTab(activeUuid);
  } else if (allNotes.length) {
    await openInTab(allNotes[0].uuid);
  } else {
    showEmpty();
  }
});

// ── Sidebar list ─────────────────────────────────────────────────────────────

async function loadList() {
  allNotes = await api.get('/notes');
  renderList(allNotes);
}

function renderList(notes) {
  notes = filterByRoot(notes);
  const list = document.getElementById('note-list');
  list.innerHTML = '';
  if (!notes.length) {
    list.innerHTML = '<div class="empty" style="padding:20px">No notes yet</div>';
    return;
  }
  for (const n of notes) {
    const el = document.createElement('div');
    el.className = `s-item${n.uuid === activeUuid ? ' active' : ''}`;
    el.dataset.uuid = n.uuid;
    el.innerHTML = `<div class="s-item-title">${esc(n.title)}</div>
      <div class="s-item-meta">${n.modified_at?.slice(0,10) || ''}</div>`;
    el.onclick = () => openInTab(n.uuid);
    list.appendChild(el);
  }
}

function highlightActive() {
  document.querySelectorAll('#note-list .s-item').forEach(el =>
    el.classList.toggle('active', el.dataset.uuid === activeUuid));
}

// ── Tabs ─────────────────────────────────────────────────────────────────────

function persistTabs() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({ open: openTabs, active: activeUuid }));
  } catch { /* storage unavailable — tabs simply won't persist */ }
}

function restoreTabs() {
  try {
    const saved = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
    const valid = new Set(allNotes.map(n => n.uuid));
    openTabs   = (saved.open || []).filter(u => valid.has(u));
    activeUuid = valid.has(saved.active) ? saved.active : (openTabs[0] || null);
  } catch { openTabs = []; activeUuid = null; }
}

function tabTitle(uuid) {
  const st = tabState.get(uuid);
  if (st?.title) return st.title;
  return allNotes.find(n => n.uuid === uuid)?.title || 'Untitled';
}

function renderTabs() {
  const bar = document.getElementById('note-tabs');
  bar.innerHTML = '';
  for (const uuid of openTabs) {
    const t = document.createElement('div');
    t.className = `note-tab${uuid === activeUuid ? ' on' : ''}`;
    t.innerHTML = `<span class="note-tab-title">${esc(tabTitle(uuid))}</span>
      <span class="note-tab-x" title="Close">✕</span>`;
    t.querySelector('.note-tab-title').onclick = () => activateTab(uuid);
    t.querySelector('.note-tab-x').onclick = e => { e.stopPropagation(); closeTab(uuid); };
    bar.appendChild(t);
  }
}

async function openInTab(uuid) {
  if (!openTabs.includes(uuid)) openTabs.push(uuid);
  await activateTab(uuid);
}

async function activateTab(uuid) {
  if (activeUuid && activeUuid !== uuid) await saveActive();   // flush edits

  activeUuid = uuid;
  if (!tabState.has(uuid)) {
    try {
      const n = await api.get(`/notes/${uuid}`);
      tabState.set(uuid, { title: n.title || '', content: n.content || '',
                           context_id: n.context_id || null, dirty: false });
    } catch (err) {
      toast(err.message, 'err');
      closeTab(uuid);
      return;
    }
  }
  const st = tabState.get(uuid);
  document.getElementById('editor-title').value = st.title;
  document.getElementById('editor-ta').value    = st.content;
  document.getElementById('editor-ctx').value   = st.context_id || '';
  document.getElementById('save-badge').textContent = '';
  document.getElementById('editor-panel').classList.remove('editor-empty');

  renderTabs(); highlightActive(); persistTabs();
  renderLinksPanel(document.getElementById('links-panel'), st.content, uuid);
}

async function closeTab(uuid) {
  const st = tabState.get(uuid);
  if (st?.dirty && uuid === activeUuid) await saveActive();
  else if (st?.dirty) await saveNote(uuid);

  openTabs = openTabs.filter(u => u !== uuid);
  tabState.delete(uuid);

  if (activeUuid === uuid) {
    activeUuid = openTabs[openTabs.length - 1] || null;
    if (activeUuid) await activateTab(activeUuid);
    else showEmpty();
  }
  renderTabs(); highlightActive(); persistTabs();
}

function showEmpty() {
  document.getElementById('editor-title').value = '';
  document.getElementById('editor-ta').value    = '';
  document.getElementById('editor-ctx').value   = '';
  document.getElementById('links-panel').innerHTML = '';
  document.getElementById('editor-panel').classList.add('editor-empty');
  renderTabs();
}

// ── Save / create / delete ───────────────────────────────────────────────────

async function saveNote(uuid) {
  const st = tabState.get(uuid);
  if (!st || !st.dirty) return;
  await api.put(`/notes/${uuid}`, {
    title: st.title, content: st.content, context_id: st.context_id,
  });
  st.dirty = false;
}

async function saveActive() {
  if (!activeUuid || saving) return;
  const st = tabState.get(activeUuid);
  if (!st?.dirty) return;
  saving = true;
  const badge = document.getElementById('save-badge');
  badge.textContent = 'Saving…';
  try {
    await saveNote(activeUuid);
    badge.textContent = 'Saved';
    setTimeout(() => { if (badge.textContent === 'Saved') badge.textContent = ''; }, 1500);
    await loadList(); highlightActive(); renderTabs();
  } catch (err) {
    badge.textContent = 'Error';
    toast(err.message, 'err');
  } finally { saving = false; }
}

async function newNote() {
  await saveActive();
  const note = await api.post('/notes', { title: 'Untitled note' });
  await loadList();
  await openInTab(note.uuid);
  document.getElementById('editor-title').select();
}

async function deleteActive() {
  if (!activeUuid) return;
  if (!confirm('Delete this note? The file will also be removed.')) return;
  const uuid = activeUuid;
  tabState.delete(uuid);                       // discard edits — don't resave
  openTabs = openTabs.filter(u => u !== uuid);
  await api.delete(`/notes/${uuid}`);
  toast('Note deleted');
  activeUuid = null;
  await loadList();
  persistTabs();
  if (openTabs.length) await activateTab(openTabs[openTabs.length - 1]);
  else if (allNotes.length) await openInTab(allNotes[0].uuid);
  else showEmpty();
}
