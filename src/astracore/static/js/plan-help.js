// Explaining surprising planner outcomes (browser side): when two incomes count as "about the same",
// and why a plan stops below the product tier it may use. Pure functions; the "?" itself is js/help.js.
(function () {
  // ISK differences under 1% or 0.5M/day are noise, not a reason to prefer an answer.
  const ABOUT_SAME_ISK = 0.5e6, ABOUT_SAME_SHARE = 0.01;
  function aboutSame(a, b) {
    if (a == null || b == null) return false;
    return Math.abs(b - a) < Math.max(ABOUT_SAME_ISK, ABOUT_SAME_SHARE * Math.max(Math.abs(a), Math.abs(b)));
  }

  // `need` is a plan's tier_need (planner/optimizer.py): {allowed, used, miners, factory_miners: {tier: n}}.
  // Returns null when the plan uses every tier it may, otherwise
  // {short, question, text}: `short` for the card ("Same plan as Up to P2"), `question` names its "?"
  // and `text` answers it.
  // opts.same: the plan for the lower answer is the same one; opts.sameLabel: that answer's name.
  function tierHelp(need, {same = false, sameLabel = ''} = {}) {
    if (!need || !(need.used >= 1) || !(need.allowed > need.used)) return null;
    const next = Math.max(2, need.used + 1);
    const n = (need.factory_miners || {})[String(next)];
    const miners = +need.miners || 0;
    const short = same && sameLabel ? `Same plan as ${sameLabel}`
      : need.used === 1 ? 'Uses no factories' : `Builds up to P${need.used} only`;
    const why = n && miners
      ? `At full speed, a typical P${next} factory uses about ${n} ${n === 1 ? 'miner’s' : 'miners’'} output; this plan has ${miners}. This is a full-speed estimate, not a minimum colony count: factories can run partially.`
      : `Higher-tier factories need their complete input chain and suitable planets.`;
    return {short, question: `Why no P${next} factories?`,
            text: `${why} Inputs must come from your planned colonies; buying inputs is not modelled. Chains spanning characters need teamwork enabled. The planner adds a factory only when the ISK justifies its colonies and logistics.`};
  }

  window.AC = Object.assign(window.AC || {}, {aboutSame, tierHelp});
})();
