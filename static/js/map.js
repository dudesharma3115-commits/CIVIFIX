/* CivicFix — Leaflet helpers (dark map, animated status pins, location picker) */
(function () {
  const COLORS = window.CF ? CF.STATUS_COLOR : {};
  const T = window.__TILES__ || { url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', dark: true, attribution: '&copy; OpenStreetMap contributors' };
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function base(el, o) {
    if (!window.L) {
      el.innerHTML = '<div class="map-fallback"><div><b>Map could not load</b><br>Check your internet connection and refresh. Reports still work without the map.</div></div>';
      return null;
    }
    const map = L.map(el, { zoomControl: false, scrollWheelZoom: o.scroll !== false, attributionControl: true, worldCopyJump: true })
      .setView(o.center || [11.1271, 78.6569], o.zoom || 8);
    L.control.zoom({ position: 'bottomright' }).addTo(map);
    let errors = 0;
    const layer = L.tileLayer(T.url, { maxZoom: 19, subdomains: 'abc', attribution: T.attribution, className: T.dark ? 'tiles-dark' : '' }).addTo(map);
    layer.on('tileerror', () => {
      if (++errors === 8 && window.CF) CF.toast('Map background could not load.', 'warn', 'Pins still work. Check your connection or the tile provider settings.');
    });
    return map;
  }

  function pinIcon(m, fresh) {
    const c = COLORS[m.status] || '#4c7dff';
    const open = !['Resolved', 'Rejected'].includes(m.status);
    const cls = ['pin', open ? 'live' : '', open && m.priority === 'Critical' ? 'crit' : '', m.mine ? 'mine' : '', fresh ? 'drop' : ''].join(' ');
    return L.divIcon({ className: 'pin-wrap', html: `<span class="${cls}" style="--c:${c}"></span>`, iconSize: [26, 26], iconAnchor: [13, 13], popupAnchor: [0, -10] });
  }

  function popup(m) {
    const a = (window.CF && CF.agencies && CF.agencies[m.category]) || null;
    return `<div class="pop"><b>${esc(m.title)}</b><small>${esc(m.ticket)}${m.ticket ? ' · ' : ''}${esc(a ? a.short : m.category)} · ${esc(m.area)}</small>` +
      `<span class="status status-${esc(String(m.status).toLowerCase().replace(' ', '-'))}">${esc(m.status)}</span> ` +
      `<span class="prio prio-${esc(String(m.priority).toLowerCase())}">${esc(m.priority)}</span>` +
      (m.approx ? '<small style="margin-top:8px">Approximate location (no GPS pin)</small>' : '') +
      (m.url ? `<div style="margin-top:9px"><a href="${esc(m.url)}">Open case</a></div>` : '') + '</div>';
  }

  window.CivicMap = {
    /* Display map with status pins. api.setMarkers(list, fit=true), api.setFilter(fn) */
    create(el, o = {}) {
      const map = base(el, o);
      if (!map) return null;
      const layer = L.layerGroup().addTo(map);
      let all = [], filter = () => true, known = new Set(), first = true;
      const api = {
        map,
        setMarkers(list, fit = true) {
          all = list; draw(fit);
        },
        setFilter(fn) { filter = fn; draw(false); },
        fit() { draw(true); },
        flyTo(c, z) { map.flyTo(c, z, { duration: 1.1 }); },
      };
      function draw(fit) {
        layer.clearLayers();
        const pts = [];
        all.filter(filter).forEach(m => {
          const fresh = !first && !known.has(m.id);
          const mk = L.marker([m.lat, m.lng], { icon: pinIcon(m, fresh), riseOnHover: true, keyboard: true, title: m.title }).bindPopup(popup(m));
          mk.addTo(layer); pts.push([m.lat, m.lng]);
        });
        all.forEach(m => known.add(m.id)); first = false;
        if (fit && pts.length) {
          if (pts.length === 1) map.setView(pts[0], o.zoom || 15);
          else map.fitBounds(pts, { padding: [60, 60], maxZoom: 15 });
        }
      }
      setTimeout(() => map.invalidateSize(), 250);
      return api;
    },

    /* Location picker for the report form: tap/click to drop a pin, drag to adjust */
    picker(el, o = {}) {
      const map = base(el, o);
      if (!map) return null;
      let pin = null;
      const icon = L.divIcon({ className: 'pin-wrap', html: '<span class="pin live picker-pin"></span>', iconSize: [26, 26], iconAnchor: [13, 13] });
      const set = (lat, lng, silent) => {
        if (!pin) {
          pin = L.marker([lat, lng], { icon, draggable: true }).addTo(map);
          pin.on('dragend', () => { const p = pin.getLatLng(); o.onPick && o.onPick(p.lat, p.lng); });
        } else pin.setLatLng([lat, lng]);
        if (!silent) o.onPick && o.onPick(lat, lng);
      };
      map.on('click', e => set(e.latlng.lat, e.latlng.lng));
      setTimeout(() => map.invalidateSize(), 250);
      return { map, setPin: (a, b) => set(a, b, true), flyTo: (c, z) => map.flyTo(c, z, { duration: 1 }) };
    },
  };
})();
