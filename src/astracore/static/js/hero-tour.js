// The public tour is an illustrative operation, independent of saved pilot preferences.
(function () {
  const root = document.querySelector('[data-hero-tour]');
  if (!root) return;
  const svgNS = 'http://www.w3.org/2000/svg';
  const duration = 10000;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const copies = [...root.querySelectorAll('[data-hero-copy]')];
  const scenes = [...root.querySelectorAll('[data-hero-scene]')];
  const tabs = [...root.querySelectorAll('[data-hero-tab]')];
  const pause = root.querySelector('[data-hero-pause]');
  const selling = scenes[3];
  const channels = {
    jita: {destination: 'Jita 4-4', method: 'Buy orders or sell orders',
      description: 'Consolidate in RF-K9W, use VOC delivery to Jita 4-4, then sell. Your plan compares the return after courier fees and selling taxes.'},
    amarr: {destination: 'Amarr', method: 'Emperor Family Academy · buy / sell orders',
      description: 'VOC can deliver your consolidated stock to Amarr VIII – Emperor Family Academy. Compare the return after hauling, taxes, and any broker fees.'},
    local: {destination: 'RF-K9W', method: 'VOC buyback or Delve buy orders',
      description: 'Sell locally through VOC buyback or Delve buy orders. No high-sec courier leg is needed. Your plan compares the net return against Jita and Amarr.'},
  };
  let active = 0;
  let channel = 'jita';
  let elapsed = 0;
  let previousTime;
  let userPaused = false;
  let motionPaused = false;
  let focused = false;
  let visible = true;
  let transitionTimer;
  let drawFrame;

  function updatePause() {
    const stopped = userPaused || focused || !visible || document.hidden || reducedMotion.matches;
    root.toggleAttribute('data-paused', stopped);
    root.toggleAttribute('data-motion-paused', motionPaused || !visible || document.hidden || reducedMotion.matches);
    pause.setAttribute('aria-pressed', String(userPaused || reducedMotion.matches));
    pause.textContent = reducedMotion.matches ? 'Motion reduced' : userPaused ? 'Resume tour' : 'Pause tour';
    pause.disabled = reducedMotion.matches;
  }

  function point(map, id, port) {
    const node = map.querySelector(`[data-node="${id}"] [data-port="${port}"]`);
    const rect = node.getBoundingClientRect();
    const bounds = map.getBoundingClientRect();
    return {x: rect.left + rect.width / 2 - bounds.left, y: rect.top + rect.height / 2 - bounds.top};
  }

  function route(map, from, to, kind, lane = 0) {
    const svg = map.querySelector('svg.tour-routes');
    const start = point(map, from, 'out');
    const end = point(map, to, 'in');
    let d;
    if (kind === 'refine') {
      const a = map.querySelector(`[data-node="${from}"]`).getBoundingClientRect();
      const b = map.querySelector(`[data-node="${to}"]`).getBoundingClientRect();
      const bounds = map.getBoundingClientRect();
      const y = Math.max(a.bottom, b.bottom) - bounds.top + 14 + lane * 10;
      const x = end.x - 7 - lane * 3;
      d = `M${start.x} ${start.y} V${y} H${x} V${end.y} H${end.x}`;
    } else if (Math.abs(start.x - end.x) < 8) {
      d = `M${start.x} ${start.y} V${end.y}`;
    } else if (Math.abs(start.y - end.y) < 8) {
      d = `M${start.x} ${start.y} H${end.x}`;
    } else {
      const y = kind === 'supply' ? end.y - 24 - lane * 4 : (start.y + end.y) / 2 + lane * 5;
      const system = map.querySelector(`[data-node="${from}"]`).closest('.tour-system');
      if (kind === 'supply' && system === map.querySelector('.tour-system') && system.getBoundingClientRect().width > map.clientWidth * .9) {
        const exit = system.getBoundingClientRect().bottom - map.getBoundingClientRect().top + 8 + lane * 3;
        const x = -6 - lane * 4;
        d = `M${start.x} ${start.y} V${exit} H${x} V${y} H${end.x} V${end.y}`;
      } else {
        d = `M${start.x} ${start.y} V${y} H${end.x} V${end.y}`;
      }
    }
    const base = document.createElementNS(svgNS, 'path');
    base.setAttribute('d', d);
    base.setAttribute('class', 'tour-route');
    const packet = document.createElementNS(svgNS, 'path');
    packet.setAttribute('d', d);
    packet.setAttribute('pathLength', '100');
    packet.setAttribute('class', `tour-packet tour-packet-${kind}`);
    svg.append(base, packet);
  }

  function draw() {
    drawFrame = undefined;
    const map = scenes[active].querySelector('[data-tour-map]');
    const svg = map.querySelector('svg.tour-routes');
    svg.replaceChildren();
    svg.setAttribute('viewBox', `0 0 ${map.clientWidth} ${map.clientHeight}`);
    if (active === 0) {
      for (let i = 1; i <= 3; i++) route(map, `pilot-${i}`, 'core', 'scope', i - 1);
    } else if (active === 1) {
      route(map, 'reactive', 'mechanical', 'supply');
      route(map, 'precious', 'mechanical', 'supply', 1);
      route(map, 'toxic', 'electronics', 'supply', 2);
      route(map, 'chiral', 'electronics', 'supply', 3);
      route(map, 'mechanical', 'robotics', 'refine');
      route(map, 'electronics', 'robotics', 'refine', 1);
    } else if (active === 2) {
      route(map, 'stock', 'epithal', 'pickup');
      route(map, 'epithal', 'dropoff', 'dropoff');
    } else if (channel === 'local') {
      route(map, 'origin', 'market', 'local');
    } else {
      route(map, 'origin', 'freighter', 'courier');
      route(map, 'freighter', 'market', 'market');
    }
    map.querySelectorAll('.tour-packet, .tour-colony').forEach(node => {
      node.getAnimations().forEach(animation => { animation.currentTime = elapsed; });
    });
  }

  function scheduleDraw() {
    if (drawFrame === undefined) drawFrame = requestAnimationFrame(draw);
  }

  function show(index, manual = false) {
    if (manual) userPaused = true;
    if (index === active) { updatePause(); return; }
    const old = active;
    active = index;
    elapsed = 0;
    clearTimeout(transitionTimer);
    [...copies, ...scenes].forEach(node => {
      const index = Number(node.dataset.heroCopy ?? node.dataset.heroScene);
      node.classList.remove('is-entering', 'is-leaving');
      node.hidden = index !== active && index !== old;
      node.inert = index !== active;
      node.setAttribute('aria-hidden', String(index !== active));
      if (index === active && !reducedMotion.matches) node.classList.add('is-entering');
      if (index === old && !reducedMotion.matches) node.classList.add('is-leaving');
    });
    tabs.forEach((tab, i) => {
      tab.setAttribute('aria-selected', String(i === active));
      tab.tabIndex = i === active ? 0 : -1;
    });
    root.style.setProperty('--tour-progress', '0');
    transitionTimer = setTimeout(() => {
      [...copies, ...scenes].forEach(node => {
        const index = Number(node.dataset.heroCopy ?? node.dataset.heroScene);
        node.hidden = index !== active;
        node.classList.remove('is-entering', 'is-leaving');
      });
    }, reducedMotion.matches ? 0 : 550);
    updatePause();
    scheduleDraw();
  }

  tabs.forEach((tab, i) => {
    tab.addEventListener('click', () => show(i, true));
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (active + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (active + tabs.length - 1) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next === undefined) return;
      event.preventDefault();
      show(next, true);
      tabs[next].focus();
    });
  });
  pause.addEventListener('click', () => {
    userPaused = !userPaused;
    motionPaused = userPaused;
    focused = false;
    updatePause();
  });
  root.addEventListener('focusin', event => { focused = event.target !== pause; updatePause(); });
  root.addEventListener('focusout', event => { if (!root.contains(event.relatedTarget)) { focused = false; updatePause(); } });
  document.addEventListener('visibilitychange', updatePause);
  reducedMotion.addEventListener('change', updatePause);
  new IntersectionObserver(entries => { visible = entries[0].isIntersecting; updatePause(); }, {threshold: .15}).observe(root);
  new ResizeObserver(scheduleDraw).observe(root.querySelector('.hero-visual'));
  document.fonts.ready.then(scheduleDraw);
  selling.querySelectorAll('[data-network-channel]').forEach(button => button.addEventListener('click', () => {
    channel = button.dataset.networkChannel;
    selling.dataset.channel = channel;
    userPaused = true;
    elapsed = 0;
    selling.querySelectorAll('[data-network-channel]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
    selling.querySelector('[data-network-destination]').textContent = channels[channel].destination;
    selling.querySelector('[data-network-market-method]').textContent = channels[channel].method;
    selling.querySelector('[data-network-sale-description]').textContent = channels[channel].description;
    updatePause();
    scheduleDraw();
  }));
  root.querySelector('[data-hero-controls]').hidden = false;
  updatePause();
  scheduleDraw();
  function tick(time) {
    if (previousTime !== undefined && !root.hasAttribute('data-paused')) {
      elapsed += Math.min(time - previousTime, 100);
      if (elapsed >= duration) show((active + 1) % scenes.length);
      root.style.setProperty('--tour-progress', String(Math.min(1, elapsed / duration)));
    }
    previousTime = time;
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})();
