/**
 * shared.js — planr v1.1.0 shared utilities (ES module)
 */

// ── API ───────────────────────────────────────────────────────────────────────

export const api = {
  async _req(method, path, body, params) {
    const url = new URL('/api' + path, location.origin);
    if (params) Object.entries(params).forEach(([k,v]) => {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
    });
    const opts = { method, headers: {} };
    if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    const r = await fetch(url, opts);
    if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.detail||`${method} ${path} → ${r.status}`); }
    return r.json();
  },
  get:    (path,params) => api._req('GET',   path,undefined,params),
  post:   (path,body)   => api._req('POST',  path,body),
  put:    (path,body)   => api._req('PUT',   path,body),
  delete: (path)        => api._req('DELETE',path),
  capture:(text)        => api.post('/capture',{text}),
};

// ── Date/time helpers ─────────────────────────────────────────────────────────

export const todayStr = () => new Date().toLocaleDateString('en-CA');

export function getURLParam(key, fallback) {
  return new URLSearchParams(location.search).get(key) || fallback || '';
}
export function setURLParam(key, val) {
  const p = new URLSearchParams(location.search); p.set(key, val);
  history.pushState({}, '', '?' + p);
}
export function addDays(dateStr, n) {
  const d = new Date(dateStr + 'T12:00:00'); d.setDate(d.getDate() + n);
  return d.toLocaleDateString('en-CA');
}
export function mondayOf(dateStr) {
  const d = new Date(dateStr + 'T12:00:00'); const day = d.getDay();
  d.setDate(d.getDate() - ((day+6)%7)); return d.toLocaleDateString('en-CA');
}
export function fmtDate(iso) {
  if (!iso) return ''; return new Date(iso).toLocaleDateString('en-CA');
}
export function fmtTime(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',hour12:false});
}
export function fmtDateLong(dateStr) {
  return new Date(dateStr + 'T12:00:00').toLocaleDateString('en-GB',
    {weekday:'long',year:'numeric',month:'long',day:'numeric'});
}
export function fmtWeekRange(startStr) {
  const s = new Date(startStr+'T12:00:00'), e = new Date(startStr+'T12:00:00');
  e.setDate(e.getDate()+6);
  const o = {month:'short',day:'numeric'};
  return `${s.toLocaleDateString('en-GB',o)} – ${e.toLocaleDateString('en-GB',o)}, ${s.getFullYear()}`;
}
export function fmtMonth(year, month) {
  return new Date(year, month-1, 1).toLocaleDateString('en-GB',{month:'long',year:'numeric'});
}
export function isToday(dateStr)  { return dateStr === todayStr(); }
export function isPast(iso)       { return iso && new Date(iso) < new Date(); }

// ── Toast ─────────────────────────────────────────────────────────────────────

export function toast(msg, type='ok') {
  const el = document.createElement('div');
  el.className = `toast ${type}`; el.textContent = msg;
  document.getElementById('toasts').appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => { el.classList.remove('show'); setTimeout(()=>el.remove(),300); }, 3000);
}

// ── Modal ─────────────────────────────────────────────────────────────────────

export function openModal(title, html) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-bd').innerHTML = html;
  document.getElementById('modal-overlay').classList.remove('hidden');
}
export function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
  document.getElementById('modal-bd').innerHTML = '';
}

// ── External file links in rendered markdown (delegated) ─────────────────────

document.addEventListener('click', async e => {
  const a = e.target.closest('a.xfile');
  if (!a) return;
  e.preventDefault();
  try {
    const r = await api.post('/open', {path: a.dataset.path});
    if (!r.success) toast(r.error || 'Could not open file', 'err');
  } catch (err) { toast(err.message, 'err'); }
});

// ── Nav + clock ───────────────────────────────────────────────────────────────

export function initNav() {
  const path = location.pathname;
  document.querySelectorAll('.nav-link').forEach(el => {
    if (el.getAttribute('href') === path) el.classList.add('active');
  });
  const clk = document.getElementById('topbar-clock');
  if (clk) {
    const tick = () => {
      const n = new Date();
      clk.textContent = n.toLocaleDateString('en-CA') + '  ' +
        n.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',hour12:false});
    };
    tick(); setInterval(tick, 30_000);
  }
  document.getElementById('modal-x')?.addEventListener('click', closeModal);
  document.getElementById('modal-overlay')?.addEventListener('click', e => {
    if (e.target === e.currentTarget) closeModal();
  });
}

