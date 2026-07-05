/**
 * contexts.js — Contexts management view for planr
 */
import { api, esc, toast, openModal, closeModal, initNav, initCapture } from '/static/js/shared.js?v=6';

const PRESETS = [
  '#6B7280','#EF4444','#F97316','#EAB308',
  '#22C55E','#14B8A6','#3B82F6','#8B5CF6',
  '#EC4899','#10B981','#F59E0B','#60A5FA',
];

let contexts = [];

document.addEventListener('DOMContentLoaded', () => {
  initNav();
  initCapture(() => {});
  document.getElementById('btn-add').onclick = () => openContextModal();
  load();
});

// ── Data ──────────────────────────────────────────────────────────────────────

async function load() {
  contexts = await api.get('/contexts');
  render();
}

// ── Tree rendering ────────────────────────────────────────────────────────────

function buildTree() {
  const map = {};
  for (const c of contexts) map[c.id] = { ...c, children: [] };
  const roots = [];
  for (const c of contexts) {
    if (c.parent_id && map[c.parent_id]) map[c.parent_id].children.push(map[c.id]);
    else roots.push(map[c.id]);
  }
  // Sort siblings by sort_order, then name
  const byOrder = (a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.name.localeCompare(b.name);
  roots.sort(byOrder);
  for (const node of Object.values(map)) node.children.sort(byOrder);
  return roots;
}

function render() {
  const tree = buildTree();
  const el   = document.getElementById('ctx-tree');
  el.innerHTML = '';
  if (!contexts.length) {
    el.innerHTML = '<div class="empty">No contexts yet</div>';
    return;
  }
  renderNodes(el, tree, 0);
}

function renderNodes(container, nodes, depth) {
  for (const node of nodes) {
    container.appendChild(makeRow(node, depth));
    if (node.children.length) renderNodes(container, node.children, depth + 1);
  }
}

function makeRow(node, depth) {
  const row = document.createElement('div');
  row.className = 'ctx-row';
  row.dataset.id = node.id;

  // Indentation via a spacer element
  if (depth > 0) {
    const indent = document.createElement('span');
    indent.style.cssText = `display:inline-block;width:${depth * 20}px;flex-shrink:0;`;
    row.appendChild(indent);
    // Tree connector
    const conn = document.createElement('span');
    conn.style.cssText = 'color:var(--t3);margin-right:4px;font-size:12px;flex-shrink:0;';
    conn.textContent = '└─';
    row.appendChild(conn);
  }

  const swatch = document.createElement('div');
  swatch.className = 'ctx-swatch';
  swatch.style.background = node.color || '#6B7280';

  const name = document.createElement('span');
  name.className = 'ctx-name';
  name.textContent = node.name;

  const path = document.createElement('span');
  path.className = 'ctx-path';
  path.textContent = depth > 0 ? node.full_path : '';

  const spacer = document.createElement('span');
  spacer.className = 'ctx-spacer';

  // Count items using this context
  const acts = document.createElement('div');
  acts.className = 'ctx-acts';

  const btnUp   = makeActBtn('↑',    'Move up',        () => moveCtx(node.id, 'up'));
  const btnDown = makeActBtn('↓',    'Move down',      () => moveCtx(node.id, 'down'));
  const btnEdit = makeActBtn('Edit', 'Edit',            () => openContextModal(node));
  const btnSub  = makeActBtn('+ Sub','Add subcontext',  () => openContextModal({}, node.id));
  const btnDel  = makeActBtn('Del',  'Delete',          () => deleteCtx(node));
  btnDel.classList.add('btn-danger');

  acts.append(btnUp, btnDown, btnEdit, btnSub, btnDel);
  row.append(swatch, name, path, spacer, acts);
  return row;
}

function makeActBtn(label, title, onClick) {
  const btn = document.createElement('button');
  btn.className = 'btn btn-ghost btn-sm';
  btn.textContent = label;
  btn.title = title;
  btn.onclick = onClick;
  return btn;
}

// ── Move (reorder within siblings) ───────────────────────────────────────────

async function moveCtx(id, direction) {
  const ctx      = contexts.find(c => c.id === id);
  const siblings = contexts
    .filter(c => (c.parent_id || null) === (ctx.parent_id || null))
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.name.localeCompare(b.name));

  const idx    = siblings.findIndex(c => c.id === id);
  const newIdx = direction === 'up' ? idx - 1 : idx + 1;
  if (newIdx < 0 || newIdx >= siblings.length) return;

  // Reassign sort_order for all siblings
  const reordered = [...siblings];
  const [moved]   = reordered.splice(idx, 1);
  reordered.splice(newIdx, 0, moved);

  await Promise.all(
    reordered.map((c, i) => api.put(`/contexts/${c.id}`, { sort_order: i }))
  );
  await load();
}

