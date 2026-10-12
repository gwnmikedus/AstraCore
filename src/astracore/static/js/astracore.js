// Shared page behaviour: theme toggle, CSRF-aware fetch, copy buttons, confirm prompts.
(function () {
  window.AC = window.AC || {};
  const csrf = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  // JSON POST with the CSRF header. 503 {busy: true} = Astracore is busy: wait and retry, telling the
  // page through onBusy(waitingSeconds) so it can show "your plan is queued".
  AC.post = async function (url, body, opts = {}) {
    const started = Date.now();
    for (;;) {
      let r;
      try { r = await fetch(url, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf()},
        body: JSON.stringify(body ?? {}), signal: opts.signal,
      }); } catch (error) {
        if (error.name === 'AbortError') return {superseded: true};
        return {error: 'Connection lost. Check your connection and try again.'};
      }
      if (r.status === 503) {
        let j = {}; try { j = await r.json(); } catch (e) {}
        if (j.busy) {
          if (opts.onBusy) opts.onBusy(Math.round((Date.now() - started) / 1000));
          if (Date.now() - started > 120000) return {error: 'The planner is still busy. Try again in a moment.'};
          await new Promise(res => setTimeout(res, Math.min(10, Math.max(1, +j.retry_after || 3)) * 1000));
          if (opts.signal?.aborted) return {superseded: true};
          continue;
        }
      }
      if (r.status === 409) { let j = {}; try { j = await r.clone().json(); } catch (e) {} if (j.superseded) return {superseded: true}; }
      if (r.status === 401) { location.href = '/'; return {error: 'Signed out'}; }
      let data; try { data = await r.json(); } catch (e) { data = {error: `Server error (${r.status})`}; }
      if (!r.ok && !data.error) data.error = `Server error (${r.status})`;
      return data;
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    const tt = document.getElementById('theme-toggle');
    const root = document.documentElement;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const systemTheme = window.matchMedia('(prefers-color-scheme: light)');
    let themeTimer;
    // The tooltip says what the switch does, in plain words.
    const themeTips = {
      dark: ['Light theme', 'Easier in daylight.'],
      light: ['Dark theme', 'Easier on the eyes at night.']
    };
    const themeLabel = () => {
      const themeColor = document.querySelector('meta[name="theme-color"]');
      if (themeColor) themeColor.content = getComputedStyle(root).getPropertyValue('--void').trim();
      if (!tt) return;
      const light = root.dataset.theme === 'light';
      const label = `Switch to ${light ? 'dark' : 'light'} theme`;
      tt.setAttribute('aria-label', label);
      const tip = tt.querySelector('.theme-tip');
      if (tip) {
        const [title, text] = themeTips[light ? 'light' : 'dark'];
        tip.querySelector('strong').textContent = title;
        tip.querySelector('span').textContent = text;
      }
    };
    themeLabel();
    if (tt) tt.onclick = () => {
      const next = root.dataset.theme === 'light' ? 'dark' : 'light';
      clearTimeout(themeTimer);
      root.toggleAttribute('data-theme-changing', !reducedMotion.matches);
      root.dataset.theme = next;
      try { localStorage.setItem('ac_theme', next); } catch (e) {}
      themeLabel();
      tt.classList.add('tip-quiet');
      themeTimer = setTimeout(() => root.removeAttribute('data-theme-changing'), 400);
    };
    // After a switch the tooltip stays hidden until the pointer or focus leaves, so it never warns about the theme you just chose.
    if (tt) ['pointerleave', 'blur'].forEach(type => tt.addEventListener(type, () => tt.classList.remove('tip-quiet')));
    systemTheme.addEventListener('change', () => {
      let saved;
      try { saved = localStorage.getItem('ac_theme'); } catch (e) {}
      if (saved === 'light' || saved === 'dark') return;
      root.dataset.theme = systemTheme.matches ? 'light' : 'dark';
      themeLabel();
    });
    window.addEventListener('storage', event => {
      if (event.key !== 'ac_theme') return;
      root.dataset.theme = event.newValue === 'light' || event.newValue === 'dark'
        ? event.newValue : systemTheme.matches ? 'light' : 'dark';
      themeLabel();
    });
    document.addEventListener('click', async e => {
      const b = e.target.closest('button.copy[data-copy]');
      if (!b) return;
      e.preventDefault();
      const t = b.innerHTML;
      try {
        await navigator.clipboard.writeText(b.dataset.copy);
        b.textContent = 'Copied';
      } catch (err) { b.textContent = 'Copy failed'; }
      setTimeout(() => b.innerHTML = t, 1600);
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
    const preview = document.querySelector('[data-pi-preview]');
    if (preview) {
      const approaches = {
        passive: {
          title: 'A small routine. Room for everything else.',
          description: 'Start with independent miner colonies and longer extractor programs. Keep pickups close together and the number of moving parts low.',
          product: 'Proteins', tier: 'Produce P1',
          planets: 'Restart extractors. Pick up products.',
          tradeoff: 'Less upkeep; lower hourly extraction.',
        },
        balanced: {
          title: 'A little more industry. When it earns its keep.',
          description: 'Combine miner output in factory colonies where the extra income justifies restocking. Your real plan compares that work against the value of your time.',
          product: 'Mechanical Parts', tier: 'Produce P2',
          planets: 'Restart, collect, and supply your factories.',
          tradeoff: 'More inputs to move; more value per cubic metre.',
        },
        max: {
          title: 'More moving parts. Every colony has a job.',
          description: 'Consider longer production chains, more systems, and selling options. Your real plan checks which combinations pay after hauling, fees, and taxes.',
          product: 'Robotics', tier: 'Produce P3+',
          planets: 'Coordinate miners, factories, and character transfers.',
          tradeoff: 'More logistics and market work to manage.',
        },
      };
      preview.querySelectorAll('[data-approach]').forEach(button => button.addEventListener('click', () => {
        const approach = approaches[button.dataset.approach];
        if (!approach) return;
        preview.querySelectorAll('[data-approach]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
        for (const field of ['title', 'description', 'tier', 'planets', 'tradeoff']) {
          preview.querySelector(`[data-preview-${field}]`).textContent = approach[field];
        }
        const product = preview.querySelector('[data-preview-product]');
        product.src = button.dataset.product;
        product.alt = approach.product;
        const start = preview.querySelector('[data-preview-start]');
        if (start) {
          const url = new URL(start.href);
          url.searchParams.set('rhythm', button.dataset.approach);
          start.href = url.href;
        }
        AC.enterPanel(preview.querySelector('.preview-output'));
      }));
    }
  });
  AC.enterPanel = function (element) {
    if (!element || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    element.getAnimations().forEach(animation => animation.cancel());
    element.animate([{opacity: .3}, {opacity: 1}], {duration: 200, easing: 'ease-out'});
  };
})();