// ── Quick capture ─────────────────────────────────────────────────────────────

export function initCapture(onSuccess) {
  const inp = document.getElementById('quick-capture');
  if (!inp) return;
  inp.addEventListener('keydown', async e => {
    if (e.key !== 'Enter' || !inp.value.trim()) return;
    try {
      const r = await api.capture(inp.value.trim());
      if (r.success) { toast(`✓  ${r.title}`); inp.value = ''; onSuccess?.(r); }
      else toast(r.error||'Capture failed','err');
    } catch (err) { toast(err.message,'err'); }
  });
  inp.addEventListener('keydown', e => { if (e.key==='Escape') inp.blur(); });
}

// ── Wiki-link autocomplete ────────────────────────────────────────────────────

export function initWikiAC(textarea) {
  if (!textarea) return;
  const drop = document.getElementById('ac-drop');
  let targets = [], activeIdx = -1, triggerStart = -1;

  textarea.addEventListener('input', async () => {
    const val = textarea.value, pos = textarea.selectionStart;
    const before = val.slice(0, pos);
    const start  = before.lastIndexOf('[[');
    if (start === -1 || before.slice(start).includes(']]')) { drop.classList.add('hidden'); return; }
    triggerStart = start;
    const query  = before.slice(start + 2);
    let typeF = '', q = query;
    const ci = query.indexOf(':');
    if (ci !== -1) { typeF = query.slice(0, ci); q = query.slice(ci+1); }
    // Show immediately when user types [[, even with no query
    try {
      targets = await api.get('/links/targets', {q, object_type: typeF, limit: 10});
    } catch { targets = []; }
    if (!targets.length && q.length > 0) { drop.classList.add('hidden'); return; }
    if (!targets.length) {
      drop.innerHTML = '<div class="ac-item" style="color:var(--t3);pointer-events:none;">Type to search…</div>';
      drop.classList.remove('hidden');
      positionDrop(textarea, drop);
      return;
    }
    drop.innerHTML = targets.map((t,i) =>
      `<div class="ac-item${i===activeIdx?' sel':''}" data-i="${i}">
         <span class="ac-type">${t.type}</span><span>${t.title}</span>
       </div>`
    ).join('');
    positionDrop(textarea, drop);
    drop.classList.remove('hidden');
    activeIdx = -1;
    drop.querySelectorAll('.ac-item').forEach(el =>
      el.addEventListener('mousedown', e => { e.preventDefault(); insertLink(+el.dataset.i); })
    );
  });

  textarea.addEventListener('keydown', e => {
    if (drop.classList.contains('hidden')) return;
    if (e.key==='ArrowDown')  { e.preventDefault(); activeIdx=Math.min(activeIdx+1,targets.length-1); hi(); }
    else if (e.key==='ArrowUp')   { e.preventDefault(); activeIdx=Math.max(activeIdx-1,0); hi(); }
    else if ((e.key==='Tab'||e.key==='Enter') && activeIdx>=0) { e.preventDefault(); insertLink(activeIdx); }
    else if (e.key==='Escape') drop.classList.add('hidden');
  });
  textarea.addEventListener('blur', () => setTimeout(()=>drop.classList.add('hidden'), 200));

  function hi() {
    drop.querySelectorAll('.ac-item').forEach((el,i) => el.classList.toggle('sel', i===activeIdx));
  }
  function insertLink(idx) {
    const t = targets[idx]; if (!t) return;
    const link = `[[${t.type}:${t.title}-${t.uuid.slice(0,8)}]]`;
    const after = textarea.value.slice(textarea.selectionStart);
    textarea.value = textarea.value.slice(0, triggerStart) + link + after;
    textarea.selectionStart = textarea.selectionEnd = triggerStart + link.length;
    drop.classList.add('hidden');
    textarea.dispatchEvent(new Event('input'));
  }
  function positionDrop(ta, d) {
    // Anchor at the text caret, not the textarea edge — in a full-page
    // editor the textarea bottom is the bottom of the screen.
    const { top, left } = _caretViewportPos(ta);
    const dropW = Math.min(320, Math.max(220, ta.clientWidth * 0.6));
    d.style.minWidth = dropW + 'px';
    let x = left, y = top + 4;
    // Keep inside the viewport
    x = Math.min(x, window.innerWidth - dropW - 12);
    d.style.left = Math.max(8, x + window.scrollX) + 'px';
    d.style.top  = (y + window.scrollY) + 'px';
    // If it would spill below the viewport, flip above the caret line
    requestAnimationFrame(() => {
      const dh = d.offsetHeight;
      if (y + dh > window.innerHeight - 8) {
        const lh = parseFloat(getComputedStyle(ta).lineHeight) || 18;
        d.style.top = Math.max(8, top - lh - dh - 2 + window.scrollY) + 'px';
      }
    });
  }
}

