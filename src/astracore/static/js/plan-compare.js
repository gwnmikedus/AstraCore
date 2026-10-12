// Plan comparisons and guided-setup navigation (browser side). Needs fmt.js.
// The table mirrors pi/_plan_compare.html: same columns, same units, stacked rows on phones.
(function () {
  const {isk, m3, count, duration, esc} = window.AC;
  const SYSTEM_NAMES_SHOWN = 4;

  const COLUMNS = ['Income', 'Your time', 'Colonies', 'Characters', 'Systems', 'Restarts', 'Haul', 'Uncertainty'];

  function systemsCell(t, f) {
    const names = f.system_names || [];
    const shown = names.slice(0, SYSTEM_NAMES_SHOWN).map(esc).join(', ');
    const more = names.length > SYSTEM_NAMES_SHOWN ? ` +${names.length - SYSTEM_NAMES_SHOWN} more` : '';
    return `${count(t.systems)}${shown ? `<small>${shown}${more}</small>` : ''}${f.dropoff ? `<small>drop-off ${esc(f.dropoff)}</small>` : ''}`;
  }

  // Reasons every row gives word for word. They don't help choose, so cells list them last and muted.
  function sharedReasons(rows) {
    const lists = rows.map(r => (r.facts || {}).uncertainty).filter(Boolean).map(u => u.reasons || []);
    if (lists.length < 2) return new Set();
    return new Set(lists[0].filter(x => lists.every(l => l.includes(x))));
  }

  // Differing reasons first, shared ones after. Mirrors pi/_plan_compare.html.
  function uncertaintyCell(f, shared) {
    const u = f.uncertainty;
    if (!u) return '–';
    const reasons = u.reasons || [];
    const own = reasons.filter(x => !shared.has(x)), same = reasons.filter(x => shared.has(x));
    return `<span class="uncert uncert-${esc(u.level)}">${esc(u.label)}</span>`
      + (u.score == null ? '' : `<small class="uncert-score">score ${count(u.score)} of 100</small>`)
      + (own.length ? `<small class="uncert-own">${own.map(esc).join('; ')}</small>` : '')
      + (same.length ? `<small class="uncert-shared">Same for every option: ${same.map(esc).join('; ')}</small>` : '');
  }

  // One row. r = {label, note, totals, facts, income, incomeUnit, week, actions, current}
  // `actions` is trusted HTML built by the caller; everything else is escaped here.
  function rowHTML(r, shared = new Set()) {
    const t = r.totals || {}, f = r.facts || {};
    const income = r.income ?? t.isk_per_day;
    const week = r.week ?? (income == null ? null : income * 7);
    const unit = esc(r.incomeUnit || 'ISK/day');
    const cells = [
      `${isk(income)} ${unit}<small>${isk(week)} ISK/week</small>${t.needs_recalculation ? '<small>Character removed · recalculate income</small>' : ''}`,
      f.minutes_per_week == null ? '–' : `≈ ${duration(f.minutes_per_week)} / week`,
      `${count(t.colonies)} of ${count(t.slots_total)} slots${t.factories ? `<small>${count(t.factories)} factory planet${t.factories === 1 ? '' : 's'}</small>` : ''}`,
      f.characters_total ? `${count(f.characters_used)} of ${count(f.characters_total)}` : count(f.characters_used),
      systemsCell(t, f),
      `${count(t.restarts_per_week)} / week`,
      `${m3(t.m3_per_week)} / week${t.transfers ? `<small>${count(t.transfers)} transfer${t.transfers === 1 ? '' : 's'} between characters</small>` : ''}`,
      uncertaintyCell(f, shared),
    ];
    return `<tr${r.current ? ' class="current" aria-current="true"' : ''}>
      <th scope="row">${esc(r.label)}${r.note ? `<small>${esc(r.note)}</small>` : ''}${r.actions || ''}</th>
      ${cells.map((c, i) => `<td data-label="${COLUMNS[i]}">${c}</td>`).join('')}</tr>`;
  }

  function compareTableHTML({caption, rows, first = 'Option'}) {
    if (!rows || !rows.length) return '';
    const shared = sharedReasons(rows);
    return `<div class="scroll compare-scroll"><table class="compare-table">
      <caption>${esc(caption)}</caption>
      <thead><tr><th scope="col">${esc(first)}</th><th scope="col">Income</th><th scope="col">Your time</th>
        <th scope="col">Colonies</th><th scope="col">Characters</th><th scope="col">Systems</th>
        <th scope="col">Restarts</th><th scope="col">Haul</th><th scope="col">Uncertainty</th></tr></thead>
      <tbody>${rows.map(r => rowHTML(r, shared)).join('')}</tbody></table></div>`;
  }

  // ---- guided setup navigation ----------------------------------------------------------------
  // The furthest step that may be opened: every question before it has an answer.
  function tourReach(steps, answered) {
    const has = answered instanceof Set ? answered : new Set(answered || []);
    const i = steps.findIndex(s => s.options && !has.has(s.id));
    return i < 0 ? steps.length - 1 : i;
  }

  // What leaving a question without Continue does with the answer on screen.
  //  save:   keep it (it was compared and is either confirmed by moving on or replaces an earlier answer)
  //  keep:   nothing to do, the saved answer is unchanged
  //  revert: not compared yet, or never confirmed: go back to the saved answer
  function tourLeave({forward, valid, wasAnswered, changed}) {
    if (!valid) return 'revert';
    if (forward) return 'save';
    if (!wasAnswered) return 'revert';
    return changed ? 'save' : 'keep';
  }

  window.AC = Object.assign(window.AC || {}, {compareTableHTML, tourReach, tourLeave});
})();
