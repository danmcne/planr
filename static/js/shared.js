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

// ── Root-context filter (top bar) ─────────────────────────────────────────────
// Toggleable chips for each root context (work, personal, …). The selection
// persists in localStorage and applies across all views. Empty selection =
// show everything. While a filter is active, items without a context are
// hidden (use the inbox/uncategorized chips to see unsorted items).

const _RF_KEY = 'planr.rootFilter';
let _rfSelected = new Set();
try { _rfSelected = new Set(JSON.parse(localStorage.getItem(_RF_KEY) || '[]')); } catch {}

export function rootFilterActive() { return _rfSelected.size > 0; }

/** True if an item with this context_path passes the current filter. */
export function rootFilterPass(contextPath) {
  if (!_rfSelected.size) return true;
  if (!contextPath) return false;
  return _rfSelected.has(String(contextPath).split('.')[0]);
}

export function filterByRoot(items, pathKey = 'context_path') {
  if (!_rfSelected.size) return items;
  return (items || []).filter(it => rootFilterPass(it[pathKey]));
}

/** Render the chips into #root-filter; call onChange on every toggle. */
export async function initRootFilter(onChange) {
  const host = document.getElementById('root-filter');
  if (!host) return;
  let roots = [];
  try {
    const ctxs = await api.get('/contexts');
    roots = ctxs.filter(c => !c.full_path.includes('.'));
  } catch { return; }

  // Drop selections for roots that no longer exist
  const names = new Set(roots.map(r => r.full_path));
  let changed = false;
  for (const sel of [..._rfSelected])
    if (!names.has(sel)) { _rfSelected.delete(sel); changed = true; }
  if (changed) localStorage.setItem(_RF_KEY, JSON.stringify([..._rfSelected]));

  const render = () => {
    host.innerHTML = '';
    const all = document.createElement('span');
    all.className = `rf-chip${_rfSelected.size ? '' : ' on'}`;
    all.textContent = 'All';
    all.onclick = () => {
      _rfSelected.clear();
      localStorage.setItem(_RF_KEY, '[]');
      render(); onChange?.();
    };
    host.appendChild(all);

    for (const r of roots) {
      const chip = document.createElement('span');
      const on = _rfSelected.has(r.full_path);
      chip.className = `rf-chip${on ? ' on' : ''}`;
      const col = r.color || '#4B5563';
      chip.innerHTML = `<span class="rf-dot" style="background:${col}"></span>${esc(r.full_path)}`;
      if (on) chip.style.borderColor = col;
      chip.onclick = () => {
        if (_rfSelected.has(r.full_path)) _rfSelected.delete(r.full_path);
        else _rfSelected.add(r.full_path);
        localStorage.setItem(_RF_KEY, JSON.stringify([..._rfSelected]));
        render(); onChange?.();
      };
      host.appendChild(chip);
    }
  };
  render();
}

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
//
// Two storage formats:
//   Tasks  (withType=true)  — legacy compact "unit:n:type"   (unchanged)
//   Events (withType=false) — RFC 5545 RRULE text, e.g.
//       FREQ=WEEKLY;INTERVAL=2 · FREQ=MONTHLY;BYDAY=2TU ·
//       FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
//   Legacy "unit:n" values on old events are still parsed for prefill
//   (and expanded by the backend), and are upgraded to RRULE on next save.

const _WD      = ['SU','MO','TU','WE','TH','FR','SA'];
const _WD_NAME = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
const _ORD     = ['first','second','third','fourth','fifth'];
const _FREQ2UNIT = {DAILY:'day', WEEKLY:'week', MONTHLY:'month', YEARLY:'year'};
const _UNIT2FREQ = {day:'DAILY', week:'WEEKLY', month:'MONTHLY', year:'YEARLY'};

