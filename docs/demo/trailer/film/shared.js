(function () {
  const { seg, eio, rng } = kit;
  const r = rng(42);
  const D = 2400, F = 820;
  const stars = Array.from({ length: 760 }, () => ({ x: (r() - 0.5) * 5200, y: (r() - 0.5) * 3000, z: r() * D, b: 0.35 + r() * 0.65 }));
  const neb = [[-0.9, -0.4, 900, '255,106,26', 0.10], [0.8, 0.5, 1100, '79,157,255', 0.08], [0.2, -0.9, 700, '255,138,71', 0.06], [-0.4, 0.9, 1000, '79,157,255', 0.05], [1.2, -0.6, 800, '255,106,26', 0.05]];
  const WARPS = [[3.5, 950], [11, 800], [14, 450], [31, 950], [47, 1000], [51, 850], [55, 650]];
  const Z = (T) => { let z = 70 * T; for (const [c, w] of WARPS) z += w * eio(seg(T, c - 0.55, c + 0.4)); return z; };
  const STEPS = ['Goal', 'Logins', 'Area', 'Products', 'Buying', 'Selling', 'Your plan'];   // the wizard's six main questions
  const LAST = STEPS.length - 1;
  window.UI = {
    grain(st, t) { const f = Math.floor(t * 24); st.transform = 'translate(' + ((f * 37) % 60) + 'px,' + ((f * 53) % 60) + 'px)'; },
    stepper(prefix) {
      return '<div class=\"' + prefix + '-steps\" style=\"position:relative;display:flex;justify-content:space-between;padding:0 30px\">' +
        '<div style=\"position:absolute;left:60px;right:60px;top:21px;height:2px;background:#2a2e33\"></div>' +
        '<div class=\"' + prefix + '-fill\" style=\"position:absolute;left:60px;top:21px;height:2px;width:0;background:var(--main)\"></div>' +
        STEPS.map((s, i) => '<div style=\"position:relative;display:flex;flex-direction:column;align-items:center;gap:14px;width:120px\">' +
          '<span class=\"' + prefix + '-dot\" style=\"width:44px;height:44px;display:grid;place-items:center;font-family:var(--mono, ui-monospace, monospace);font-size:20px;background:var(--ground);box-shadow:inset 0 0 0 2px #646a72;color:var(--second)\">' + (i < LAST ? i + 1 : '◆') + '</span>' +
          '<span class=\"mono ' + prefix + '-lab\" style=\"font-size:15px;color:#a19d94\">' + s + '</span></div>').join('') + '</div>';
    },
    setStep(kit, prefix, k) {
      const dots = kit.stage.querySelectorAll('.' + prefix + '-dot'), labs = kit.stage.querySelectorAll('.' + prefix + '-lab');
      const i = Math.floor(k);
      dots.forEach((d, j) => { const on = j === i, done = j < i; d.style.background = on ? 'var(--main)' : 'var(--ground)'; d.style.color = on ? 'var(--ground)' : (done ? 'var(--main)' : 'var(--second)'); d.style.boxShadow = 'inset 0 0 0 2px ' + (on || done ? 'var(--main)' : '#646a72'); });
      labs.forEach((l, j) => { l.style.color = j === i ? 'var(--second)' : '#a19d94'; });
      kit.stage.querySelector('.' + prefix + '-fill').style.width = 'calc((100% - 120px) * ' + (Math.min(k, LAST) / LAST).toFixed(4) + ')';
    },
  };
  const sway = (T) => [Math.sin(T * 0.35) * 60, Math.cos(T * 0.27) * 30];
  window.SPACE = {
    Z,
    draw(c, T, dim) {
      const a = dim == null ? 1 : dim;
      const z = Z(T), zp = Z(T - 1 / 30), [sx, sy] = sway(T);
      c.clearRect(0, 0, 1920, 1080);
      for (const n of neb) {
        const px = 960 + n[0] * 900 - sx * 0.3 - (z * 0.02 * n[0]);
        const py = 540 + n[1] * 600 - sy * 0.3 - (z * 0.02 * n[1]);
        const g = c.createRadialGradient(px, py, 0, px, py, n[2]);
        g.addColorStop(0, 'rgba(' + n[3] + ',' + (n[4] * a).toFixed(3) + ')');
        g.addColorStop(1, 'rgba(' + n[3] + ',0)');
        c.fillStyle = g; c.fillRect(0, 0, 1920, 1080);
      }
      c.lineCap = 'round';
      for (const s of stars) {
        const zz = ((s.z - z) % D + D) % D + 20;
        const zo = ((s.z - zp) % D + D) % D + 20;
        const x = 960 + (s.x - sx) * F / zz, y = 540 + (s.y - sy) * F / zz;
        if (x < -50 || x > 1970 || y < -50 || y > 1130) continue;
        const near = 1 - zz / D;
        const al = Math.min(1, near * 1.4) * s.b * a;
        c.strokeStyle = 'rgba(236,232,223,' + al.toFixed(3) + ')';
        c.lineWidth = 0.6 + near * near * 3.4;
        c.beginPath(); c.moveTo(x, y);
        if (zo > zz) c.lineTo(960 + (s.x - sx) * F / zo, 540 + (s.y - sy) * F / zo); else c.lineTo(x + 0.1, y);
        c.stroke();
      }
    },
    nodes: [[-0.55, -0.25], [-0.2, -0.45], [0.15, -0.2], [-0.35, 0.15], [0.05, 0.3], [0.4, 0.1]],
    links: [[0, 1], [1, 2], [0, 3], [3, 4], [2, 4], [4, 5], [2, 5]],
    blobs: (function () { const q = rng(5); return Array.from({ length: 70 }, () => ({ lon: q() * 6.28, lat: (q() - 0.5) * 2.6, s: 0.05 + q() * 0.16, a: 0.05 + q() * 0.12 })); })(),
    nodeAt(i, rot) { const n = this.nodes[i]; return [n[0] + Math.sin(rot) * 0.15, n[1]]; },
    planet(c, cx, cy, R, rot, linkP, nodeP, t) {
      c.save();
      c.beginPath(); c.arc(cx, cy, R, 0, 6.2832); c.clip();
      const body = c.createRadialGradient(cx - R * 0.45, cy - R * 0.4, R * 0.1, cx, cy, R * 1.05);
      body.addColorStop(0, '#5a3a26'); body.addColorStop(0.45, '#2a1d16'); body.addColorStop(1, '#0d0b0a');
      c.fillStyle = body; c.fillRect(cx - R, cy - R, R * 2, R * 2);
      for (const b of this.blobs) {
        const lon = b.lon + rot; if (Math.cos(lon) < 0) continue;
        const px = cx + Math.sin(lon) * Math.cos(b.lat * 0.6) * R, py = cy + Math.sin(b.lat * 0.6) * R;
        c.fillStyle = 'rgba(255,170,110,' + (b.a * Math.cos(lon)).toFixed(3) + ')';
        c.beginPath(); c.ellipse(px, py, b.s * R * Math.cos(lon), b.s * R * 0.45, 0, 0, 6.2832); c.fill();
      }
      const shade = c.createLinearGradient(cx - R, cy - R, cx + R, cy + R);
      shade.addColorStop(0.35, 'rgba(0,0,0,0)'); shade.addColorStop(0.95, 'rgba(0,0,0,.85)');
      c.fillStyle = shade; c.fillRect(cx - R, cy - R, R * 2, R * 2);
      const pts = this.nodes.map((_, i) => { const u = this.nodeAt(i, rot); return [cx + u[0] * R, cy + u[1] * R]; });
      c.lineWidth = Math.max(2, R / 160); c.strokeStyle = '#ff6a1a'; c.shadowColor = '#ff6a1a'; c.shadowBlur = 14;
      this.links.forEach(([a, b], i) => { const p = linkP(i); if (p <= 0) return; c.beginPath(); c.moveTo(pts[a][0], pts[a][1]); c.lineTo(pts[a][0] + (pts[b][0] - pts[a][0]) * p, pts[a][1] + (pts[b][1] - pts[a][1]) * p); c.stroke(); });
      pts.forEach(([x, y], i) => { const p = nodeP(i); if (p <= 0) return; const s = (8 + 6 * p + 2 * Math.sin(t * 4 + i)) * Math.max(1, R / 470); c.fillStyle = '#ff6a1a'; c.fillRect(x - s / 2, y - s / 2, s, s); });
      c.restore(); c.shadowBlur = 0;
      const rim = c.createRadialGradient(cx, cy, R * 0.94, cx, cy, R * 1.12);
      rim.addColorStop(0, 'rgba(79,157,255,0)'); rim.addColorStop(0.35, 'rgba(79,157,255,.45)'); rim.addColorStop(1, 'rgba(79,157,255,0)');
      c.fillStyle = rim; c.beginPath(); c.arc(cx, cy, R * 1.12, 0, 6.2832); c.fill();
    },
  };
})();
