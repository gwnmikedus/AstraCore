// The Advanced planner (pi/planner.html): every option on one screen, previewed live.
// Server data: the page's <script type="application/json" id="plan-data"> block (read by js/plan-render.js,
// which is loaded first and also provides planHTML and fillYieldBand).
const S = JSON.parse(PLAN_DATA.settings_json);
const API = PLAN_DATA.api, EXPORT = PLAN_DATA.export, SETTINGS_URL = PLAN_DATA.settings_url;
const OPERATE_URL = PLAN_DATA.operate_url;
let EXPORT_Q = '';
const WAYPOINT_CHARS = PLAN_DATA.waypoints || [];
const PLANS = PLAN_DATA.plans || [];
const CHANNELS = ['use_buyback', 'use_jita', 'use_amarr', 'use_local', 'use_self_haul', 'use_sell_orders'];
const $ = id => document.getElementById(id);
const {isk, num, m3, count, esc} = AC;
let crossSet = !!S.cross_character_set;   // the pilot chose Teamwork: it no longer follows the tier

// ---- controls <-> state -------------------------------------------------------
const labels = {
  max_systems: v => v >= 11 ? 'no limit' : v,
  max_jumps: v => v,
  cycle_days: v => v + (v == 1 ? ' day' : ' days'),
  per_planet: v => v,
  ship_every_days: v => v + (v == 1 ? ' day' : ' days'),
};
const HOUR_DEFAULT = PLAN_DATA.hour_defaults;   // settings.HOUR_DEFAULTS
const goalOf = e => e <= 25 ? 'passive' : e <= 75 ? 'balanced' : 'max';
const hourDefault = () => HOUR_DEFAULT[goalOf(S.effort)];
const hourValue = () => (+S.hour_isk >= 0 ? +S.hour_isk : hourDefault());
let hourControl = null;
function setGoal(v) {
  S.effort = +v;
  document.querySelectorAll('#goal button').forEach(b => b.classList.toggle('on', goalOf(+b.dataset.v) === goalOf(+v)));
  if (hourControl) hourControl.setValue(hourValue(), hourDefault(), +S.hour_isk < 0);
}
function init() {
  for (const k of ['max_jumps', 'cycle_days', 'per_planet', 'ship_every_days']) $(k).value = S[k];
  $('hour').innerHTML = AC.moneySliderHTML('hour-isk', hourValue());
  hourControl = AC.wireMoneySlider($('hour'), {value: hourValue(), defaultValue: hourDefault(), isDefault: +S.hour_isk < 0,
    onCommit: (value, {useDefault}) => { S.hour_isk = useDefault || value === hourDefault() ? -1 : value; schedule(0); }});
  setGoal(S.effort);
  for (const k of CHANNELS) $(k).checked = !!S[k];
  $('max_systems').value = S.max_systems === 0 ? 11 : S.max_systems;
  $('cross_character').checked = !!S.cross_character;
  $('buy_inputs').checked = !!S.buy_inputs;
  $('input_budget_b').value = (+S.input_budget_isk || 0) / 1e9;
  $('input_budget_b').disabled = !S.buy_inputs;
  // A drop-off saved on the Area page may not be in this list: show it rather than a blank select,
  // which would save an empty drop-off on the next change.
  if (S.hub_system && ![...$('hub_system').options].some(o => o.value === S.hub_system)) {
    $('hub_system').add(new Option(`${S.hub_system} (outside the selected area: Auto is used)`, S.hub_system));
  }
  $('hub_system').value = S.hub_system || '';
  setNever(S.product_blacklist || []);
  setTier(S.max_tier);
  showLabels();
}
// "Never produce": checkboxes of every PI product. Names are compared case-insensitively, so lists typed
// before these checkboxes still match; a name that isn't a PI product isn't kept.
const neverBoxes = () => [...document.querySelectorAll('input[data-never-all]')];
function setNever(names) {
  const want = new Set((names || []).map(n => String(n).trim().toLowerCase()));
  neverBoxes().forEach(b => { b.checked = want.has(b.value.toLowerCase()); });
  showNever();
}
const neverNames = () => neverBoxes().filter(b => b.checked).map(b => b.value);
function showNever() { const n = neverNames().length; $('o-never').textContent = n ? n + ' left out' : 'none'; }
function setTier(v) { S.max_tier = +v; document.querySelectorAll('#max_tier button').forEach(b => b.classList.toggle('on', +b.dataset.v === +v)); }
function showLabels() { for (const k in labels) { const o = $('o-' + k); if (o) o.textContent = labels[k](+$(k).value); } }
function state() {
  const ms = +$('max_systems').value;
  return {
    effort: S.effort, hour_isk: +S.hour_isk, max_tier: S.max_tier, max_systems: ms >= 11 ? 0 : ms,
    max_jumps: +$('max_jumps').value, cycle_days: +$('cycle_days').value, per_planet: +$('per_planet').value,
    cross_character: $('cross_character').checked, cross_character_set: crossSet, hub_system: $('hub_system').value,
    buy_inputs: $('buy_inputs').checked, input_budget_isk: Math.max(0, +$('input_budget_b').value || 0) * 1e9,
    product_blacklist: neverNames(), ship_every_days: +$('ship_every_days').value,
    ...Object.fromEntries(CHANNELS.map(k => [k, $(k).checked])),
  };
}

