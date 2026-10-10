(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', () => {
    const button = document.querySelector('[data-next-tip]');
    const output = document.querySelector('[data-flight-tip]');
    if (!button || !output) return;
    const tips = [
      output.textContent,
      'Check your cargo. Then check which alt you’re logged into.',
      'Your Epithal has one job. It is not a combat doctrine.',
      'A full launchpad is a hauling invitation, not a retirement plan.',
      'Remember to restart the extractors. They’re terrible at taking the initiative.',
      'Plan the planets. Leave some time for the spaceships.',
    ];
    let index = 0;
    button.hidden = false;
    button.addEventListener('click', () => {
      index = (index + 1) % tips.length;
      output.textContent = tips[index];
    });
  });
})();
