/* CivicFix: state -> district pickers and map centres (data comes from the server in window.__GEO__) */
(function () {
  const G = window.__GEO__ || { states: [], districts: {}, agencies: {} };
  const base = window.__GENERIC__ || {};
  const INDIA = [22.9, 79.5, 5];
  window.CFGeo = {
    center(state, district) {
      const st = G.states.find(s => s.code === state);
      if (!st) return INDIA;
      const d = (G.districts[state] || []).find(x => x.n === district);
      return d && d.lat != null ? [d.lat, d.lng, 12] : [st.lat, st.lng, st.zoom];
    },
    agency(state, cat) { return Object.assign({}, base[cat] || {}, ((G.agencies[state] || {})[cat]) || {}); },
  };
  const opt = (v, t, sel) => `<option value="${String(v).replace(/"/g, '&quot;')}"${sel ? ' selected' : ''}>${String(t).replace(/</g, '&lt;')}</option>`;
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('select[data-districts]').forEach(st => {
      const dist = document.querySelector(st.dataset.districts);
      if (st.options.length <= 1) {
        st.innerHTML = opt('', 'Choose state') + G.states.map(s => opt(s.code, s.name, s.code === st.dataset.preset)).join('');
      }
      const fill = (keep) => {
        if (!dist) return;
        const list = G.districts[st.value] || [];
        dist.innerHTML = opt('', st.value ? 'Choose district' : 'Choose state first') + list.map(d => opt(d.n, d.n, d.n === keep)).join('');
      };
      fill(dist ? dist.dataset.preset : '');
      st.addEventListener('change', () => { fill(''); st.dispatchEvent(new CustomEvent('geo-change')); });
    });
    // district-only selects for a fixed state (e.g. State admins)
    document.querySelectorAll('select[data-fixed-state]').forEach(dist => {
      const list = G.districts[dist.dataset.fixedState] || [];
      dist.innerHTML = opt('', 'Choose district') + list.map(d => opt(d.n, d.n, d.n === dist.dataset.preset)).join('');
    });
  });
})();
