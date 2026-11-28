// Capsuleer tips in the footer: an intentional easter egg (docs/easter-eggs.md). Static humour only, never operation
// status or advice from account data. A page starts on a random tip; while the footer is on screen the tip changes
// every so often, but not while the pointer or focus is on it, not in a background tab and never under reduced motion.
// "One more tip" always works. Automatic changes are silent for screen readers (aria-live off); a press is announced.
(function () {
  'use strict';

  const TIPS = [
    'Check your cargo. Then check which alt you’re logged into.',
    'Your Epithal has one job. It is not a combat doctrine.',
    'A full launchpad is a hauling invitation, not a retirement plan.',
    'Remember to restart the extractors. They’re terrible at taking the initiative.',
    'Plan the planets. Leave some time for the spaceships.',
    'Customs offices take ISK, not excuses.',
    'Barren planets: not as boring as they sound. Slightly.',
    'Jita local is not a reliable source of PI advice.',
    'Planets never get ganked. Your hauler might.',
    'Gas giants: mostly hot air, occasionally profit.',
    'An idle extractor is just a very expensive lawn ornament.',
    'Your planets don’t mind if you only log in once a week.',
    'The best PI alt is the one you remember to log into.',
    'Storms on a storm planet. Nobody could have seen it coming.',
    'Spreadsheets are a valid form of PvP.',
    // Hints for the hunt (docs/easter-eggs.md): they point at easter eggs without giving them away.
    'Some things in AstraCore aren’t on any overview. Fifteen, rumour has it.',
    'The theme switch has opinions. Ask it in the dark.',
    'Capsuleers say o7. AstraCore is listening.',
    'Our footer logo likes attention. Lots of it, quickly.',
  ];
  // About one page load in fifty starts on this one.
  const RARE = 'You found the rare tip. Tell nobody. Especially not local.';
  const RARE_CHANCE = 0.02;
  const ROTATE_MS = 20000;
  const FADE_MS = 180;

  function setup(env) {
    const {document: doc, random, schedule, cancel, reducedMotion, observe} = env;
    const button = doc.querySelector('[data-next-tip]');
    const output = doc.querySelector('[data-flight-tip]');
    if (!button || !output) return null;
    const tips = [output.textContent].concat(TIPS.filter(tip => tip !== output.textContent));
    let index = Math.floor(random() * tips.length);
    let paused = false;
    let visible = false;
    let timer = null;

    const show = (text, announce) => {
      output.setAttribute('aria-live', announce ? 'polite' : 'off');
      output.textContent = text;
    };
    const next = announce => {
      index = (index + 1) % tips.length;
      show(tips[index], announce);
    };
    const auto = () => {
      timer = null;
      if (paused || !visible || doc.hidden) return arm();
      if (!output.classList) { next(false); return arm(); }
      output.classList.add('is-swapping');
      schedule(() => { next(false); output.classList.remove('is-swapping'); }, FADE_MS);
      arm();
    };
    function arm() {
      if (reducedMotion() || timer !== null) return;
      timer = schedule(auto, ROTATE_MS);
    }

    const rare = random() < RARE_CHANCE;
    show(rare ? RARE : tips[index], false);
    // The rare tip is a logbook find too (js/easter-eggs.js listens for this).
    if (rare && doc.dispatchEvent && typeof CustomEvent === 'function')
      doc.dispatchEvent(new CustomEvent('astracore:egg', {detail: 'rare_tip'}));
    button.hidden = false;
    button.addEventListener('click', () => {
      next(true);
      if (timer !== null) { cancel(timer); timer = null; }
      arm();
    });
    const tipBox = output.parentNode && output.parentNode.addEventListener ? output.parentNode : output;
    if (tipBox.addEventListener) {
      ['pointerenter', 'focusin'].forEach(type => tipBox.addEventListener(type, () => { paused = true; }));
      ['pointerleave', 'focusout'].forEach(type => tipBox.addEventListener(type, () => { paused = false; }));
    }
    observe(output, isVisible => { visible = isVisible; });
    arm();
    return {tips, next, auto, state: () => ({index, paused, visible, timer})};
  }

  const api = {TIPS, RARE, RARE_CHANCE, ROTATE_MS, setup};
  if (typeof window !== 'undefined') window.AstraTips = api;
  if (typeof document === 'undefined' || !document.addEventListener) return;
  document.addEventListener('DOMContentLoaded', () => {
    const motion = typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
    setup({
      document,
      random: Math.random,
      schedule: (fn, ms) => setTimeout(fn, ms),
      cancel: id => clearTimeout(id),
      reducedMotion: () => !!(motion && motion.matches),
      observe: (el, fn) => {
        if (typeof IntersectionObserver === 'undefined') { fn(true); return; }
        new IntersectionObserver(entries => entries.forEach(entry => fn(entry.isIntersecting))).observe(el);
      },
    });
  });
})();