// ── Caret coordinates inside a textarea (mirror-div technique) ────────────────

const _MIRROR_PROPS = [
  'boxSizing','width','fontFamily','fontSize','fontWeight','fontStyle',
  'letterSpacing','lineHeight','tabSize','textIndent','textTransform',
  'wordSpacing','paddingTop','paddingRight','paddingBottom','paddingLeft',
  'borderTopWidth','borderRightWidth','borderBottomWidth','borderLeftWidth',
];

function _caretViewportPos(ta) {
  const style = getComputedStyle(ta);
  const div = document.createElement('div');
  for (const p of _MIRROR_PROPS) div.style[p] = style[p];
  div.style.position = 'absolute';
  div.style.visibility = 'hidden';
  div.style.whiteSpace = 'pre-wrap';
  div.style.overflowWrap = 'break-word';
  div.style.width = ta.clientWidth + 'px';
  div.textContent = ta.value.slice(0, ta.selectionStart);
  const marker = document.createElement('span');
  marker.textContent = '\u200b';
  div.appendChild(marker);
  document.body.appendChild(div);
  const lh = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.4;
  const inTop  = marker.offsetTop  - ta.scrollTop + lh;
  const inLeft = marker.offsetLeft - ta.scrollLeft;
  div.remove();
  const rect = ta.getBoundingClientRect();
  return { top: rect.top + inTop, left: rect.left + inLeft };
}

// ── Markdown renderer ─────────────────────────────────────────────────────────

export function renderMd(text) {
  if (!text) return '';
  let h = text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,'<em>$1</em>')
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/^### (.+)$/gm,'<h3>$1</h3>').replace(/^## (.+)$/gm,'<h2>$1</h2>').replace(/^# (.+)$/gm,'<h1>$1</h1>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/\n/g,'<br>');
  // External links first (note: < > were escaped to &lt; &gt; above)
  h = h.replace(/\[\[(web|file):([^\[\]]+?)&lt;(.+?)&gt;\]\]/g, (_, kind, title, ref) => {
    const safeRef = ref.replace(/"/g, '&quot;');
    return kind === 'web'
      ? `<a class="xlink" href="${safeRef}" target="_blank" rel="noopener">${title} ↗</a>`
      : `<a class="xlink xfile" data-path="${safeRef}" title="${safeRef}">${title} ⤴</a>`;
  });
  h = h.replace(/\[\[(?:(\w+):)?([^\]]+?)(?:-([a-f0-9]{8}))?\]\]/g,
    (_,type,title,sid) =>
      `<a class="wlink" data-type="${type||'any'}" ${sid?`data-sid="${sid}"`:''}>${title}</a>`
  );
  h = h.replace(/#(\w+)/g,'<span class="tag">#$1</span>');
  return h;
}

// ── Links panel ───────────────────────────────────────────────────────────────

