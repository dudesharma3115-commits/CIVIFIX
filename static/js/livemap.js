/* CivicFix — full-screen live map with status + department filters */
document.addEventListener('DOMContentLoaded', async () => {
  const el = document.getElementById('bigMap');
  const api = CivicMap.create(el, { center: [10.9, 78.4], zoom: 7 });
  if (!api) return;
  const offS = new Set(), offC = new Set();
  const apply = () => api.setFilter(m => !offS.has(m.status) && !offC.has(m.category));
  const mk = (box, items, off, color) => {
    box.innerHTML = items.map(([k, label, c]) => `<button type="button" class="mchip" data-k="${CF.esc(k)}" style="--c:${c}"><i></i>${CF.esc(label)}</button>`).join('');
    box.addEventListener('click', e => {
      const b = e.target.closest('.mchip'); if (!b) return;
      off.has(b.dataset.k) ? off.delete(b.dataset.k) : off.add(b.dataset.k);
      b.classList.toggle('off', off.has(b.dataset.k)); apply();
    });
  };
  mk(document.getElementById('statusChips'), Object.entries(CF.STATUS_COLOR).map(([k, c]) => [k, k, c]), offS);
  mk(document.getElementById('catChips2'), Object.entries(CF.agencies).map(([k, a]) => [k, a.short, a.color]), offC);
  const load = async first => {
    try { const r = await fetch('/api/markers'); if (r.ok) api.setMarkers(await r.json(), first); } catch (e) { /* offline */ }
  };
  await load(true);
  setInterval(() => { if (!document.hidden) load(false); }, 25000);
});
