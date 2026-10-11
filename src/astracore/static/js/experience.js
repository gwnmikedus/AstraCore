(function () {
  const main = document.getElementById('main-content');
  if (!main || !window.IntersectionObserver || !main.animate) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const marketing = document.body.classList.contains('page-home');
  const seen = new WeakSet();
  const active = new Set();
  const sections = main.querySelectorAll(':scope > section:not([data-hero-tour], .platform-hero), :scope > article, :scope > .ac-stack > section, :scope > .ac-stack > article, :scope > .tiles > .tile');
  const scenes = main.querySelectorAll('[data-parallax]');
  const visibleScenes = new Set();
  const offsets = new WeakMap();
  const question = main.querySelector('#q');
  let arrivals;
  let questions;
  let scenery;
  let frame = 0;

  function arrive(element) {
    if (reducedMotion.matches || element.contains(document.activeElement)) return;
    const distance = marketing ? 24 : 10;
    const animation = element.animate([
      {opacity: marketing ? .35 : .7, transform: `translateY(${distance}px)`},
      {opacity: 1, transform: 'none'},
    ], {duration: marketing ? 650 : 300, easing: 'cubic-bezier(.2,.7,.2,1)'});
    active.add(animation);
    animation.onfinish = animation.oncancel = () => active.delete(animation);
  }

  function updateScenery() {
    frame = 0;
    if (reducedMotion.matches || document.hidden) return;
    const mobile = window.innerWidth <= 760;
    for (const scene of visibleScenes) {
      const hero = scene.dataset.parallax === 'hero';
      const bounds = (hero ? scene.parentElement : scene).getBoundingClientRect();
      const travel = mobile ? 12 : (hero ? 48 : 24);
      const rate = mobile ? .05 : (hero ? .16 : .08);
      const offset = Math.max(-travel, Math.min(travel,
        (window.innerHeight / 2 - bounds.top - bounds.height / 2) * rate)).toFixed(2);
      if (offsets.get(scene) === offset) continue;
      scene.style.setProperty('--art-offset', `${offset}px`);
      offsets.set(scene, offset);
    }
  }

  function scheduleScenery() {
    if (!frame && !reducedMotion.matches && !document.hidden && visibleScenes.size) {
      frame = window.requestAnimationFrame(updateScenery);
    }
  }

  function visibilityChanged() {
    if (document.hidden && frame) {
      window.cancelAnimationFrame(frame);
      frame = 0;
    } else scheduleScenery();
  }

  function stop() {
    arrivals?.disconnect();
    questions?.disconnect();
    for (const animation of active) animation.cancel();
    active.clear();
    if (scenery) {
      scenery.disconnect();
      window.removeEventListener('scroll', scheduleScenery);
      window.removeEventListener('resize', scheduleScenery);
      document.removeEventListener('visibilitychange', visibilityChanged);
    }
    if (frame) window.cancelAnimationFrame(frame);
    frame = 0;
    visibleScenes.clear();
    for (const scene of scenes) {
      scene.style.removeProperty('--art-offset');
      offsets.delete(scene);
    }
  }

  function start() {
    stop();
    if (reducedMotion.matches) return;
    arrivals = new IntersectionObserver(entries => {
      if (reducedMotion.matches) return;
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        arrivals.unobserve(entry.target);
        if (seen.has(entry.target)) continue;
        seen.add(entry.target);
        arrive(entry.target);
      }
    }, {rootMargin: marketing ? '0px 0px -12% 0px' : '0px 0px -48px 0px'});
    for (const section of sections) {
      if (!seen.has(section)) arrivals.observe(section);
    }
    if (question && window.MutationObserver) {
      questions = new MutationObserver(() => {
        const bounds = question.getBoundingClientRect();
        if (bounds.bottom <= 0 || bounds.top >= window.innerHeight) return;
        seen.add(question);
        arrive(question);
      });
      questions.observe(question, {childList: true});
    }
    if (scenes.length && window.requestAnimationFrame && window.cancelAnimationFrame) {
      scenery = new IntersectionObserver(entries => {
        for (const entry of entries) {
          if (entry.isIntersecting) visibleScenes.add(entry.target);
          else visibleScenes.delete(entry.target);
        }
        scheduleScenery();
      }, {rootMargin: '80px 0px'});
      for (const scene of scenes) scenery.observe(scene);
      window.addEventListener('scroll', scheduleScenery, {passive: true});
      window.addEventListener('resize', scheduleScenery);
      document.addEventListener('visibilitychange', visibilityChanged);
    }
  }

  reducedMotion.addEventListener('change', start);
  start();
})();
