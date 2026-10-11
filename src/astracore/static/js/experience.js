(function () {
  const main = document.getElementById('main-content');
  if (!main || !window.IntersectionObserver || !main.animate) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const seen = new WeakSet();
  const active = new Set();
  const sections = main.querySelectorAll(':scope > section:not([data-hero-tour]), :scope > article, :scope > .ac-stack > section, :scope > .ac-stack > article, :scope > .tiles > .tile');
  const question = main.querySelector('#q');
  let arrivals;
  let questions;

  function arrive(element) {
    if (reducedMotion.matches) return;
    const animation = element.animate([
      {opacity: .75, transform: 'translateY(6px)'},
      {opacity: 1, transform: 'none'},
    ], {duration: 200, easing: 'ease-out'});
    active.add(animation);
    animation.onfinish = animation.oncancel = () => active.delete(animation);
  }

  function stop() {
    arrivals?.disconnect();
    questions?.disconnect();
    for (const animation of active) animation.cancel();
    active.clear();
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
    }, {rootMargin: '0px 0px -24px 0px'});
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
  }

  reducedMotion.addEventListener('change', start);
  start();
})();
