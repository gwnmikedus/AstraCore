// The one number formatter (browser side). Mirrors astracore/core/fmt.py.
// Fixed locale `en` so a Dutch and an English browser show the same thing: 123,379 m³ · 46.2M · 1.24B.
(function () {
  const nf = {};
  const fmt = (x, d) => (nf[d] ||= new Intl.NumberFormat('en', {minimumFractionDigits: d, maximumFractionDigits: d})).format(x);
  const nz = s => (s.startsWith('-') && !/[1-9]/.test(s)) ? s.slice(1) : s;   // never "-0"
  const ok = v => v !== null && v !== undefined && v !== '' && !Number.isNaN(+v);
  const num = (v, d = 0) => ok(v) ? nz(fmt(+v, d)) : '–';
  const isk = v => {
    if (!ok(v)) return '–';
    const x = +v, a = Math.abs(x);
    const s = a >= 1e12 ? fmt(x / 1e12, 2) + 'T' : a >= 1e9 ? fmt(x / 1e9, 2) + 'B' : a >= 1e6 ? fmt(x / 1e6, 1) + 'M'
            : a >= 1e3 ? fmt(x / 1e3, 0) + 'k' : fmt(x, 0);
    return nz(s);
  };
  const m3 = v => ok(v) ? num(v, (Math.abs(+v) > 0 && Math.abs(+v) < 10) ? 1 : 0) + ' m³' : '–';
  const count = v => ok(v) ? num(Math.round(+v)) : '–';
  const pct = (v, d = 1) => ok(v) ? nz((+v).toFixed(d).replace(/\.?0+$/, '')) + '%' : '–';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  window.AC = Object.assign(window.AC || {}, {num, isk, m3, count, pct, esc});
})();