// ---- live updates -------------------------------------------------------------------
let timer = null, ctrl = null, altKey = null, updateSeq = 0, applying = false;
let baseline = null;
function invalidatePreview() {
  ++updateSeq; ++altSeq; altKey = null;
  $('apply-preview').disabled = true;
  $('preview-status').textContent = 'Preview only. Your guided answers stay unchanged until you apply.';
  $('planbar').innerHTML = '';
  document.querySelectorAll('#result [data-export]').forEach(a => { a.removeAttribute('href'); a.setAttribute('aria-disabled', 'true'); });
}
function schedule(delay = 300) { invalidatePreview(); showLabels(); clearTimeout(timer); timer = setTimeout(update, delay); }
async function update(apply = false) {
  const my = ++updateSeq;
  if (apply) applying = true;
  $('apply-preview').disabled = true;
  if (ctrl) ctrl.abort();
  ctrl = new AbortController();
  $('busy').hidden = false; $('result').classList.add('loading');
  const st = state();
  try {
    const res = await AC.post(API + (apply ? '/apply' : '/preview'), {settings: st, baseline}, {signal: ctrl.signal,
      onBusy: () => { $('busy').textContent = 'AstraCore is busy, your plan is queued…'; }});
    if (my !== updateSeq) return;
    $('busy').textContent = 'updating…';
    if (res.superseded) return;
    baseline = res.baseline || baseline;
    $('apply-preview').disabled = !!res.error || apply;
    $('preview-status').textContent = res.error ? 'Preview unavailable. Your settings were not applied.' : apply ? 'Settings applied and downloads match this plan. Operate keeps tracking your active plan until you save this one.' : 'Preview only. Apply these settings before downloading or saving this plan.';
    render(res, st);
    if (apply && !res.error && res.result_id) planBar(res.result_id);
    const key = JSON.stringify({...st, effort: null, hour_isk: null});
    if (key !== altKey) { altKey = key; loadAlts(st); } else markAlt();
  } catch (e) { if (my === updateSeq && e.name !== 'AbortError') $('result').innerHTML = '<p class="bad">' + esc(e) + '</p>'; }
  finally { if (apply) applying = false; if (my === updateSeq) { $('busy').hidden = true; $('result').classList.remove('loading'); } }
}
let altSeq = 0;
let altsWanted = false;           // the three goals cost three extra solves: compared once the pilot asks
async function loadAlts(st) {
  const my = ++altSeq;            // only the newest comparison may draw (an older answer can arrive later)
  if (!altsWanted) {
    $('alts').innerHTML = '';
    $('alts-note').innerHTML = '<button type="button" class="outline secondary inline-action" id="alts-show">Compare the three goals</button>';
    $('alts-show').onclick = () => { altsWanted = true; loadAlts(st); };
    return;
  }
  $('alts-note').textContent = '- comparing goals…';
  let alts;
  try { alts = await AC.post(API + '/alternatives', {base: st}); } catch (e) { alts = {error: String(e)}; }
  if (my !== altSeq) return;
  if (alts.superseded) { $('alts-note').textContent = ''; return; }
  if (!Array.isArray(alts)) { $('alts-note').textContent = '- comparison unavailable, change a setting to retry'; return; }
  $('alts').innerHTML = alts.map(a => a.error ? `<div class="alt"><div class="t">${a.name}</div><div class="bad muted">${esc(a.error)}</div></div>` : `
    <div class="alt ${a.dominated ? 'dimmed-option' : ''}" data-effort="${a.effort}">
      <div class="t">${a.name}${a.dominated ? ` <span class="muted">· no gain for the extra effort${a.same_as ? ' - same as ' + esc(a.same_as) : ''}</span>` : ''}</div>
      <div class="v">${isk(a.totals.isk_per_day)}<span class="muted"> /day</span></div>
      <div class="muted">${m3(a.totals.m3_per_week)}/wk · ${a.totals.systems} systems · ${a.totals.colonies}/${a.totals.slots_total} slots</div>
      <div class="muted">${esc(a.mix)}</div>
    </div>`).join('');
  document.querySelectorAll('.alt[data-effort]').forEach(el => el.onclick = () => { S.hour_isk = -1; setGoal(el.dataset.effort); schedule(0); });
  $('alts-note').textContent = '- each at its goal’s default value of your time; click one to load it';
  markAlt();
}
function markAlt() {
  const own = +S.hour_isk >= 0;
  document.querySelectorAll('.alt[data-effort]').forEach(el =>
    el.classList.toggle('cur', !own && goalOf(+el.dataset.effort) === goalOf(S.effort)));
}

