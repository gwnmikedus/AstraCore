// Native details keeps navigation available before JavaScript loads.
(function () {
  const menu = document.querySelector('[data-site-menu]');
  if (!menu) return;
  const toggle = menu.querySelector('summary');
  const panel = menu.querySelector('.menu-panel');
  const label = menu.querySelector('[data-menu-label]');
  const backdrop = menu.querySelector('[data-menu-backdrop]');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let closeTimer;
  let touchStart;
  let touchClickHandled = false;

  function sync() {
    const open = menu.open && !menu.hasAttribute('data-closing');
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', `${open ? 'Close' : 'Open'} AstraCore menu`);
    label.textContent = open ? 'Close' : 'Menu';
    panel.inert = !open;
    document.documentElement.toggleAttribute('data-menu-open', menu.open);
  }

  function openMenu() {
    clearTimeout(closeTimer);
    menu.removeAttribute('data-closing');
    menu.open = true;
    sync();
    panel.scrollTop = 0;
  }

  function closeMenu(returnFocus = true) {
    if (!menu.open || menu.hasAttribute('data-closing')) return;
    if (returnFocus) toggle.focus({preventScroll: true});
    menu.setAttribute('data-closing', '');
    sync();
    function finishClose() {
      menu.open = false;
      menu.removeAttribute('data-closing');
      sync();
    }
    if (reducedMotion.matches) finishClose();
    else closeTimer = setTimeout(finishClose, 180);
  }

  function activate() {
    if (menu.open && !menu.hasAttribute('data-closing')) closeMenu();
    else openMenu();
  }

  toggle.addEventListener('pointerdown', event => {
    touchClickHandled = false;
    touchStart = event.pointerType === 'touch' && event.isPrimary && event.button === 0
      ? {id: event.pointerId, x: event.clientX, y: event.clientY} : null;
  });
  toggle.addEventListener('pointerup', event => {
    if (!touchStart || event.pointerId !== touchStart.id) return;
    const distance = Math.hypot(event.clientX - touchStart.x, event.clientY - touchStart.y);
    touchStart = null;
    touchClickHandled = true;
    event.preventDefault();
    if (distance > 12) return;
    toggle.focus({preventScroll: true});
    activate();
  });
  toggle.addEventListener('pointercancel', () => {
    touchStart = null;
    touchClickHandled = true;
  });
  toggle.addEventListener('click', event => {
    event.preventDefault();
    const pointerClick = event.detail > 0 || event.pointerType === 'touch'
      || event.sourceCapabilities?.firesTouchEvents;
    // A touch release may also generate a compatibility click for the same input.
    if (touchClickHandled && pointerClick) {
      touchClickHandled = false;
      return;
    }
    touchClickHandled = false;
    activate();
  });
  menu.addEventListener('toggle', sync);
  backdrop.addEventListener('click', () => closeMenu());
  panel.addEventListener('click', event => {
    if (event.target.closest('a')) closeMenu(false);
  });
  document.addEventListener('click', event => {
    if (!menu.contains(event.target)) closeMenu(false);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu.open) {
      event.preventDefault();
      closeMenu();
    }
  });
  document.addEventListener('focusin', event => {
    if (!menu.contains(event.target)) closeMenu(false);
  });
  window.addEventListener('pageshow', () => {
    clearTimeout(closeTimer);
    touchStart = null;
    touchClickHandled = false;
    menu.open = false;
    menu.removeAttribute('data-closing');
    sync();
  });
  const header = document.querySelector('.site-header');
  if (header && window.IntersectionObserver) {
    const headerVisibility = new window.IntersectionObserver(entries => {
      document.documentElement.toggleAttribute('data-header-away', !entries[0].isIntersecting);
    });
    headerVisibility.observe(header);
  }
  sync();
})();
