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
    if (returnFocus) toggle.focus();
    menu.setAttribute('data-closing', '');
    sync();
    closeTimer = setTimeout(() => {
      menu.open = false;
      menu.removeAttribute('data-closing');
      sync();
    }, reducedMotion.matches ? 0 : 180);
  }

  toggle.addEventListener('click', event => {
    event.preventDefault();
    if (menu.open && !menu.hasAttribute('data-closing')) closeMenu();
    else openMenu();
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
    menu.open = false;
    menu.removeAttribute('data-closing');
    sync();
  });
  sync();
})();