// → {unit, n, type, on}   on ∈ 'md' (day-of-month) | 'nth' | 'last'
function _parseRecur(str) {
  if (!str) return {unit:'', n:1, type:'fixed', on:'md', days:[]};
  if (str.toUpperCase().includes('FREQ=')) {
    const p = {};
    str.replace(/^RRULE:/i,'').split(';').forEach(kv => {
      const [k,v] = kv.split('='); if (k) p[k.trim().toUpperCase()] = (v||'').trim();
    });
    const unit = _FREQ2UNIT[(p.FREQ||'').toUpperCase()] || '';
    const on   = p.BYDAY ? (p.BYDAY.startsWith('-') ? 'last' : 'nth') : 'md';
    const days = (unit === 'week' && p.BYDAY) ? p.BYDAY.split(',') : [];
    return {unit, n: parseInt(p.INTERVAL)||1, type:'fixed', on, days};
  }
  const [u,n,t] = str.split(':');
  return {unit:u||'', n:parseInt(n)||1, type:t||'fixed', on:'md', days:[]};
}

// Options for the month/year "On" select, phrased from the start date.
// Nth-weekday is offered only for the 1st–4th (a "5th Tuesday" exists in
// some months only); dates in the final week get "the last …" instead.
// Day-of-month 29–31 (and yearly Feb 29) is offered but clamps: in months
// lacking that day the occurrence falls on the month's last day.
function _onOptions(unit, dateStr) {
  const d   = dateStr ? new Date(dateStr+'T00:00:00') : new Date();
  const dom = d.getDate(), wd = _WD_NAME[d.getDay()];
  const nth = Math.ceil(dom/7);
  const dim = new Date(d.getFullYear(), d.getMonth()+1, 0).getDate();
  const mn  = d.toLocaleString('en-GB', {month:'long'});
  const clamp = unit === 'year' ? (d.getMonth() === 1 && dom === 29) : dom >= 29;
  const opts = [ unit === 'year'
    ? ['md', `on ${mn} ${dom}${clamp ? ' *' : ''}`]
    : ['md', `on day ${dom}${clamp ? ' *' : ''}`] ];
  if (nth <= 4)
    opts.push(['nth', unit === 'year'
      ? `the ${_ORD[nth-1]} ${wd} of ${mn}` : `the ${_ORD[nth-1]} ${wd}`]);
  if (dom > dim - 7)
    opts.push(['last', unit === 'year' ? `the last ${wd} of ${mn}` : `the last ${wd}`]);
  return opts;
}

// Warning shown when a clamped day-of-month rule is selected.
function _clampHint(unit, dateStr, on) {
  if (on !== 'md' || !dateStr) return '';
  const d = new Date(dateStr+'T00:00:00'), dom = d.getDate();
  if (unit === 'month' && dom >= 29)
    return `Not every month has a day ${dom} — in shorter months this event`
         + ` will fall on the last day of the month.`;
  if (unit === 'year' && d.getMonth() === 1 && dom === 29)
    return `February 29 exists only in leap years — otherwise this event`
         + ` will fall on February 28.`;
  return '';
}

function _refreshOn(pfx, unit, dateStr) {
  const sel = document.getElementById(`${pfx}-on`);
  const wrap = document.getElementById(`${pfx}-on-wrap`);
  if (!sel || !wrap) return;
  const monthly = unit === 'month' || unit === 'year';
  wrap.style.display = monthly ? '' : 'none';
  const hint = document.getElementById(`${pfx}-hint`);
  if (!monthly) { if (hint) hint.style.display = 'none'; return; }
  const cur = sel.value || sel.dataset.init || 'md';
  const opts = _onOptions(unit, dateStr);
  const keep = opts.some(([v]) => v === cur) ? cur : 'md';
  sel.innerHTML = opts.map(([v,l]) =>
    `<option value="${v}" ${v===keep?'selected':''}>${l}</option>`).join('');
  if (hint) {
    const msg = _clampHint(unit, dateStr, keep);
    hint.textContent = msg ? '⚠ ' + msg : '';
    hint.style.display = msg ? '' : 'none';
  }
}

// Display order Monday-first; values are RFC weekday codes.
const _WD_TOGGLES = [['MO','Mo'],['TU','Tu'],['WE','We'],['TH','Th'],
                     ['FR','Fr'],['SA','Sa'],['SU','Su']];

