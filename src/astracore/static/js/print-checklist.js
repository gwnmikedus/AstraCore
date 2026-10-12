// "Print build checklist": one compact table per character (planet, template, upkeep) with tick
// boxes, to keep next to the EVE client. Needs fmt.js. The page's print stylesheet (css/print.css)
// prints only this checklist while <html> has the print-checklist class.
(function () {
  const {isk, num, esc} = window.AC;

  // A plan result (the /suggest response) as checklist markup. Characters without colonies are left out.
  function checklistHTML(res, {date = new Date()} = {}) {
    if (!res || res.error || !Array.isArray(res.characters)) return '';
    const colonies = res.colonies || [];
    const t = res.totals || {};
    const facts = [t.isk_per_day != null ? `${isk(t.isk_per_day)} ISK/day` : '',
      t.colonies != null ? `${t.colonies} colon${t.colonies === 1 ? 'y' : 'ies'}` : '',
      res.hub ? `drop-off ${esc(res.hub)}` : '', date.toISOString().slice(0, 10)].filter(Boolean);
    let h = `<h1>Build checklist</h1><p class="checklist-facts">${facts.join(' · ')}</p>`;
    for (const ch of res.characters) {
      const mine = colonies.filter(c => c.character_id === ch.character_id);
      if (!mine.length) continue;
      const route = ch.route && ch.route.order && ch.route.order.length
        ? `<span>Route ${ch.route.order.map(esc).join(' → ')}</span>` : '';
      h += `<section class="checklist-character"><h2>${esc(ch.name)} ${route}</h2>
        <table><thead><tr><th class="tick" aria-label="Done"></th><th>Planet</th><th>Template</th><th>Makes</th><th>Upkeep</th><th>Action</th></tr></thead><tbody>`;
      for (const c of mine) {
        const makes = Object.keys(c.out_per_day || {}).map(esc).join(', ');
        const every = c.upkeep && c.upkeep.visit_every_days
          ? `${c.kind === 'miner' ? 'Visit' : 'Restock'} every ${num(c.upkeep.visit_every_days, c.upkeep.visit_every_days % 1 ? 1 : 0)} d` : '';
        h += `<tr><td class="tick"><span class="tickbox" aria-hidden="true"></span></td>
          <td class="planet">${esc(c.planet)}<small>${esc(c.planet_type || '')}${c.security != null ? ` · sec ${esc(String(c.security))}` : ''}</small></td>
          <td>${esc(c.template || '')}<small>Template by DalShooth</small>
            <small class="template-source">Source: ${esc(c.template_url || 'https://github.com/DalShooth/EVE_PI_Templates')}</small>
            ${c.p0 && c.p0.length ? `<small>extract ${c.p0.map(esc).join(', ')}</small>` : ''}</td>
          <td>${makes}${c.tier ? ` <small class="tier">P${c.tier}</small>` : ''}</td>
          <td>${every}</td><td>${esc(c.action || '')}</td></tr>`;
      }
      h += `</tbody></table></section>`;
    }
    if ((res.transfers || []).length) {
      h += `<section class="checklist-character"><h2>Transfers between characters</h2><ul>` + res.transfers.map(x =>
        `<li><span class="tickbox" aria-hidden="true"></span> ${esc(x.from)} → ${esc(x.to)}: ${num(x.units_per_day)} ${esc(x.item)}/day</li>`).join('') + `</ul></section>`;
    }
    return h;
  }

  // Print only the checklist, then put the page back.
  function printChecklist(res) {
    const html = checklistHTML(res);
    if (!html) return false;
    document.querySelector('.print-checklist-sheet')?.remove();
    const sheet = document.createElement('div');
    sheet.className = 'print-checklist-sheet';
    sheet.hidden = true;
    sheet.innerHTML = html;
    document.body.appendChild(sheet);
    const root = document.documentElement;
    root.classList.add('print-checklist');
    const done = () => { root.classList.remove('print-checklist'); sheet.remove(); window.removeEventListener('afterprint', done); };
    window.addEventListener('afterprint', done);
    window.print();
    return true;
  }

  Object.assign(window.AC, {checklistHTML, printChecklist});
})();
