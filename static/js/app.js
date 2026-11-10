/* CivicFix — shared UI helpers: toasts, notifications, forms, case actions */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const CF = (window.CF = {});
  CF.icons = window.__ICONS__ || {};
  CF.agencies = window.__AGENCIES__ || {};
  CF.csrf = ($('meta[name=csrf]') || {}).content || '';
  CF.STATUS_COLOR = { Submitted: '#ffb020', Approved: '#35e0ff', Forwarded: '#a78bfa', 'In Progress': '#4c7dff', Resolved: '#2ee59d', Rejected: '#7b8bb3' };
  CF.esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  CF.svg = (n, size = 18) => `<svg class="ic" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${CF.icons[n] || CF.icons.pin}"/></svg>`;
  CF.ago = iso => {
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    return Math.floor(s / 86400) + 'd ago';
  };
  CF.reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- toasts ---------- */
  const toasts = document.createElement('div');
  toasts.className = 'toasts'; toasts.setAttribute('aria-live', 'polite');
  document.addEventListener('DOMContentLoaded', () => document.body.appendChild(toasts));
  CF.toast = (msg, kind = 'info', sub = '', url = '') => {
    const el = document.createElement(url ? 'a' : 'div');
    if (url) el.href = url;
    el.className = 'toast ' + kind;
    el.innerHTML = CF.svg(kind === 'error' ? 'alert' : kind === 'success' ? 'check' : kind === 'action' ? 'send' : 'bell', 20) +
      `<div>${CF.esc(msg)}${sub ? `<small>${CF.esc(sub)}</small>` : ''}</div>`;
    toasts.appendChild(el);
    setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 450); }, 6500);
    while (toasts.children.length > 4) toasts.firstChild.remove();
  };

  /* ---------- count-up numbers ---------- */
  CF.countUp = (el, to, suffix = '', dur = 900) => {
    const from = parseFloat(el.dataset.v || '0') || 0;
    el.dataset.v = to;
    const dec = String(to).includes('.') ? 1 : 0;
    if (CF.reduced || from === to) { el.textContent = to + suffix; return; }
    const t0 = performance.now();
    const step = t => {
      const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      el.textContent = (from + (to - from) * e).toFixed(dec) + suffix;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };

  /* ---------- notifications ---------- */
  const bell = $('#bell'), pop = $('#notifPop'), badge = $('#bellBadge'), railBadge = $('#railBell');
  function renderNotifs(d) {
    if (!pop) return;
    const list = $('#notifList');
    list.innerHTML = d.items.length ? d.items.map(i =>
      `<a class="notif-item ${i.read ? '' : 'unread'}" href="${i.url || '/notifications'}">${CF.esc(i.message)}<small>${CF.ago(i.created_at)}</small></a>`
    ).join('') : '<div class="notif-empty">You\'re all caught up.</div>';
  }
  async function pollNotifs() {
    if (!bell || document.hidden) return;
    try {
      const r = await fetch('/api/notifications', { headers: { Accept: 'application/json' } });
      if (!r.ok) return;
      const d = await r.json();
      badge.textContent = d.unread; badge.hidden = !d.unread;
      const last = +(sessionStorage.getItem('cf_last_notif') || 0);
      const maxId = d.items.reduce((m, i) => Math.max(m, i.id), 0);
      if (last) d.items.filter(i => i.id > last && !i.read).reverse().forEach(i => CF.toast(i.message, i.kind === 'action' ? 'action' : i.kind, '', i.url || ''));
      if (maxId > last) sessionStorage.setItem('cf_last_notif', maxId);
      renderNotifs(d);
    } catch (e) { /* offline: ignore */ }
  }
  if (bell) {
    bell.addEventListener('click', e => {
      e.stopPropagation();
      pop.hidden = !pop.hidden;
      if (!pop.hidden && !badge.hidden) {
        setTimeout(() => fetch('/notifications/read', { method: 'POST', headers: { 'X-CSRF-Token': CF.csrf } })
          .then(() => { badge.hidden = true; badge.textContent = '0'; }), 1200);
      }
    });
    document.addEventListener('click', e => { if (!pop.contains(e.target)) pop.hidden = true; });
    pollNotifs(); setInterval(pollNotifs, 15000);
  }

  document.addEventListener('DOMContentLoaded', () => {
    /* server flash messages -> toasts */
    (window.__FLASH__ || []).forEach(([cat, msg]) => CF.toast(msg, cat === 'message' ? 'info' : cat));

    /* ---------- reports list search ---------- */
    const search = $('#reportSearch');
    if (search) {
      const q0 = new URLSearchParams(location.search).get('q');
      const run = () => { const q = search.value.toLowerCase(); $$('.searchable').forEach(r => r.hidden = !r.innerText.toLowerCase().includes(q)); };
      if (q0) { search.value = q0; run(); }
      search.addEventListener('input', run);
    }

    /* ---------- login demo chips ---------- */
    $$('[data-demo]').forEach(b => b.addEventListener('click', () => {
      $('input[name=email]').value = b.dataset.demo;
      $('input[name=password]').value = 'CivicFix@2026';
      $('input[name=password]').focus();
    }));

    /* ---------- report form ---------- */
    const rf = $('#reportForm');
    if (rf) {
      const centers = window.__CENTERS__ || {};
      const district = $('#districtSel'), lat = $('#latitude'), lng = $('#longitude'), status = $('#locStatus');
      const hint = $('#routeHint');
      $$('input[name=category]', rf).forEach(r => r.addEventListener('change', () => {
        const a = CF.agencies[r.value];
        hint.hidden = false;
        hint.innerHTML = `${CF.svg('send', 16)} Your district admin will review this, then forward it to <b>${CF.esc(a.name)}</b>.`;
      }));
      let picker = null;
      const start = centers[district.value] || [11.1271, 78.6569];
      if (window.CivicMap) {
        picker = CivicMap.picker($('#pickerMap'), {
          center: start, zoom: centers[district.value] ? 12 : 7,
          onPick: (a, b) => { lat.value = a.toFixed(6); lng.value = b.toFixed(6); status.textContent = `Pinned at ${a.toFixed(4)}, ${b.toFixed(4)}`; }
        });
      }
      district.addEventListener('change', () => { const c = centers[district.value]; if (c && picker) picker.flyTo(c, 12); });
      const locate = $('#locateBtn');
      locate.addEventListener('click', () => {
        if (!navigator.geolocation) { CF.toast('Location is not available in this browser.', 'error'); return; }
        locate.disabled = true; locate.lastChild.textContent = ' Locating…';
        navigator.geolocation.getCurrentPosition(p => {
          const a = p.coords.latitude, b = p.coords.longitude;
          lat.value = a.toFixed(6); lng.value = b.toFixed(6);
          status.textContent = `Pinned at ${a.toFixed(4)}, ${b.toFixed(4)} (your location)`;
          if (picker) { picker.setPin(a, b); picker.flyTo([a, b], 17); }
          locate.disabled = false; locate.lastChild.textContent = ' Use my current location';
        }, () => {
          locate.disabled = false; locate.lastChild.textContent = ' Use my current location';
          CF.toast('Could not get your location. Check permission, or tap the map to drop a pin.', 'warn');
        }, { enableHighAccuracy: true, timeout: 12000 });
      });
      initUpload($('.upload', rf), $('#photoInput'), $('#camInput'));
      rf.addEventListener('submit', () => { const b = $('button[type=submit]', rf); b.disabled = true; b.firstChild.textContent = 'Submitting… '; });
    }
    const pf = $('#proofForm');
    if (pf) initUpload($('.upload', pf), $('#proofInput'), $('#proofCam'));

    /* ---------- case actions: forward-to selects ---------- */
    $$('select[data-forward]').forEach(sel => {
      const officer = $(sel.dataset.officer), btn = sel.dataset.btn ? $(sel.dataset.btn) : null;
      const sync = () => {
        const dept = sel.value, ag = CF.agencies[dept];
        if (officer) {
          [...officer.options].forEach(o => { o.hidden = !!o.dataset.dept && o.dataset.dept !== dept; });
          if (officer.selectedOptions[0] && officer.selectedOptions[0].hidden) officer.value = '';
        }
        if (btn) btn.innerHTML = dept && ag ? `${CF.svg('send', 17)} ${btn.dataset.with} ${CF.esc(ag.short)}` : `${CF.svg('check', 17)} ${btn.dataset.without}`;
      };
      sel.addEventListener('change', sync); sync();
    });
    const rt = $('#rejectToggle'), rb = $('#rejectBox');
    if (rt) rt.addEventListener('click', () => { rb.hidden = !rb.hidden; if (!rb.hidden) $('textarea', rb).focus(); });

    /* mini map on case page */
    const mm = $('#miniMap');
    if (mm && window.CivicMap) {
      const m = CivicMap.create(mm, { center: [+mm.dataset.lat, +mm.dataset.lng], zoom: 16, scroll: false });
      if (m) m.setMarkers([{ lat: +mm.dataset.lat, lng: +mm.dataset.lng, status: mm.dataset.status, priority: mm.dataset.priority, title: mm.dataset.title, ticket: '', category: mm.dataset.category, area: mm.dataset.area, url: null }], false);
    }

    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/service-worker.js').catch(() => {});
  });

  /* photo picker: preview, drag & drop, camera capture */
  function initUpload(zone, input, cam) {
    if (!zone || !input) return;
    const prev = $('.upload-prev', zone), name = $('.upload-name', zone);
    const show = f => {
      if (!f) return;
      name.textContent = f.name + ' · ' + (f.size / 1048576).toFixed(1) + ' MB';
      prev.innerHTML = `<img alt="Selected photo preview" src="${URL.createObjectURL(f)}">`;
    };
    input.addEventListener('change', () => show(input.files[0]));
    if (cam) cam.addEventListener('change', () => {
      if (!cam.files[0]) return;
      try { const dt = new DataTransfer(); dt.items.add(cam.files[0]); input.files = dt.files; } catch (e) { /* older browsers */ }
      show(cam.files[0]);
    });
    ['dragenter', 'dragover'].forEach(ev => zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.add('drag'); }));
    ['dragleave', 'drop'].forEach(ev => zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.remove('drag'); }));
    zone.addEventListener('drop', e => {
      const f = e.dataTransfer.files[0];
      if (f && /^image\//.test(f.type)) { try { const dt = new DataTransfer(); dt.items.add(f); input.files = dt.files; show(f); } catch (err) { /* ignore */ } }
    });
  }
})();

/* admin: add-account form shows only the relevant fields */
document.addEventListener('DOMContentLoaded', () => {
  const role = document.getElementById('roleSel');
  if (!role) return;
  const d = document.getElementById('fDistrict'), p = document.getElementById('fDept');
  const sync = () => { d.hidden = role.value === 'superadmin'; p.hidden = role.value !== 'staff'; };
  role.addEventListener('change', sync); sync();
});