function _recurHTML(pfx, str, withType) {
  const {unit,n,type,on,days} = _parseRecur(str);
  const UNITS = [['','Does not repeat'],['day','Daily'],['week','Weekly'],['month','Monthly'],['year','Yearly']];
  const uOpts = UNITS.map(([v,l]) => `<option value="${v}" ${v===unit?'selected':''}>${l}</option>`).join('');
  return `<div class="fg-row" style="gap:10px;align-items:flex-end;flex-wrap:wrap;">
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
    </div>` : `<div class="fg" id="${pfx}-on-wrap" style="flex:1.6;display:none">
      <label>On</label>
      <select id="${pfx}-on" data-init="${on}"></select>
    </div>`}
  </div>
  ${withType ? '' : `<div class="fg" id="${pfx}-wd-wrap" style="${unit==='week'?'':'display:none;'}margin-top:-4px;">
    <label>On days</label>
    <div style="display:flex;gap:6px;flex-wrap:wrap;">
      ${_WD_TOGGLES.map(([v,l]) => `<button type="button" class="btn btn-sm wd-toggle${(days||[]).includes(v)?' on':''}"
        data-wd="${v}" id="${pfx}-wd-${v}"
        style="min-width:36px;padding:4px 0;">${l}</button>`).join('')}
    </div>
  </div>
  <div id="${pfx}-hint" style="display:none;font-size:11.5px;color:var(--warn,#d9a441);margin:-4px 0 10px;line-height:1.45;"></div>`}`;
}

// dateInputId (events only): the modal's start-date field — the "On" labels
// are phrased from it and refresh when it changes.
function _initRecur(pfx, withType, dateInputId) {
  const uEl = document.getElementById(`${pfx}-unit`);
  const nW  = document.getElementById(`${pfx}-n-wrap`);
  const tW  = withType ? document.getElementById(`${pfx}-type-wrap`) : null;
  const lbl = document.getElementById(`${pfx}-unit-lbl`);
  const wdWrap = withType ? null : document.getElementById(`${pfx}-wd-wrap`);
  const dayCode = () => {
    const ds = _getDateInput(dateInputId);
    return ds ? _WD[new Date(ds+'T00:00:00').getDay()] : null;
  };
  const upd = () => {
    const u = uEl.value;
    [nW,tW].forEach(el => el && (el.style.display = u?'':'none'));
    if (lbl) lbl.textContent = u ? u+'(s)' : '';
    if (!withType) {
      _refreshOn(pfx, u, _getDateInput(dateInputId));
      if (wdWrap) {
        wdWrap.style.display = u === 'week' ? '' : 'none';
        if (u === 'week'
            && !wdWrap.querySelector('.wd-toggle.on') && dayCode())
          document.getElementById(`${pfx}-wd-${dayCode()}`)?.classList.add('on');
      }
    }
  };
  if (wdWrap) wdWrap.querySelectorAll('.wd-toggle').forEach(b =>
    b.onclick = () => b.classList.toggle('on'));
  uEl.onchange = upd;
  if (!withType) {
    document.getElementById(dateInputId)
      ?.addEventListener('change', () => _refreshOn(pfx, uEl.value, _getDateInput(dateInputId)));
    document.getElementById(`${pfx}-on`)
      ?.addEventListener('change', () => _refreshOn(pfx, uEl.value, _getDateInput(dateInputId)));
    upd();  // populate "On" for prefilled rules
  }
}

function _getRecur(pfx, withType, dateInputId) {
  const u = document.getElementById(`${pfx}-unit`).value;
  if (!u) return '';
  const n = parseInt(document.getElementById(`${pfx}-n`).value) || 1;
  if (withType) {
    const t = document.getElementById(`${pfx}-type`)?.value || 'fixed';
    return `${u}:${n}:${t}`;
  }
  let r = `FREQ=${_UNIT2FREQ[u]}`;
  if (n > 1) r += `;INTERVAL=${n}`;
  if (u === 'week') {
    const days = [...document.querySelectorAll(`#${pfx}-wd-wrap .wd-toggle.on`)]
      .map(b => b.dataset.wd);
    const ds = _getDateInput(dateInputId);
    const start = ds ? _WD[new Date(ds+'T00:00:00').getDay()] : null;
    // Plain FREQ=WEEKLY when the selection is just the start date's weekday
    // (canonical, matches pre-1.6 rules); explicit BYDAY otherwise.
    if (days.length && !(days.length === 1 && days[0] === start))
      r += `;BYDAY=${days.join(',')}`;
  }
  if (u === 'month' || u === 'year') {
    const on = document.getElementById(`${pfx}-on`)?.value || 'md';
    const ds = _getDateInput(dateInputId);
    const d  = ds ? new Date(ds+'T00:00:00') : null;
    if (d && on !== 'md') {
      const wd = _WD[d.getDay()];
      if (u === 'year') r += `;BYMONTH=${d.getMonth()+1}`;
      r += `;BYDAY=${on === 'last' ? '-1' : Math.ceil(d.getDate()/7)}${wd}`;
    } else if (d) {
      const dom = d.getDate();
      // Day 29–31 (and yearly Feb 29): "that day if it exists, else the
      // last day of the month" — BYMONTHDAY=28..dom;BYSETPOS=-1 picks the
      // latest existing candidate, which is exactly the clamp.
      if (u === 'month' && dom >= 29) {
        const days = []; for (let k = 28; k <= dom; k++) days.push(k);
        r += `;BYMONTHDAY=${days.join(',')};BYSETPOS=-1`;
      } else if (u === 'year' && d.getMonth() === 1 && dom === 29) {
        r += `;BYMONTH=2;BYMONTHDAY=28,29;BYSETPOS=-1`;
      }
    }
  }
  return r;
}

