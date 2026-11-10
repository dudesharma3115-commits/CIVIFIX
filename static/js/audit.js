document.addEventListener('DOMContentLoaded', () => {
  const f = document.getElementById('auditFilter');
  if (!f) return;
  f.addEventListener('input', () => {
    const q = f.value.toLowerCase();
    document.querySelectorAll('#auditTbl tbody tr').forEach(r => r.hidden = !r.innerText.toLowerCase().includes(q));
  });
});
