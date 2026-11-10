/* CivicFix — live command-center rendering (gauges, rings, charts, feed, map) */
(function () {
  const $ = s => document.querySelector(s);
  let data = window.__DASH__, sig = '', lastActKey = '', first = true, hidden = new Set(), mapApi = null;
  const CENTERS = window.__CENTERS__ || {};
  const STAGES = [['Submitted', 'New'], ['Approved', 'Approved'], ['Forwarded', 'Sent'], ['In Progress', 'Fixing'], ['Resolved', 'Done']];
  const isStaffish = () => data.role === 'district_admin' || data.role === 'superadmin';

  /* ---------- SVG builders ---------- */
  let gid = 0;
  function gauge(pct, caption, value) {
    const id = 'gg' + (++gid);
    return `<svg class="gauge" viewBox="0 0 180 114" role="img" aria-label="${CF.esc(caption)} ${CF.esc(value)}">
      <defs><linearGradient id="${id}" x1="0" x2="1"><stop offset="0" stop-color="#8b5cf6"/><stop offset=".55" stop-color="#35e0ff"/><stop offset="1" stop-color="#2ee59d"/></linearGradient></defs>
      <path class="g-track" d="M12 98 A78 78 0 0 1 168 98"/>
      <path class="g-fill" d="M12 98 A78 78 0 0 1 168 98" pathLength="100" stroke="url(#${id})" stroke-dasharray="100" stroke-dashoffset="100" data-pct="${pct}"/>
      <g class="g-needle" style="transform-origin:90px 98px;transform:rotate(-90deg)" data-rot="${(pct / 100) * 180 - 90}"><line x1="90" y1="98" x2="90" y2="40"/><circle cx="90" cy="98" r="6"/></g>
      <text x="12" y="113" text-anchor="middle">0</text><text x="168" y="113" text-anchor="middle">100</text></svg>
      <div class="g-cap"><b>${CF.esc(value)}</b><small>${CF.esc(caption)}</small></div>`;
  }
  function ring(pct, color, sub, small) {
    return `<svg class="ring ${small ? 'sm' : ''}" viewBox="0 0 104 104" role="img" aria-label="${CF.esc(sub)} ${pct}%">
      <circle class="r-track" cx="52" cy="52" r="42"/>
      <circle class="r-fill" cx="52" cy="52" r="42" pathLength="100" stroke="${color}" style="color:${color}" stroke-dasharray="100" stroke-dashoffset="100" data-pct="${pct}"/>
      <text x="52" y="56">${pct}%</text><text class="r-sub" x="52" y="71">${CF.esc(sub)}</text></svg>`;
  }
  function animateIn(root) {
    const run = () => {
      root.querySelectorAll('.g-fill,.r-fill').forEach(p => p.style.strokeDashoffset = 100 - Math.min(100, +p.dataset.pct));
      root.querySelectorAll('.g-needle').forEach(n => n.style.transform = `rotate(${n.dataset.rot}deg)`);
      root.querySelectorAll('.meter i').forEach(m => m.style.width = m.dataset.w + '%');
      root.querySelectorAll('.vbars').forEach(v => v.classList.add('go'));
    };
    CF.reduced ? run() : requestAnimationFrame(() => requestAnimationFrame(run));
  }
  function smooth(pts) {
    let d = `M${pts[0][0]},${pts[0][1]}`;
    for (let i = 1; i < pts.length; i++) { const mx = (pts[i - 1][0] + pts[i][0]) / 2; d += ` C${mx},${pts[i - 1][1]} ${mx},${pts[i][1]} ${pts[i][0]},${pts[i][1]}`; }
    return d;
  }
  function trend(t) {
    const W = 300, H = 132, L = 20, B = 20, T = 8, R = 6;
    const max = Math.max(2, ...t.map(x => Math.max(x.reported, x.resolved)));
    const top = max % 2 ? max + 1 : max;
    const X = i => L + i * (W - L - R) / (t.length - 1), Y = v => T + (H - T - B) * (1 - v / top);
    const line = k => t.map((x, i) => [X(i), Y(x[k])]);
    const rep = line('reported'), res = line('resolved');
    const grid = [0, .5, 1].map(f => { const y = Y(top * f); return `<line class="grid" x1="${L}" x2="${W - R}" y1="${y}" y2="${y}"/><text x="${L - 5}" y="${y + 3}" text-anchor="end">${Math.round(top * f)}</text>`; }).join('');
    const days = t.map((x, i) => `<text x="${X(i)}" y="${H - 5}" text-anchor="middle">${x.day}</text>`).join('');
    return `<svg class="trend" viewBox="0 0 ${W} ${H}" role="img" aria-label="Reports reported and resolved over the last 7 days">
      <defs><linearGradient id="tg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8b5cf6" stop-opacity=".45"/><stop offset="1" stop-color="#8b5cf6" stop-opacity="0"/></linearGradient></defs>
      ${grid}${days}
      <path d="${smooth(rep)} L${X(t.length - 1)},${Y(0)} L${X(0)},${Y(0)}Z" fill="url(#tg)"/>
      <path class="ln draw" pathLength="1" stroke="#8b5cf6" d="${smooth(rep)}"/>
      <path class="ln draw" pathLength="1" stroke="#2ee59d" d="${smooth(res)}"/>
      ${rep.map(p => `<circle cx="${p[0]}" cy="${p[1]}" r="2.6" fill="#8b5cf6"/>`).join('')}
    </svg>`;
  }

  /* ---------- panels ---------- */
  function renderPanels() {
    const d = data, set = (id, html) => { const el = $(id); if (el) el.innerHTML = html; };

    // 1 · trend
    set('#trendChart', trend(d.trend));
    set('#trendLegend', `<span><i style="--c:#8b5cf6"></i>Reported</span><span><i style="--c:#2ee59d"></i>Resolved</span>`);
    const pendPct = d.total ? Math.round(d.pending / d.total * 100) : 0;
    set('#trendStats', `
      <div class="stat-line"><span>${d.role === 'citizen' ? 'Waiting for approval' : 'Awaiting approval'}</span><b class="${d.pending ? 'hot' : 'good'}">${d.pending}</b></div>
      <div class="meter" style="--c:#ffb020"><i data-w="${pendPct}"></i></div>
      <div class="stat-line"><span>Avg. time to resolve</span><b>${d.avg_hours === null ? '—' : d.avg_hours + ' h'}</b></div>
      <div class="meter" style="--c:#35e0ff"><i data-w="${d.avg_hours === null ? 0 : Math.min(100, d.avg_hours / d.sla_hours * 100)}"></i></div>`);

    // 2 · pipeline bars + ring + dept chips
    const max = Math.max(1, ...STAGES.map(s => d.by_status[s[0]]));
    set('#pipeRow', `<div class="vbars">${STAGES.map(([k, lab]) =>
      `<div class="vbar"><b>${d.by_status[k]}</b><div class="vbar-track"><div class="vbar-fill" style="--c:${CF.STATUS_COLOR[k]};--h:${Math.max(d.by_status[k] ? 8 : 0, d.by_status[k] / max * 100)}%"></div></div>${lab}</div>`).join('')}</div>
      ${ring(d.resolution_rate, '#2ee59d', 'RESOLVED', true)}`);
    set('#catChips', Object.entries(d.by_category).filter(([, n]) => n).map(([k, n]) => {
      const a = CF.agencies[k]; return `<span class="chip" style="--c:${a.color}">${CF.svg(a.icon, 15)}${CF.esc(a.short)} <b>${n}</b></span>`;
    }).join('') || '<span class="muted">No reports yet</span>');

    // 3 · service level
    set('#gaugeRate', gauge(d.resolution_rate, 'Resolution rate', d.resolution_rate + '%'));
    set('#ringSla', ring(d.on_time_rate, '#35e0ff', 'ON TIME', false));
    let rows;
    if (isStaffish()) {
      rows = d.departments.slice().sort((a, b) => b.open - a.open || b.total - a.total).slice(0, 5).map(x =>
        `<div class="dept-row" style="--c:${x.color}">${CF.svg(x.icon, 18)}<span>${CF.esc(x.short)}</span><b>${x.open} open</b>
         <div class="meter" style="--c:${x.color}"><i data-w="${x.total ? Math.round(x.resolved / x.total * 100) : 0}"></i></div></div>`).join('');
    } else {
      const tot = Math.max(1, d.total);
      rows = Object.entries(d.by_category).filter(([, n]) => n).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([k, n]) => {
        const a = CF.agencies[k];
        return `<div class="dept-row" style="--c:${a.color}">${CF.svg(a.icon, 18)}<span>${CF.esc(a.short)}</span><b>${n}</b><div class="meter" style="--c:${a.color}"><i data-w="${Math.round(n / tot * 100)}"></i></div></div>`;
      }).join('');
    }
    set('#deptRows', rows || '<div class="muted" style="margin-top:10px">Nothing to show yet.</div>');

    // 4 · critical alerts
    set('#gaugeCrit', gauge(Math.min(100, d.critical * 20), 'Critical open', String(d.critical)));
    set('#critSide', `<span class="lbl">${d.role === 'citizen' ? 'Your open reports' : 'In the field'}</span><div class="big-num">${d.role === 'citizen' ? d.active + d.pending : d.in_field}</div>
      <span class="lbl" style="margin-top:8px">Rejected</span><div class="big-num" style="font-size:26px;color:var(--muted)">${d.rejected}</div>`);
    set('#alertList', d.alerts.length ? d.alerts.map(a =>
      `<a class="alert-box" href="${a.url}">${CF.svg('alert', 20)}<span><b>${CF.esc(a.priority)} · ${CF.esc(a.title)}</b><small>${CF.esc(a.ticket)} · ${CF.esc(a.area)} · ${CF.ago(a.created_at)}</small></span></a>`).join('')
      : `<div class="alert-box clear">${CF.svg('check', 20)}<span><b>All clear</b><small>No critical or high-priority issues open.</small></span></div>`);

    // map overlays
    set('#kpiStrip', `
      <div class="kpi"><small>Total</small><b class="count" data-k="total">${d.total}</b></div>
      <div class="kpi warn"><small>Awaiting</small><b class="count" data-k="pending">${d.pending}</b></div>
      <div class="kpi cy"><small>In field</small><b class="count" data-k="in_field">${d.in_field}</b></div>
      <div class="kpi ok"><small>Resolved</small><b class="count" data-k="resolved">${d.resolved}</b></div>`);
    const h = d.hotspots[0];
    set('#callouts', (h ? `<div class="callout"><small>Hotspot</small><b>${CF.esc(h.area)}: <span class="hot">${h.n} open</span></b></div>`
      : `<div class="callout good"><small>Hotspot</small><b>No open issues</b></div>`) +
      (d.critical ? `<div class="callout" style="margin-top:8px"><small>Needs urgent action</small><b><span class="hot">${d.critical} critical</span> case${d.critical > 1 ? 's' : ''}</b></div>`
        : `<div class="callout good" style="margin-top:8px"><small>Priority</small><b><span class="hot">Nothing critical</span></b></div>`));

    // bottom: queue + feed
    $('#queueTitle').textContent = d.queue_title;
    set('#queueRows', d.queue.length ? d.queue.map(q => {
      const a = CF.agencies[q.category] || CF.agencies.Other;
      return `<a class="row" href="${q.url}" style="--c:${a.color}"><span class="row-ico">${CF.svg(a.icon, 19)}</span>
        <span class="row-main"><b>${CF.esc(q.title)}</b><small>${CF.esc(q.ticket)} · ${CF.esc(q.area)}${d.role === 'superadmin' ? ' · ' + CF.esc(q.district) : ''} · ${CF.esc(a.short)}</small></span>
        <span class="row-aside"><span class="status status-${q.status.toLowerCase().replace(' ', '-')}">${q.status}</span><span class="prio prio-${q.priority.toLowerCase()}">${q.priority}</span></span></a>`;
    }).join('') : `<div class="empty"><h3>${d.role === 'citizen' ? 'No reports yet' : 'Inbox zero'}</h3><p>${d.role === 'citizen' ? 'Spotted something broken? Report it with a photo.' : 'Nothing is waiting on you right now.'}</p></div>`);
    set('#feedRows', d.activity.length ? d.activity.map((a, i) =>
      `<a class="feed-item ${!first && i === 0 && lastActKey !== actKey(a) ? 'fresh' : ''}" href="${a.url}" style="--c:${CF.STATUS_COLOR[a.status] || '#35e0ff'}"><span class="tick"></span><div><p><b>${CF.esc(a.ticket)}</b> · ${CF.esc(a.status)} — ${CF.esc(a.note)}</p><small>${CF.esc(a.actor || 'CivicFix')} · ${CF.ago(a.created_at)}</small></div></a>`).join('')
      : '<div class="empty">No activity yet.</div>');

    if (d.role === 'superadmin') set('#distRows', d.districts.map(x => `<div class="dist-row"><span>${CF.esc(x.district)}</span><b>${x.resolved}/${x.total}</b></div>`).join('') || '<div class="muted">No data</div>');

    document.querySelectorAll('.count').forEach(el => CF.countUp(el, +el.dataset.k ? +el.dataset.k : +el.textContent, '', first ? 1100 : 600));
    animateIn(document);
  }
  const actKey = a => a.cid + '|' + a.status + '|' + a.created_at;

  /* ---------- map ---------- */
  function renderMap() {
    const el = $('#ccMap');
    if (!el) return;
    if (!mapApi) {
      const c = CENTERS[data.district] || [10.9, 78.4];
      mapApi = CivicMap.create(el, { center: c, zoom: CENTERS[data.district] ? 12 : 7 });
      if (!mapApi) return;
      const lg = $('#legend');
      lg.innerHTML = STAGES.map(([k]) => `<button type="button" class="mchip" data-s="${k}" style="--c:${CF.STATUS_COLOR[k]}"><i></i>${k}</button>`).join('');
      lg.addEventListener('click', e => {
        const b = e.target.closest('.mchip'); if (!b) return;
        hidden.has(b.dataset.s) ? hidden.delete(b.dataset.s) : hidden.add(b.dataset.s);
        b.classList.toggle('off', hidden.has(b.dataset.s));
        mapApi.setFilter(m => !hidden.has(m.status));
      });
      mapApi.setMarkers(data.markers, true);
    } else mapApi.setMarkers(data.markers, false);
  }

  function render() {
    renderPanels(); renderMap();
    lastActKey = data.activity[0] ? actKey(data.activity[0]) : '';
    first = false;
  }

  async function poll() {
    if (document.hidden) return;
    try {
      const r = await fetch('/api/dashboard', { headers: { Accept: 'application/json' } });
      if (!r.ok) return;
      const nd = await r.json();
      const s = JSON.stringify({ ...nd, server_time: 0 });
      if (s === sig) return;
      const prevKey = lastActKey, top = nd.activity[0];
      data = nd; sig = s;
      if (top && prevKey && actKey(top) !== prevKey) CF.toast(`${top.ticket} → ${top.status}`, 'info', top.note, top.url);
      renderPanels(); renderMap();
      lastActKey = top ? actKey(top) : '';
    } catch (e) { /* offline */ }
  }

  document.addEventListener('DOMContentLoaded', () => {
    sig = JSON.stringify({ ...data, server_time: 0 });
    render();
    setInterval(poll, 20000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  });
})();