// ---- rendering (planHTML and friends: js/plan-render.js) --------------------------------
function updateSellingCoverage(coverage) {
  if (!coverage) return;
  const ownTrip = $('use_self_haul').checked;
  const orders = document.querySelector('[data-order-channel]');
  orders.hidden = !coverage.trade_hub && (ownTrip || !coverage.courier);
  $('use_sell_orders').disabled = orders.hidden;
  $('batch-transport-note').textContent = ownTrip
    ? 'Bigger batches mean fewer own trips and more cargo. Journey costs are not priced.'
    : "Bigger batches spread the courier's minimum fee per contract.";
  document.querySelectorAll("[data-buyback-channel]").forEach(label => {
    label.hidden = !coverage.buyback;
    label.querySelector("input").disabled = !coverage.buyback;
  });
  document.querySelectorAll("[data-local-channel]").forEach(label => {
    label.hidden = !coverage.local;
    label.querySelector("input").disabled = !coverage.local;
  });
}
function render(res, st) {
  updateSellingCoverage(res.selling_coverage);
  const w = res.weights || {};
  $('h-effort').textContent = w.isk_per_m3 !== undefined
    ? (w.isk_per_m3 > 0 ? `Weighed against your time: each m³ hauled costs ${num(w.isk_per_m3)} ISK, each system on the pickup round ` +
       `${isk(w.isk_per_system)}/day and each factory to restock ${isk(w.isk_per_factory)}/day.` : 'Only income counts: your time is valued at 0.') : '';
  EXPORT_Q = res.result_id ? '?result=' + encodeURIComponent(res.result_id) : '';
  $('result').innerHTML = planHTML(res);
  if (!res.result_id) {
    document.querySelectorAll('#result [data-export]').forEach(a => { a.removeAttribute('href'); a.setAttribute('aria-disabled', 'true'); });
  }
  fillYieldBand(st);
}