// ── Recurrence in words ───────────────────────────────────────────────────────

const _WD_FULL = {MO:'Monday',TU:'Tuesday',WE:'Wednesday',TH:'Thursday',
                  FR:'Friday',SA:'Saturday',SU:'Sunday'};
const _MONTHS = ['January','February','March','April','May','June','July',
                 'August','September','October','November','December'];

export function humanizeRecur(rule, startAt) {
  if (!rule) return '';
  const {unit, n, on} = _parseRecur(rule);
  if (!unit) return '';
  const d = startAt ? new Date(startAt) : null;
  const every = n > 1 ? `every ${n} ${unit}s` : {day:'daily', week:'weekly',
    month:'monthly', year:'yearly'}[unit];
  let s = `Repeats ${every}`;
  const p = {};
  if (rule.toUpperCase().includes('FREQ='))
    rule.split(';').forEach(kv => { const [k,v] = kv.split('=');
      if (k) p[k.toUpperCase()] = v; });

  if (unit === 'week') {
    const days = p.BYDAY ? p.BYDAY.split(',').map(c => _WD_FULL[c] || c)
               : (d ? [_WD_FULL[_WD[d.getDay()]]] : []);
    if (days.length)
      s += ' on ' + (days.length > 1
        ? days.slice(0, -1).join(', ') + ' and ' + days[days.length - 1]
        : days[0]);
  } else if (unit === 'month' || unit === 'year') {
    const mn = p.BYMONTH ? _MONTHS[+p.BYMONTH - 1]
             : (d ? _MONTHS[d.getMonth()] : '');
    if (p.BYDAY) {
      const m = p.BYDAY.match(/^(-?\d)(\w\w)$/);
      if (m) {
        const which = m[1] === '-1' ? 'last' : _ORD[+m[1] - 1];
        s += ` on the ${which} ${_WD_FULL[m[2]]}`;
        if (unit === 'year' && mn) s += ` of ${mn}`;
      }
    } else if (p.BYSETPOS === '-1' && p.BYMONTHDAY) {
      const dom = Math.max(...p.BYMONTHDAY.split(',').map(Number));
      s += unit === 'year'
        ? ` on ${mn} ${dom} (Feb 28 outside leap years)`
        : ` on day ${dom} (or the last day of shorter months)`;
    } else if (d) {
      const dom = d.getDate();
      s += unit === 'year' ? ` on ${mn} ${dom}` : ` on day ${dom}`;
      if (unit === 'month' && dom >= 29)
        s += ' (or the last day of shorter months)';
    }
  }
  if (p.UNTIL) {
    const u = p.UNTIL;
    s += ` until ${u.slice(0,4)}-${u.slice(4,6)}-${u.slice(6,8)}`;
  }
  if (p.COUNT) s += `, ${p.COUNT} times`;
  return s;
}