// ── Delete ────────────────────────────────────────────────────────────────────

async function deleteCtx(node) {
  const hasChildren = contexts.some(c => c.parent_id === node.id);
  if (hasChildren) {
    toast('Remove all subcontexts first', 'err'); return;
  }
  if (!confirm(`Delete context "${node.full_path}"?\nAll objects using it will lose their context assignment.`)) return;
  try {
    await api.delete(`/contexts/${node.id}`);
    toast(`Deleted: ${node.full_path}`);
    await load();
  } catch (err) {
    toast(err.message, 'err');
  }
}

// ── Add / Edit modal ──────────────────────────────────────────────────────────

function openContextModal(ctx = {}, defaultParentId = null) {
  const isEdit    = !!ctx.id;
  const parentId  = ctx.parent_id ?? defaultParentId;

  // Build parent options (exclude self and descendants)
  const parentOpts = contexts
    .filter(c => !isEdit || (c.id !== ctx.id && !c.full_path.startsWith(ctx.full_path + '.')))
    .map(c => `<option value="${c.id}" ${c.id == parentId ? 'selected' : ''}>${c.full_path}</option>`)
    .join('');

  const currentColor = ctx.color || '#6B7280';

  openModal(isEdit ? 'Edit context' : 'New context', `
    <div class="fg">
      <label>Name</label>
      <input id="f-name" value="${esc(ctx.name||'')}" autofocus placeholder="e.g. project, hobby…">
    </div>
    <div class="fg">
      <label>Parent (optional)</label>
      <select id="f-parent">
        <option value="">— root level —</option>
        ${parentOpts}
      </select>
    </div>
    <div class="fg">
      <label>Colour</label>
      <div class="color-presets">
        ${PRESETS.map(c =>
          `<div class="cp-dot${c === currentColor ? ' sel' : ''}" data-c="${c}"
               style="background:${c};" title="${c}"></div>`
        ).join('')}
      </div>
      <div style="display:flex;align-items:center;gap:8px;margin-top:4px;">
        <input type="color" id="f-color" value="${currentColor}"
               style="width:36px;height:28px;padding:1px;cursor:pointer;border-radius:3px;">
        <span id="f-color-hex" style="font-family:var(--ff-mono);font-size:11px;color:var(--t2);">${currentColor}</span>
      </div>
    </div>
    <div class="form-actions">
      ${isEdit && ctx.id > 4 ? '<button class="btn btn-danger btn-sm" id="f-del">Delete</button>' : ''}
      <span style="flex:1"></span>
      <button class="btn btn-secondary" id="f-cancel">Cancel</button>
      <button class="btn btn-primary"   id="f-save">${isEdit ? 'Save changes' : 'Create'}</button>
    </div>
  `);

  // Colour preset clicks
  document.querySelectorAll('.cp-dot').forEach(dot => {
    dot.addEventListener('click', () => {
      document.getElementById('f-color').value = dot.dataset.c;
      document.getElementById('f-color-hex').textContent = dot.dataset.c;
      document.querySelectorAll('.cp-dot').forEach(d =>
        d.classList.toggle('sel', d === dot));
    });
  });

  // Native colour picker sync
  document.getElementById('f-color').addEventListener('input', e => {
    const v = e.target.value;
    document.getElementById('f-color-hex').textContent = v;
    document.querySelectorAll('.cp-dot').forEach(d =>
      d.classList.toggle('sel', d.dataset.c === v));
  });

  document.getElementById('f-cancel').onclick = closeModal;

  if (document.getElementById('f-del')) {
    document.getElementById('f-del').onclick = async () => {
      closeModal(); await deleteCtx(ctx);
    };
  }

  document.getElementById('f-save').onclick = async () => {
    const name = document.getElementById('f-name').value.trim();
    if (!name) { toast('Name required', 'err'); return; }
    const parent_id = +document.getElementById('f-parent').value || null;
    const color     = document.getElementById('f-color').value;

    try {
      if (isEdit) {
        await api.put(`/contexts/${ctx.id}`, { name, color });
      } else {
        await api.post('/contexts', { name, parent_id, color });
      }
      toast(isEdit ? 'Context updated' : '✓  Context created');
      closeModal();
      await load();
    } catch (err) {
      toast(err.message, 'err');
    }
  };
}