export async function renderLinksPanel(el, content, sourceUuid) {
  content = content || '';

  // External links: [[web:Title<https://…>]] / [[file:Title</path/to/file>]]
  const XP = /\[\[(web|file):([^\[\]]+?)<(.+?)>\]\]/g;
  const externals = []; let m;
  while ((m = XP.exec(content)) !== null)
    externals.push({kind: m[1], title: m[2], ref: m[3]});
  content = content.replace(XP, '');

  const LP = /\[\[(?:(\w+):)?([^\]]+?)(?:-([a-f0-9]{8}))?\]\]/g;
  const links = [];
  while ((m = LP.exec(content)) !== null)
    links.push({type:m[1]||'?', title:m[2], sid:m[3]});
  const tags = [...new Set((content.match(/#(\w+)/g)||[]).map(t=>t.slice(1)))];

  let html = '';
  if (links.length || externals.length) {
    html += '<div class="lp-section"><div class="lp-label">Links</div>';
    links.forEach(lk =>
      html += `<a class="lp-chip" data-type="${lk.type}" data-sid="${lk.sid||''}" title="${esc(lk.title)}">
        <span class="lp-type">${lk.type}</span>${esc(lk.title)}</a>`
    );
    externals.forEach(x =>
      html += `<a class="lp-chip lp-ext" data-kind="${x.kind}" data-ref="${esc(x.ref)}" title="${esc(x.ref)}">
        <span class="lp-type">${x.kind}</span>${esc(x.title)} ${x.kind==='web'?'↗':'⤴'}</a>`
    );
    html += '</div>';
  }
  if (tags.length) {
    html += '<div class="lp-section"><div class="lp-label">Tags</div><div class="lp-tags">';
    tags.forEach(t => html += `<span class="lp-tag" data-tag="${esc(t)}">#${esc(t)}</span>`);
    html += '</div></div>';
  }
  if (sourceUuid) {
    try {
      const bls = await api.get('/links', {target_uuid: sourceUuid});
      if (bls.length) {
        html += '<div class="lp-section"><div class="lp-label">Backlinks</div>';
        bls.forEach(bl =>
          html += `<a class="lp-chip" data-type="${bl.source_type}" data-uuid="${bl.source_uuid}">
            <span class="lp-type">${bl.source_type}</span>← ${esc(bl.display_text||bl.source_uuid.slice(0,8))}</a>`
        );
        html += '</div>';
      }
    } catch {}
  }
  el.innerHTML = html || `<span class="lp-empty">No links or tags yet — [[Title]] links an object,
    [[web:Title&lt;https://…&gt;]] a site, [[file:Title&lt;/path&gt;]] a file, #tag tags</span>`;

  el.querySelectorAll('.lp-ext').forEach(chip => {
    chip.addEventListener('click', async () => {
      const {kind, ref} = chip.dataset;
      if (kind === 'web') {
        window.open(/^https?:\/\//.test(ref) ? ref : 'https://' + ref, '_blank', 'noopener');
      } else {
        try {
          const r = await api.post('/open', {path: ref});
          if (!r.success) toast(r.error || 'Could not open file', 'err');
        } catch (err) { toast(err.message, 'err'); }
      }
    });
  });

  el.querySelectorAll('.lp-chip:not(.lp-ext)').forEach(chip => {
    chip.addEventListener('click', async () => {
      const {type, sid, uuid} = chip.dataset;
      const id = sid || uuid;
      if (!id) return;
      try {
        const obj = sid ? await api.get(`/links/resolve/${sid}`) : {uuid: id, type};
        _navigateTo(obj.type, obj.uuid);
      } catch {}
    });
  });
  el.querySelectorAll('.lp-tag').forEach(t =>
    t.addEventListener('click', () =>
      location.href = `/search?q=${encodeURIComponent('#'+t.dataset.tag)}`)
  );
}

async function _navigateTo(type, uuid) {
  if (type==='note')    { location.href = `/notes?uuid=${uuid}`; return; }
  if (type==='journal') { location.href = `/journal?uuid=${uuid}`; return; }
  if (type==='task')    { const t = await api.get(`/tasks/${uuid}`); openTaskModal(t); return; }
  if (type==='event')   { const ev = await api.get(`/events/${uuid}`); openEventModal(ev); }
}

// ── Date / time widget helpers (module-private) ───────────────────────────────
// The visible field is a plain text input that always shows ISO YYYY-MM-DD,
// regardless of browser locale (a bare <input type="date"> renders in the
// browser's locale, e.g. mm/dd/yyyy on en-US — explicitly not wanted).
// The 📅 button opens the *native* browser calendar popup via a visually
// hidden <input type="date">; picking a date writes ISO back into the text.

const _ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function _validISO(v) {
  if (!v || !_ISO_DATE.test(v)) return null;
  const d = new Date(v + 'T12:00:00');
  return isNaN(d) ? null : v;
}

function _isoOf(iso) {
  // Local calendar date of a datetime; bare dates pass through unchanged
  // (avoid `new Date('YYYY-MM-DD')` → UTC midnight day-shift).
  if (!iso) return '';
  return /^\d{4}-\d{2}-\d{2}($|[T ])/.test(iso) ? iso.slice(0, 10) : fmtDate(iso);
}

function _dateInputHTML(id, iso) {
  return `<span class="date-field">
    <input type="text" id="${id}" class="date-text" value="${_isoOf(iso)}"
           placeholder="YYYY-MM-DD" maxlength="10" inputmode="numeric"
           autocomplete="off" spellcheck="false">
    <button type="button" class="date-btn" id="${id}-btn" tabindex="-1"
            title="Open calendar">📅</button>
    <input type="date" id="${id}-pick" class="date-hidden" tabindex="-1" aria-hidden="true">
  </span>`;
}

function _initDateField(id) {
  const txt  = document.getElementById(id);
  const pick = document.getElementById(`${id}-pick`);
  const btn  = document.getElementById(`${id}-btn`);
  if (!txt || !pick || !btn) return;
  btn.onclick = () => {
    pick.value = _validISO(txt.value.trim()) || todayStr();
    try { pick.showPicker ? pick.showPicker() : pick.focus(); }
    catch { pick.focus(); }
  };
  pick.onchange = () => {
    if (!pick.value) return;
    txt.value = pick.value;                      // ISO, always
    txt.classList.remove('bad');
    txt.dispatchEvent(new Event('change'));
  };
  txt.addEventListener('input', () => {
    const v = txt.value.trim();
    txt.classList.toggle('bad', !!v && !_validISO(v));
  });
}

function _getDateInput(id) {
  return _validISO(document.getElementById(id)?.value.trim());   // YYYY-MM-DD or null
}

function _copyDateInput(fromId, toId) {
  const to = document.getElementById(toId);
  to.value = document.getElementById(fromId).value;
  to.classList.remove('bad');
}

function _timeInputHTML(id, val) {
  let dl='';
  for (let h=0;h<24;h++) for (let mi=0;mi<60;mi+=30)
    dl += `<option value="${String(h).padStart(2,'0')}:${String(mi).padStart(2,'0')}">`;
  return `<input type="text" id="${id}" list="${id}-dl" class="time-inp"
    value="${val||''}" placeholder="HH:MM" autocomplete="off" spellcheck="false">
    <datalist id="${id}-dl">${dl}</datalist>`;
}

function _getTimePick(id) {
  const v = (document.getElementById(id)?.value||'').trim();
  const m = v.match(/^(\d{1,2}):(\d{2})$/);
  return m ? `${m[1].padStart(2,'0')}:${m[2]}` : v;
}

function _nowRoundedUp() {
  const now = new Date();
  if (now.getMinutes() === 0) return `${String(now.getHours()).padStart(2,'0')}:00`;
  return `${String((now.getHours()+1)%24).padStart(2,'0')}:00`;
}

function _addHour(t) {
  if (!t) return ''; const [h,m] = t.split(':').map(Number);
  return `${String((h+1)%24).padStart(2,'0')}:${String(m).padStart(2,'0')}`;
}

// ── Recurrence widget helpers (module-private) ────────────────────────────────

function _parseRecur(str) {
  if (!str) return {unit:'',n:1,type:'fixed'};
  const [u,n,t] = str.split(':');
  return {unit:u||'',n:parseInt(n)||1,type:t||'fixed'};
}

function _recurHTML(pfx, str, withType) {
  const {unit,n,type} = _parseRecur(str);
  const UNITS = [['','Does not repeat'],['day','Daily'],['week','Weekly'],['month','Monthly'],['year','Yearly']];
  const uOpts = UNITS.map(([v,l]) => `<option value="${v}" ${v===unit?'selected':''}>${l}</option>`).join('');
  return `<div class="fg-row" style="gap:10px;align-items:flex-end;">
    <div class="fg" style="flex:1.4;">
      <label>Repeats</label>
      <select id="${pfx}-unit">${uOpts}</select>
    </div>
    <div class="fg" id="${pfx}-n-wrap" style="${unit?'':'display:none'}">
      <label>Every</label>
      <div style="display:flex;align-items:center;gap:5px;">
        <input id="${pfx}-n" type="number" value="${n}" min="1" max="365" style="width:52px;">
        <span id="${pfx}-unit-lbl" style="font-size:11px;color:var(--t2);">${unit?unit+'(s)':''}</span>
      </div>
    </div>
    ${withType ? `<div class="fg" id="${pfx}-type-wrap" style="${unit?'':'display:none'}">
      <label>Type</label>
      <select id="${pfx}-type">
        <option value="fixed" ${type==='fixed'?'selected':''}>Fixed</option>
        <option value="moveable" ${type==='moveable'?'selected':''}>Moveable</option>
      </select>
    </div>` : ''}
  </div>`;
}

function _initRecur(pfx, withType) {
  const uEl = document.getElementById(`${pfx}-unit`);
  const nW  = document.getElementById(`${pfx}-n-wrap`);
  const tW  = withType ? document.getElementById(`${pfx}-type-wrap`) : null;
  const lbl = document.getElementById(`${pfx}-unit-lbl`);
  const tog = () => {
    const u = uEl.value;
    [nW,tW].forEach(el => el && (el.style.display = u?'':'none'));
    if (lbl) lbl.textContent = u ? u+'(s)' : '';
  };
  uEl.onchange = tog;
}

function _getRecur(pfx, withType) {
  const u = document.getElementById(`${pfx}-unit`).value;
  if (!u) return '';
  const n = document.getElementById(`${pfx}-n`).value || '1';
  if (!withType) return `${u}:${n}`;
  const t = document.getElementById(`${pfx}-type`)?.value || 'fixed';
  return `${u}:${n}:${t}`;
}

// ── Context options ───────────────────────────────────────────────────────────

export async function ctxOptions(selectedId=null, required=true) {
  const ctxs = await api.get('/contexts');
  const sel  = selectedId ?? (required ? 1 : null);
  const pre  = required ? '' : '<option value="">— no context —</option>';
  return pre + ctxs.map(c =>
    `<option value="${c.id}" ${c.id==sel?'selected':''}>${c.full_path}</option>`
  ).join('');
}

// ── Task modal ────────────────────────────────────────────────────────────────

export async function openTaskModal(task={}, onSaved, onDeleted) {
  const isEdit  = !!task.uuid;
  const ctxOpts = await ctxOptions(task.context_id, true);

  openModal(isEdit ? 'Edit task' : 'New task', `
    <div class="fg"><label>Title</label>
      <input id="f-title" value="${esc(task.title||'')}" autofocus></div>
    <div class="fg-row">
      <div class="fg"><label>Status</label>
        <select id="f-status">${['inbox','active','done','deferred','someday'].map(s =>
          `<option value="${s}" ${(task.status||'inbox')===s?'selected':''}>${cap(s)}</option>`
        ).join('')}</select></div>
      <div class="fg"><label>Importance</label>
        <select id="f-imp">${['low','normal','high','critical'].map(v =>
          `<option value="${v}" ${(task.importance||'normal')===v?'selected':''}>${cap(v)}</option>`
        ).join('')}</select></div>
    </div>
    <div class="fg-row">
      <div class="fg"><label>Effort</label>
        <select id="f-eff">${['low','medium','high'].map(v =>
          `<option value="${v}" ${(task.effort||'medium')===v?'selected':''}>${cap(v)}</option>`
        ).join('')}</select></div>
      <div class="fg"><label>Context</label>
        <select id="f-ctx">${ctxOpts}</select></div>
    </div>
    <div class="fg-row">
      <div class="fg"><label>Due date</label>
        ${_dateInputHTML('f-due', task.due_at)}</div>
      <div class="fg"><label>Location</label>
        <input id="f-loc" value="${esc(task.location||'')}"></div>
    </div>
    ${_recurHTML('f-recur', task.recurrence, true)}
    <div class="fg"><label>Description / Notes</label>
      <textarea id="f-desc" placeholder="[[Title]] to link · [[web:Title<https://…>]] · #tag">${esc(task.description||'')}</textarea></div>
    <div class="links-panel links-panel-modal" id="f-links"></div>
    <div class="form-actions">
      ${isEdit ? '<button class="btn btn-danger btn-sm" id="f-del">Delete</button>' : ''}
      <span style="flex:1"></span>
      <button class="btn btn-secondary" id="f-cancel">Cancel</button>
      <button class="btn btn-primary"   id="f-save">${isEdit?'Save':'Create'}</button>
    </div>
  `);

  initWikiAC(document.getElementById('f-desc'));
  _initRecur('f-recur', true);
  _initDateField('f-due');
  _initModalLinks('f-desc', 'f-links', task.uuid);
  document.getElementById('f-cancel').onclick = closeModal;

  if (isEdit) {
    document.getElementById('f-del').onclick = async () => {
      if (!confirm('Delete this task?')) return;
      await api.delete(`/tasks/${task.uuid}`);
      toast('Task deleted'); closeModal(); onDeleted?.();
    };
  }

  document.getElementById('f-save').onclick = async () => {
    const title = document.getElementById('f-title').value.trim();
    if (!title) { toast('Title required','err'); return; }
    const dueDate = _getDateInput('f-due');
    const payload = {
      title,
      status:      document.getElementById('f-status').value,
      importance:  document.getElementById('f-imp').value,
      effort:      document.getElementById('f-eff').value,
      context_id:  +document.getElementById('f-ctx').value || 1,
      due_at:      dueDate ? `${dueDate}T23:59:00` : null,
      location:    document.getElementById('f-loc').value,
      recurrence:  _getRecur('f-recur', true),
      description: document.getElementById('f-desc').value,
    };
    const saved = isEdit
      ? await api.put(`/tasks/${task.uuid}`, payload)
      : await api.post('/tasks', payload);
    toast(isEdit ? 'Saved' : '✓  Task created');
    closeModal(); onSaved?.(saved);
  };
}

// ── Event modal ───────────────────────────────────────────────────────────────

export async function openEventModal(event={}, onSaved, onDeleted) {
  const isEdit  = !!event.uuid;
  const ctxOpts = await ctxOptions(event.context_id, true);
  const allDay  = !!event.all_day;

  // Default start = now rounded up to next hour, end = +1h
  const defStartT = isEdit ? (event.start_at ? _getTimeStr(event.start_at) : '') : _nowRoundedUp();
  const defEndT   = isEdit ? (event.end_at   ? _getTimeStr(event.end_at)   : '') : _addHour(defStartT);
  const defStartD = isEdit ? event.start_at  : (new Date().toLocaleDateString('en-CA'));
  const defEndD   = isEdit ? event.end_at    : defStartD;

  openModal(isEdit ? 'Edit event' : 'New event', `
    <div class="fg"><label>Title</label>
      <input id="f-title" value="${esc(event.title||'')}" autofocus></div>

    <div class="fg" style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
      <input type="checkbox" id="f-allday" ${allDay?'checked':''} style="width:auto;border:none;box-shadow:none;accent-color:var(--a);">
      <label for="f-allday" style="font-size:12px;color:var(--t2);cursor:pointer;text-transform:none;letter-spacing:0;margin:0;">All day</label>
    </div>

    <div class="fg-row">
      <div class="fg">
        <label>Start</label>
        <div class="dt-row">
          ${_dateInputHTML('f-sd', defStartD)}
          <span id="f-st-wrap" style="display:flex;align-items:center;">${_timeInputHTML('f-st', defStartT)}</span>
        </div>
      </div>
      <div class="fg">
        <label>End</label>
        <div class="dt-row">
          ${_dateInputHTML('f-ed', defEndD)}
          <span id="f-et-wrap" style="display:flex;align-items:center;">${_timeInputHTML('f-et', defEndT)}</span>
        </div>
      </div>
    </div>

    <div class="fg-row">
      <div class="fg"><label>Context</label>
        <select id="f-ctx">${ctxOpts}</select></div>
      <div class="fg"><label>Location</label>
        <input id="f-loc" value="${esc(event.location||'')}"></div>
    </div>
    ${_recurHTML('f-recur', event.recurrence, false)}
    <div class="fg"><label>Description</label>
      <textarea id="f-desc" placeholder="[[Title]] to link · [[web:Title<https://…>]] · #tag">${esc(event.description||'')}</textarea></div>
    <div class="links-panel links-panel-modal" id="f-links"></div>
    <div class="form-actions">
      ${isEdit ? '<button class="btn btn-danger btn-sm" id="f-del">Delete</button>' : ''}
      <span style="flex:1"></span>
      <button class="btn btn-secondary" id="f-cancel">Cancel</button>
      <button class="btn btn-primary"   id="f-save">${isEdit?'Save':'Create'}</button>
    </div>
  `);

  initWikiAC(document.getElementById('f-desc'));
  _initRecur('f-recur', false);
  _initDateField('f-sd');
  _initDateField('f-ed');
  _initModalLinks('f-desc', 'f-links', event.uuid);

  // All-day toggle
  const alldayEl = document.getElementById('f-allday');
  const togAD = () => {
    ['f-st-wrap','f-et-wrap'].forEach(id =>
      document.getElementById(id).style.display = alldayEl.checked ? 'none' : '');
  };
  alldayEl.onchange = togAD; togAD();

  // Auto-fill end date from start date
  document.getElementById('f-sd')?.addEventListener('change', () => {
    const ed = document.getElementById('f-ed');
    if (!ed.value || ed.value < document.getElementById('f-sd').value)
      _copyDateInput('f-sd', 'f-ed');
  });

  // Auto-fill end time from start time (+1h)
  document.getElementById('f-st')?.addEventListener('input', () => {
    const st = _getTimePick('f-st');
    const et = document.getElementById('f-et');
    if (st && !et.value) et.value = _addHour(st);
    if (!_getDateInput('f-ed')) _copyDateInput('f-sd','f-ed');
  });

  document.getElementById('f-cancel').onclick = closeModal;
  if (isEdit) {
    document.getElementById('f-del').onclick = async () => {
      if (!confirm('Delete this event?')) return;
      await api.delete(`/events/${event.uuid}`);
      toast('Event deleted'); closeModal(); onDeleted?.();
    };
  }

  document.getElementById('f-save').onclick = async () => {
    const title = document.getElementById('f-title').value.trim();
    if (!title) { toast('Title required','err'); return; }

    const isAD  = document.getElementById('f-allday').checked;
    const sd = _getDateInput('f-sd'), ed = _getDateInput('f-ed');
    const st = _getTimePick('f-st'), et = _getTimePick('f-et');

    const start_at = sd ? (isAD ? `${sd}T00:00:00` : `${sd}T${st||'09:00'}:00`) : null;
    const end_at   = ed ? (isAD ? `${ed}T23:59:59` : `${ed}T${et||st||'10:00'}:00`) : null;

    if (start_at && end_at && new Date(end_at) < new Date(start_at)) {
      toast('End must be after start','err'); return;
    }

    const payload = {
      title, all_day:isAD, start_at, end_at,
      context_id: +document.getElementById('f-ctx').value || 1,
      location:   document.getElementById('f-loc').value,
      recurrence: _getRecur('f-recur', false),
      description:document.getElementById('f-desc').value,
    };
    const saved = isEdit
      ? await api.put(`/events/${event.uuid}`, payload)
      : await api.post('/events', payload);
    toast(isEdit ? 'Saved' : '✓  Event created');
    closeModal(); onSaved?.(saved);
  };
}

function _getTimeStr(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}

// ── Modal links/tags panel ────────────────────────────────────────────────────

function _initModalLinks(taId, panelId, sourceUuid) {
  const ta = document.getElementById(taId), panel = document.getElementById(panelId);
  if (!ta || !panel) return;
  const update = debounce(() => renderLinksPanel(panel, ta.value, sourceUuid || null), 600);
  renderLinksPanel(panel, ta.value, sourceUuid || null);
  ta.addEventListener('input', update);
}

// ── Render helpers ────────────────────────────────────────────────────────────

export const IMP_COLOR = {low:'#6B7280',normal:'#60A5FA',high:'#FBBF24',critical:'#F87171'};

export function renderTaskItem(t, onCheck, onOpen) {
  const done = t.status === 'done';
  const dueLabel = t.due_at
    ? `<span class="badge ${isPast(t.due_at)&&!done?'badge-over':'badge-due'}">${isPast(t.due_at)&&!done?'⚠ ':''}${fmtDate(t.due_at)}</span>` : '';
  const ctxBadge = t.context_path
    ? `<span class="badge badge-ctx">${t.context_path}</span>` : '';
  const el = document.createElement('div');
  el.className = `t-item${done?' done':''}`;
  el.dataset.uuid = t.uuid;
  el.innerHTML = `
    <div class="t-imp-bar ${t.importance||'normal'}"></div>
    <div class="t-check">${done?'✓':''}</div>
    <div class="t-body">
      <div class="t-title">${esc(t.title)}</div>
      <div class="t-meta"><span class="eff-dot ${t.effort||'medium'}"></span>${ctxBadge}${dueLabel}</div>
    </div>`;
  el.querySelector('.t-check').addEventListener('click', e => { e.stopPropagation(); onCheck?.(t,el); });
  el.addEventListener('click', () => onOpen?.(t));
  return el;
}

// ── Misc exports ──────────────────────────────────────────────────────────────

export function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

export function debounce(fn, ms) {
  let t; return (...args) => { clearTimeout(t); t = setTimeout(()=>fn(...args), ms); };
}
