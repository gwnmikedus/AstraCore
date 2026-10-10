// Shared page behaviour: theme toggle, CSRF-aware fetch, copy buttons, confirm prompts.
(function () {
  window.AC = window.AC || {};
  const csrf = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  // JSON POST with the CSRF header. 503 {busy: true} = Astracore is busy: wait and retry, telling the
  // page through onBusy(waitingSeconds) so it can show "your plan is queued".
  AC.post = async function (url, body, opts = {}) {
    const started = Date.now();
    for (;;) {
      const r = await fetch(url, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf()},
        body: JSON.stringify(body ?? {}), signal: opts.signal,
      });
      if (r.status === 503) {
        let j = {}; try { j = await r.json(); } catch (e) {}
        if (j.busy) {
          if (opts.onBusy) opts.onBusy(Math.round((Date.now() - started) / 1000));
          await new Promise(res => setTimeout(res, (j.retry_after || 3) * 1000));
          continue;
        }
      }
      if (r.status === 409) { let j = {}; try { j = await r.json(); } catch (e) {} if (j.superseded) return {superseded: true}; }
      if (r.status === 401) { location.href = '/'; return {error: 'Signed out'}; }
      let data; try { data = await r.json(); } catch (e) { data = {error: `Server error (${r.status})`}; }
      if (!r.ok && !data.error) data.error = `Server error (${r.status})`;
      return data;
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    const tt = document.getElementById('theme-toggle');
    if (tt) tt.onclick = () => {
      const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem('ac_theme', next); } catch (e) {}
    };
    document.addEventListener('click', async e => {
      const b = e.target.closest('button.copy[data-copy]');
      if (!b) return;
      e.preventDefault();
      try { await navigator.clipboard.writeText(b.dataset.copy); } catch (err) { return; }
      const t = b.textContent; b.textContent = 'Copied'; setTimeout(() => b.textContent = t, 1200);
    });
    document.querySelectorAll('[data-autosubmit]').forEach(el => el.addEventListener('change', () => el.form.requestSubmit()));
    document.querySelectorAll('form[data-confirm]').forEach(f => f.addEventListener('submit', e => {
      if (!confirm(f.dataset.confirm)) e.preventDefault();
    }));
    // Every POST form carries the CSRF token, even ones rendered without it.
    document.querySelectorAll('form[method="post"], form[method="POST"]').forEach(f => {
      if (!f.querySelector('input[name="csrf_token"]') && csrf()) {
        const i = document.createElement('input'); i.type = 'hidden'; i.name = 'csrf_token'; i.value = csrf(); f.appendChild(i);
      }
    });
    // Close the profile menu when clicking elsewhere.
    document.addEventListener('click', e => {
      document.querySelectorAll('details.profile-menu[open]').forEach(d => { if (!d.contains(e.target)) d.open = false; });
    });
  });
})();