// ── Event view modal (read-only; Edit opens the editor) ───────────────────────

export function openEventView(event = {}, onChanged) {
  const dt = iso => iso ? iso.slice(0, 10) : '';
  const tm = iso => iso ? iso.slice(11, 16) : '';
  let when;
  if (event.all_day) {
    const s = dt(event.start_at), e = dt(event.end_at) || s;
    when = s === e ? `${s} · all day` : `${s} → ${e} · all day`;
  } else {
    const s = event.start_at, e = event.end_at;
    when = dt(s) === dt(e) || !e
      ? `${dt(s)} · ${tm(s)}${e ? ' – ' + tm(e) : ''}`
      : `${dt(s)} ${tm(s)} → ${dt(e)} ${tm(e)}`;
  }
  const rec = humanizeRecur(event.recurrence, event.start_at);
  const row = (label, val) => val
    ? `<div style="margin-bottom:10px;"><div style="font-size:10.5px;color:var(--t2);
        text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px;">${label}</div>
        <div style="font-size:13.5px;color:var(--t1);">${val}</div></div>` : '';

  openModal(esc(event.title || 'Event'), `
    ${row('When', esc(when))}
    ${row('Repeats', rec ? '↻ ' + esc(rec) : '')}
    ${row('Context', event.context_path
        ? `<span style="display:inline-block;width:9px;height:9px;border-radius:2px;
            background:${event.context_color || '#6B7280'};margin-right:6px;"></span>`
          + esc(event.context_path) : '')}
    ${row('Location', event.location ? esc(event.location) : '')}
    ${row('Description', event.description
        ? `<div style="white-space:pre-wrap;">${esc(event.description)}</div>` : '')}
    <div class="form-actions">
      <span style="flex:1"></span>
      <button class="btn btn-secondary" id="v-close">Close</button>
      <button class="btn btn-primary"   id="v-edit">Edit</button>
    </div>
  `);
  document.getElementById('v-close').onclick = closeModal;
  document.getElementById('v-edit').onclick = async () => {
    let preset = null;
    if (event.recurrence) {
      preset = await chooseScope('Edit:', [
        ['occurrence', 'Only this occurrence'],
        ['future',     'This and all future occurrences'],
        ['all',        'All occurrences'],
      ]);
      if (!preset) return;                       // stay on the view card
    } else if (event.parent_uuid) {
      preset = await chooseScope('Edit:', [
        ['this', 'Only this event'],
        ['all',  'All events in the series'],
      ]);
      if (!preset) return;
    }
    closeModal();
    openEventModal(event, onChanged, onChanged, preset);
  };
}

// ── Task view modal (read-only; Edit opens the editor) ────────────────────────

export function openTaskView(t = {}, onChanged) {
  const row = (label, val) => val
    ? `<div style="margin-bottom:10px;"><div style="font-size:10.5px;color:var(--t2);
        text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px;">${label}</div>
        <div style="font-size:13.5px;color:var(--t1);">${val}</div></div>` : '';
  const impDot = `<span style="display:inline-block;width:9px;height:9px;border-radius:50%;
      background:${IMP_COLOR[t.importance] || IMP_COLOR.normal};margin-right:6px;"></span>`;
  let rec = humanizeRecur(t.recurrence, t.due_at);
  if (rec && (t.recurrence || '').split(':')[2] === 'moveable')
    rec += ' (moveable — next due counts from completion)';
  openModal(esc(t.title || 'Task'), `
    ${row('Status', esc(t.status || 'inbox'))}
    ${row('Importance / effort', impDot + esc(t.importance || 'normal')
        + ' · ' + esc(t.effort || 'medium') + ' effort')}
    ${row('Due', t.due_at ? esc(t.due_at.slice(0, 10)) : '')}
    ${row('Repeats', rec ? '↻ ' + esc(rec) : '')}
    ${row('Context', t.context_path
        ? `<span style="display:inline-block;width:9px;height:9px;border-radius:2px;
            background:${t.context_color || '#6B7280'};margin-right:6px;"></span>`
          + esc(t.context_path) : '')}
    ${row('Description', t.description
        ? `<div style="white-space:pre-wrap;">${esc(t.description)}</div>` : '')}
    <div class="form-actions">
      <span style="flex:1"></span>
      <button class="btn btn-secondary" id="v-close">Close</button>
      <button class="btn btn-primary"   id="v-edit">Edit</button>
    </div>
  `);
  document.getElementById('v-close').onclick = closeModal;
  document.getElementById('v-edit').onclick = () => {
    closeModal();
    openTaskModal(t, onChanged, onChanged);
  };
}

// ── Import / Export ───────────────────────────────────────────────────────────

async function _ctxSelectHTML(id, withAll) {
  const ctxs = await api.get('/contexts');
  const head = withAll ? '<option value="">All contexts</option>'
                       : '<option value="">— no context —</option>';
  return `<select id="${id}">${head}${ctxs.map(c =>
    `<option value="${c.id}">${esc(c.full_path)}</option>`).join('')}</select>`;
}

export async function openTransferModal() {
  openModal('Import / Export', `
    <div style="display:flex;gap:10px;margin:6px 0 4px;">
      <button class="btn btn-secondary" id="tx-export" style="flex:1;padding:14px;">⤓&nbsp; Export</button>
      <button class="btn btn-secondary" id="tx-import" style="flex:1;padding:14px;">⤒&nbsp; Import</button>
    </div>`);
  document.getElementById('tx-export').onclick = _transferExport;
  document.getElementById('tx-import').onclick = _transferImport;
}

async function _transferExport() {
  const ctxSel = await _ctxSelectHTML('tx-ctx', true);
  openModal('Export', `
    <div class="fg"><label>What</label>
      <select id="tx-what">
        <option value="both">Calendar — events + tasks (.ics)</option>
        <option value="events">Calendar — events only (.ics)</option>
        <option value="tasks">Calendar — tasks only (.ics)</option>
        <option value="journal">Journal (.zip of Markdown)</option>
        <option value="notes">Notes (.zip of Markdown)</option>
      </select></div>
    <div class="fg" id="tx-ctx-wrap"><label>Context</label>${ctxSel}</div>
    <div class="form-actions">
      <span style="flex:1"></span>
      <button class="btn btn-secondary" id="tx-back">Back</button>
      <button class="btn btn-primary"   id="tx-go">Download</button>
    </div>`);
  const whatEl = document.getElementById('tx-what');
  const tog = () => document.getElementById('tx-ctx-wrap').style.display =
    ['journal','notes'].includes(whatEl.value) ? 'none' : '';
  whatEl.onchange = tog; tog();
  document.getElementById('tx-back').onclick = openTransferModal;
  document.getElementById('tx-go').onclick = () => {
    const what = whatEl.value;
    let url;
    if (what === 'journal' || what === 'notes') {
      url = `/api/transfer/export/${what}.zip`;
    } else {
      const ctx = document.getElementById('tx-ctx').value;
      url = `/api/transfer/export/calendar.ics?what=${what}`
          + (ctx ? `&context_id=${ctx}` : '');
    }
    const a = document.createElement('a');
    a.href = url; a.download = '';
    document.body.appendChild(a); a.click(); a.remove();
    toast('Export started');
  };
}

async function _transferImport() {
  const ctxSel = await _ctxSelectHTML('tx-ctx', false);
  openModal('Import', `
    <div class="fg"><label>What</label>
      <select id="tx-what">
        <option value="ics">Calendar (.ics — events and tasks)</option>
        <option value="journal">Journal (.zip of Markdown)</option>
        <option value="notes">Notes (.zip of Markdown)</option>
      </select></div>
    <div id="tx-cal-opts">
      <div class="fg"><label>Import into context</label>${ctxSel}</div>
      <div class="fg" style="display:flex;align-items:center;gap:8px;">
        <input type="checkbox" id="tx-cats" checked style="width:auto;">
        <label for="tx-cats" style="text-transform:none;letter-spacing:0;margin:0;
          font-size:12px;color:var(--t2);cursor:pointer;">
          Match existing contexts from the file's CATEGORIES</label>
      </div>
    </div>
    <div class="fg"><label>File</label><input type="file" id="tx-file"></div>
    <div id="tx-result" style="font-size:12.5px;color:var(--t1);margin:6px 0;"></div>
    <div class="form-actions">
      <span style="flex:1"></span>
      <button class="btn btn-secondary" id="tx-back">Back</button>
      <button class="btn btn-primary"   id="tx-go">Import</button>
    </div>`);
  const whatEl = document.getElementById('tx-what');
  const tog = () => document.getElementById('tx-cal-opts').style.display =
    whatEl.value === 'ics' ? '' : 'none';
  whatEl.onchange = tog; tog();
  document.getElementById('tx-back').onclick = openTransferModal;
  document.getElementById('tx-go').onclick = async () => {
    const f = document.getElementById('tx-file').files[0];
    if (!f) { toast('Choose a file first', 'err'); return; }
    const what = whatEl.value;
    const fd = new FormData();
    fd.append('file', f);
    let url = `/api/transfer/import/${what}`;
    if (what === 'ics') {
      const ctx = document.getElementById('tx-ctx').value;
      if (ctx) fd.append('context_id', ctx);
      fd.append('match_categories',
                document.getElementById('tx-cats').checked ? 'true' : 'false');
    }
    const res = await fetch(url, { method: 'POST', body: fd });
    const out = document.getElementById('tx-result');
    if (!res.ok) { out.textContent = `Import failed (${res.status}).`; return; }
    const r = await res.json();
    out.textContent = what === 'ics'
      ? `Imported ${r.imported_events} event(s) and ${r.imported_tasks} task(s); skipped ${r.skipped} duplicate(s).`
      : `Imported ${r.imported}; skipped ${r.skipped} duplicate(s).`;
    toast('Import finished');
  };
}

document.getElementById('btn-transfer')
  ?.addEventListener('click', openTransferModal);

// ── Scope chooser (recurring-series edits/deletes) ────────────────────────────
//
// A lightweight overlay independent of the main modal, so it can stack on
// top of the event editor. Resolves to the chosen value, or null on cancel.
export function chooseScope(title, options) {
  return new Promise(resolve => {
    const ov = document.createElement('div');
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);' +
      'z-index:3000;display:flex;align-items:center;justify-content:center;';
    const box = document.createElement('div');
    box.style.cssText = 'background:var(--bg-2,#16181c);border:1px solid ' +
      'var(--bd,#2e3238);border-radius:10px;padding:18px 20px;min-width:320px;' +
      'max-width:92vw;box-shadow:0 12px 40px rgba(0,0,0,.5);';
    const h = document.createElement('div');
    h.textContent = title;
    h.style.cssText = 'font-size:13px;color:var(--t1,#e8e8e8);margin-bottom:14px;';
    box.appendChild(h);
    const done = v => { ov.remove(); resolve(v); };
    for (const [value, label] of options) {
      const b = document.createElement('button');
      b.className = 'btn btn-secondary';
      b.textContent = label;
      b.style.cssText = 'display:block;width:100%;margin-bottom:8px;text-align:left;';
      b.onclick = () => done(value);
      box.appendChild(b);
    }
    const c = document.createElement('button');
    c.className = 'btn';
    c.textContent = 'Cancel';
    c.style.cssText = 'display:block;width:100%;margin-top:4px;opacity:.75;';
    c.onclick = () => done(null);
    box.appendChild(c);
    ov.onclick = e => { if (e.target === ov) done(null); };
    ov.appendChild(box);
    document.body.appendChild(ov);
  });
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

const _SCOPE_LABEL = {
  occurrence: 'only this occurrence',
  future:     'this and all future occurrences',
  all:        'all occurrences',
  this:       'only this event',
};

// scopePreset: when the caller already asked the user which part of a
// recurring series to edit ('occurrence' | 'future' | 'all' | 'this'),
// the editor shows it and applies it on save without asking again.
// Without a preset, a recurring save falls back to asking at save time.
export async function openEventModal(event={}, onSaved, onDeleted, scopePreset=null) {
  const isEdit  = !!event.uuid;
  // Calendar views hand over occurrence rows with per-occurrence dates —
  // the form prefills with them, and `occAt` (the occurrence's original
  // start) anchors the scope chooser on save/delete.
  const occAt      = event.start_at || null;
  const isSeries   = !!(event.recurrence || event.parent_uuid);
  if (!isSeries) scopePreset = null;
  const ctxOpts = await ctxOptions(event.context_id, true);
  const allDay  = !!event.all_day;

  // Default start = now rounded up to next hour, end = +1h
  const defStartT = isEdit ? (event.start_at ? _getTimeStr(event.start_at) : '') : _nowRoundedUp();
  const defEndT   = isEdit ? (event.end_at   ? _getTimeStr(event.end_at)   : '') : _addHour(defStartT);
  const defStartD = isEdit ? event.start_at  : (new Date().toLocaleDateString('en-CA'));
  const defEndD   = isEdit ? event.end_at    : defStartD;

  const titleSuffix = scopePreset && scopePreset !== 'this'
    ? ` — ${_SCOPE_LABEL[scopePreset]}` : '';
  const scopeNote = scopePreset ? `
    <div style="font-size:11.5px;color:var(--t2);border:1px solid var(--b1);
        border-radius:var(--r);padding:6px 10px;margin-bottom:12px;">
      Editing <b style="color:var(--t1);">${_SCOPE_LABEL[scopePreset]}</b>${
        scopePreset === 'occurrence' && occAt
          ? ` (${esc(occAt.slice(0,10))}) — the series and its rule are unchanged`
          : ''}.
    </div>` : '';
  openModal((isEdit ? 'Edit event' : 'New event') + titleSuffix, `
    ${scopeNote}
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
    <div id="f-recur-sect" style="${scopePreset === 'occurrence' ? 'display:none;' : ''}">
      ${_recurHTML('f-recur', event.recurrence, false)}
    </div>
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
  _initDateField('f-sd');
  _initDateField('f-ed');
  _initRecur('f-recur', false, 'f-sd');
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
      if (scopePreset && scopePreset !== 'this') {
        if (!confirm(`Delete ${_SCOPE_LABEL[scopePreset]}?`)) return;
        const qs = `scope=${scopePreset}&occurrence_at=${encodeURIComponent(occAt || '')}`;
        await api.delete(`/events/${event.uuid}?${qs}`);
      } else if (!scopePreset && event.recurrence) {
        const scope = await chooseScope('Delete:', [
          ['occurrence', 'Only this occurrence'],
          ['future',     'This and all future occurrences'],
          ['all',        'The entire series'],
        ]);
        if (!scope) return;
        const qs = `scope=${scope}&occurrence_at=${encodeURIComponent(occAt || '')}`;
        await api.delete(`/events/${event.uuid}?${qs}`);
      } else {
        if (!confirm('Delete this event?')) return;
        await api.delete(`/events/${event.uuid}`);
      }
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
      recurrence: _getRecur('f-recur', false, 'f-sd'),
      description:document.getElementById('f-desc').value,
    };
    if (isEdit && scopePreset) {
      payload.scope = scopePreset;
      payload.occurrence_at = occAt;
    } else if (isEdit && isSeries) {
      const scope = await chooseScope('Apply changes to:', event.recurrence
        ? [['occurrence', 'Only this occurrence'],
           ['future',     'This and all future occurrences'],
           ['all',        'All occurrences']]
        : [['this',       'Only this event'],
           ['all',        'All events in the series']]);
      if (!scope) return;                 // cancelled — form stays open
      payload.scope = scope;
      payload.occurrence_at = occAt;
    }
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
    ? `<span class="badge badge-ctx" style="border-left:3px solid ${t.root_color || t.context_color || 'var(--b1)'};${t.context_color ? `color:${t.context_color};` : ''}">${t.context_path}</span>` : '';
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
