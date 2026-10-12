// A monetary range with an exact entry. Input previews locally; change commits once.
(function () {
  const rangeMax = value => Math.max(500e6, Math.ceil(value / 50e6) * 50e6);
  const amount = value => {
    const text = String(value).trim();
    if (!/^\d+([.,]\d+)?$/.test(text)) return null;
    const parsed = Number(text.replace(',', '.'));
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
  };
  const valueText = value => `${AC.isk(value)} ISK/hour`;

  function moneySliderHTML(id, value) {
    const key = AC.esc(id);
    return `<div class="money-slider" id="${key}">
      <div class="money-slider-heading">
        <label for="${key}-range">An hour of my time is worth</label>
        <output for="${key}-range ${key}-exact" data-money-output>${valueText(value)}</output>
      </div>
      <div class="money-slider-track">
        <span class="money-slider-fill" aria-hidden="true"></span>
        <input type="range" id="${key}-range" min="0" max="${rangeMax(value)}" step="any" value="${value}"
          data-money-range aria-describedby="${key}-help">
      </div>
      <div class="money-slider-ends" aria-hidden="true"><span>Income first · 0 ISK</span><span>Less upkeep · <span data-money-max></span></span></div>
      <div class="money-slider-entry">
        <label for="${key}-exact">Exact ISK/hour
          <input type="text" inputmode="decimal" id="${key}-exact" value="${value}" autocomplete="off"
            data-money-exact aria-describedby="${key}-error" pattern="[0-9]+([.,][0-9]+)?">
        </label>
        <button type="button" class="outline secondary" data-money-reset>Use goal default</button>
      </div>
      <small id="${key}-help" data-money-help></small>
      <small id="${key}-error" class="bad" data-money-error hidden>Enter an ISK amount of zero or more.</small>
    </div>`;
  }

  function wireMoneySlider(root, {value, defaultValue, isDefault = false, onCommit}) {
    const range = root.querySelector('[data-money-range]');
    const exact = root.querySelector('[data-money-exact]');
    const output = root.querySelector('[data-money-output]');
    const reset = root.querySelector('[data-money-reset]');
    const error = root.querySelector('[data-money-error]');
    let committed = value;
    let goalDefault = defaultValue;
    let editing = false;

    function validate() {
      const parsed = amount(exact.value);
      const message = parsed === null ? 'Enter an ISK amount of zero or more.' : '';
      exact.setCustomValidity(message);
      exact.setAttribute('aria-invalid', String(parsed === null));
      error.hidden = parsed !== null;
      return parsed;
    }

    function preview(next, writeExact = true) {
      range.max = Math.max(Number(range.max), rangeMax(next));
      range.value = next;
      if (writeExact) exact.value = next;
      output.textContent = valueText(next);
      range.setAttribute('aria-valuetext', `${new Intl.NumberFormat('en', {maximumFractionDigits: 20}).format(next)} ISK/hour`);
      root.style.setProperty('--money-progress', `${next / Number(range.max) * 100}%`);
      root.querySelector('[data-money-max]').textContent = `${AC.isk(range.max)} ISK`;
      validate();
    }

    function commit(next, useDefault = false) {
      if (next === null) return;
      editing = false;
      if (next === committed && !useDefault) return;
      committed = next;
      onCommit(next, {useDefault});
    }

    range.addEventListener('input', () => {
      editing = true;
      reset.disabled = false;
      preview(Number(range.value));
    });
    range.addEventListener('change', () => commit(Number(range.value)));
    exact.addEventListener('input', () => {
      editing = true;
      reset.disabled = false;
      const next = validate();
      if (next !== null) preview(next, false);
    });
    exact.addEventListener('change', () => commit(validate()));
    reset.addEventListener('click', () => {
      preview(goalDefault);
      commit(goalDefault, true);
    });

    const control = {
      setValue(next, defaultAmount, usingDefault) {
        if (!editing || next !== committed || defaultAmount !== goalDefault) {
          preview(next);
          editing = false;
        }
        committed = next;
        goalDefault = defaultAmount;
        isDefault = usingDefault;
        reset.disabled = usingDefault && !editing;
        root.querySelector('[data-money-help]').textContent = usingDefault
          ? `Goal default: ${valueText(goalDefault)}. Higher values favor less upkeep.`
          : `Custom value. Goal default: ${valueText(goalDefault)}. Higher values favor less upkeep.`;
      },
      setDisabled(disabled) {
        range.disabled = disabled;
        exact.disabled = disabled;
        reset.disabled = disabled || (isDefault && !editing);
      },
      reportValidity() {
        validate();
        if (!exact.validity.valid) {
          const details = exact.closest('details:not([open])');
          if (details) details.open = true;
        }
        return exact.reportValidity();
      },
    };
    control.setValue(value, defaultValue, isDefault);
    return control;
  }

  Object.assign(window.AC, {moneySliderHTML, wireMoneySlider});
})();