// ---- saving the applied plan ----------------------------------------------------------------
// The same save as the guided result: the server keeps the applied snapshot, so the plan saved is the plan shown.
function planBar(resultId) {
  const my = updateSeq;
  const active = PLANS.find(p => p.active);
  $('planbar').innerHTML = `<div class="planbar">
      <span class="muted">${active ? `Your active plan is <b>${esc(active.label)}</b> (${isk(active.totals.isk_per_day)}/day).`
        : 'No active plan yet. Save this one and Operate compares what you build against it.'}</span>
      <input id="plan-label" placeholder="Name, e.g. Max ISK with P4" maxlength="80" aria-label="Plan name">
      ${active ? '<button class="outline" id="plan-save">Save as new plan</button>' : ''}
      <button id="plan-active">Save and set as active plan</button></div>`;
  const buttons = () => $('planbar').querySelectorAll('button');
  const doSave = async activate => {
    buttons().forEach(b => { b.disabled = true; });
    const r = await AC.post(API + '/plans', {result_id: resultId, label: $('plan-label').value, active: activate});
    if (my !== updateSeq) return;
    if (r.ok) {
      setSaved(r);
      $('planbar').innerHTML = `<div class="flash">Saved as <b>${esc(r.label)}</b>${r.active
        ? ` and set as your active plan. <a href="${esc(OPERATE_URL)}">Operate</a> now tracks it.` : '.'}</div>`;
    } else if (r.stale) {
      schedule(0);   // a fresh preview; Apply again to save it
      $('planbar').innerHTML = `<p class="bad">${esc(r.error)} Apply these settings again to save this plan.</p>`;
    } else {
      buttons().forEach(b => { b.disabled = false; });
      $('planbar').querySelector('.plan-save-error')?.remove();
      $('planbar').insertAdjacentHTML('beforeend', `<p class="bad plan-save-error">${esc(r.error || 'Could not save.')}</p>`);
    }
  };
  if (active) $('plan-save').onclick = () => doSave(false);
  $('plan-active').onclick = () => doSave(true);
}
function setSaved(r) {
  if (Array.isArray(r.plans)) PLANS.splice(0, PLANS.length, ...r.plans);
  EXPORT_Q = '?plan=' + r.id;
  document.querySelectorAll('#result a[data-export]').forEach(a => { a.href = EXPORT + '/' + a.dataset.export + EXPORT_Q; });
}

// ---- wire up -------------------------------------------------------------------------------
$('apply-preview').onclick = () => { if (!applying) { clearTimeout(timer); update(true); } };
init();
for (const k of ['max_systems', 'max_jumps', 'cycle_days', 'per_planet', 'ship_every_days']) $(k).addEventListener('input', () => schedule());
document.querySelectorAll('#goal button').forEach(b => b.onclick = () => { setGoal(b.dataset.v); schedule(0); });
for (const k of ['cross_character', 'hub_system', ...CHANNELS]) $(k).addEventListener('change', () => schedule(0));
$('cross_character').addEventListener('change', () => { crossSet = true; });
$('buy_inputs').addEventListener('change', () => { $('input_budget_b').disabled = !$('buy_inputs').checked; schedule(0); });
$('input_budget_b').addEventListener('change', () => schedule(0));
neverBoxes().forEach(b => b.addEventListener('change', () => { showNever(); schedule(0); }));
// The same choices from the plan result: a preview like every other control here, until Apply.
function onNeverProduce(names) { setNever(names); schedule(0); }
function onRichnessSaved() { schedule(0); }
document.querySelectorAll('#max_tier button').forEach(b => b.onclick = () => { setTier(b.dataset.v); schedule(0); });
$('refresh-prices').onclick = async e => { e.preventDefault(); $('busy').hidden = false;
  await AC.post(API + '/prices/refresh', {}); altKey = null; schedule(0); };
update();
