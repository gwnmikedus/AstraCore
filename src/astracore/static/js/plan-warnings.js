// Plan warnings as one "Before you build (n)" box (browser side). Needs fmt.js.
// A warning is a note from pi/planner/notices.py ({code, text, guided, steps, level}) or, in plans
// saved before notes existed, a plain string. The guided setup shows its own wording and a
// "Change <answer>" link per step; the Advanced planner shows `text`, which may name its controls.
(function () {
  const SHOWN = 3;   // the rest wait in a closed "more" section

  // Every warning as a note; identical ones once; things to do before good-to-know.
  function planNotes(list) {
    const seen = new Set(), out = [];
    for (const w of list || []) {
      const n = typeof w === 'string' ? {code: 'note', text: w, steps: [], level: 'warn'} : w;
      if (!n || !n.text || seen.has(n.text)) continue;
      seen.add(n.text);
      out.push(n);
    }
    return [...out.filter(n => n.level !== 'info'), ...out.filter(n => n.level === 'info')];
  }

  // `steps` (guided only) maps step ids to the answer names shown in the links: {area: 'Area', …}.
  function noteHTML(n, steps) {
    const {esc} = window.AC;
    const text = steps ? (n.guided || n.text) : n.text;
    const links = steps ? (n.steps || []).filter(s => steps[s])
      .map(s => `<a href="#" data-step="${esc(s)}">Change ${esc(steps[s])}</a>`).join(' · ') : '';
    return `<li${n.level === 'info' ? ' class="info"' : ''}>${esc(text)}${links ? ` <span class="note-links">${links}</span>` : ''}</li>`;
  }

  function planWarningsHTML(list, {steps = null} = {}) {
    const notes = planNotes(list);
    if (!notes.length) return '';
    const icon = window.AC.icon ? window.AC.icon('triangle-alert') : '';
    const first = notes.slice(0, SHOWN), rest = notes.slice(SHOWN);
    return `<section class="warnbox plan-notes" aria-labelledby="plan-notes-title">
      <h6 id="plan-notes-title">${icon} Before you build (${notes.length})</h6>
      <ul>${first.map(n => noteHTML(n, steps)).join('')}</ul>
      ${rest.length ? `<details><summary>${rest.length} more ${rest.length === 1 ? 'note' : 'notes'}</summary>
        <ul>${rest.map(n => noteHTML(n, steps)).join('')}</ul></details>` : ''}
    </section>`;
  }

  window.AC = Object.assign(window.AC || {}, {planNotes, planWarningsHTML});
})();
