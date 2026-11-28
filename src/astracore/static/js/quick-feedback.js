// In-context quick feedback (#301): the floating Feedback button, its side panel, "point at it" and the
// one-tap "Was this clear?" on the plan result and Operate. Notes are private (POST /community/notes);
// the panel shows exactly what goes with them. The server cleans the context again (core/community.py).
(function () {
  'use strict';

  const oneLine = (value, limit) => String(value || '').replace(/\s+/g, ' ').trim().slice(0, limit);
  // Digits are masked so an ISK amount, a count or an ID never travels with a label.
  const maskDigits = text => text.replace(/[0-9]/g, '#');
  const SAFE_CLASS = /^[a-z][a-z-]*$/i;

  // A short structural path to an element: up to four levels, stopping at a stable id. Ids and classes with
  // digits are skipped (they tend to be per-character or per-plan); the panel's own classes are never used.
  function selectorFor(el, root) {
    const parts = [];
    for (let node = el; node && node.nodeType === 1 && node !== root && parts.length < 4; node = node.parentElement) {
      const tag = node.tagName.toLowerCase();
      if (tag === 'body' || tag === 'html') break;
      if (node.id && /^[a-z][a-z-]*$/i.test(node.id)) { parts.unshift(`${tag}#${node.id}`); break; }
      let part = tag;
      const classes = Array.from(node.classList || []).filter(c => SAFE_CLASS.test(c) && !c.startsWith('qf-')).slice(0, 2);
      if (classes.length) part += '.' + classes.join('.');
      const parent = node.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter(child => child.tagName === node.tagName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(node) + 1})`;
      }
      parts.unshift(part);
    }
    return parts.join(' > ').slice(0, 200);
  }

  const NAMED = 'button, a, label, summary, th, h1, h2, h3, h4, h5, h6, legend, [aria-label]';
  // A label that names the part of the page, not its data: the control or heading the pilot pointed at, or
  // the heading of the section around it.
  function labelFor(el) {
    const named = el.closest ? el.closest(NAMED) : null;
    let text = named ? (named.getAttribute('aria-label') || named.textContent) : '';
    if (!oneLine(text, 80)) {
      const section = el.closest ? el.closest('section, article, fieldset, form, aside, main') : null;
      const heading = section ? section.querySelector('h1, h2, h3, h4, h5, legend') : null;
      text = heading ? heading.textContent : '';
    }
    return maskDigits(oneLine(text, 80));
  }

  // The PI guide's current step (its tracker marks it aria-current="step"); only the step title.
  function stepName(doc) {
    const current = doc.querySelector('[aria-current="step"]');
    if (!current) return '';
    const title = current.querySelector ? current.querySelector('.lbl') : null;
    return maskDigits(oneLine((title || current).textContent, 80));
  }

  function collect(doc, win, target) {
    const context = {path: win.location.pathname, viewport: `${Math.round(win.innerWidth)}x${Math.round(win.innerHeight)}`,
      theme: doc.documentElement.dataset.theme === 'light' ? 'light' : 'dark'};
    const step = stepName(doc);
    if (step) context.step = step;
    if (target) context.target = target;
    return context;
  }

  // What the pilot sees under "Sent with your note": [label, value] pairs.
  function describe(context, version) {
    const rows = [['Page', context.path]];
    if (context.step) rows.push(['Plan step', context.step]);
    if (context.target) rows.push(['Pointed at', context.target.label ? `“${context.target.label}”` : context.target.selector]);
    rows.push(['Screen', context.viewport.replace('x', ' × ')], ['Theme', context.theme === 'light' ? 'Light' : 'Dark']);
    if (version) rows.push(['Version', version]);
    return rows;
  }

  function init(doc, win) {
    const panel = doc.querySelector('[data-qf-panel]');
    const launch = doc.querySelector('[data-qf-launch]');
    if (!panel || !launch) return null;
    const form = panel.querySelector('[data-qf-form]');
    const body = form.querySelector('textarea[name="body"]');
    const status = form.querySelector('[data-qf-status]');
    const list = form.querySelector('[data-qf-context]');
    const close = form.querySelector('[data-qf-close]');
    const pointRow = form.querySelector('[data-qf-point-row]');
    const point = form.querySelector('[data-qf-point]');
    const bar = doc.querySelector('[data-qf-pointing-bar]');
    const box = doc.querySelector('[data-qf-pointing-box]');
    const version = form.dataset.version || '';
    let target = null;
    let pointing = false;
    let hovered = null;

    // With JavaScript the launcher is a toggle button, not a link to #qf-panel.
    launch.setAttribute('role', 'button');
    launch.setAttribute('aria-expanded', 'false');
    panel.classList.add('qf-ready');
    close.hidden = false;
    pointRow.hidden = false;

    function render() {
      list.textContent = '';
      describe(collect(doc, win, target), version).forEach(([term, value]) => {
        const row = doc.createElement('div');
        const dt = doc.createElement('dt');
        const dd = doc.createElement('dd');
        dt.textContent = term;
        dd.textContent = value;
        row.append(dt, dd);
        if (term === 'Pointed at') {
          const remove = doc.createElement('button');
          remove.type = 'button';
          remove.className = 'qf-remove';
          remove.textContent = 'Remove';
          remove.setAttribute('aria-label', 'Remove the part you pointed at');
          remove.addEventListener('click', () => { target = null; render(); point.focus(); });
          dd.append(' ', remove);
        }
        list.appendChild(row);
      });
    }

    function open(kind) {
      if (kind) {
        const radio = form.querySelector(`input[name="kind"][value="${kind}"]`);
        if (radio) radio.checked = true;
      }
      render();
      panel.classList.add('qf-open');
      launch.setAttribute('aria-expanded', 'true');
      status.textContent = '';
      body.focus();
    }
    function shut(returnFocus = true) {
      panel.classList.remove('qf-open');
      launch.setAttribute('aria-expanded', 'false');
      if (win.location.hash === '#qf-panel' && win.history && win.history.replaceState)
        win.history.replaceState(null, '', win.location.pathname + win.location.search);
      if (returnFocus) launch.focus();
    }
    const isOpen = () => panel.classList.contains('qf-open');

    launch.addEventListener('click', event => { event.preventDefault(); isOpen() ? shut() : open(); });
    launch.addEventListener('keydown', event => {
      if (event.key === ' ') { event.preventDefault(); launch.click(); }
    });
    close.addEventListener('click', () => shut());
    panel.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); shut(); }
    });

    // ---- point at it -------------------------------------------------------------------------
    const ours = el => !el || el === doc.body || el === doc.documentElement || panel.contains(el) || launch.contains(el)
      || (bar && bar.contains(el));
    function outline(el) {
      hovered = ours(el) ? null : el;
      if (!hovered) { box.hidden = true; return; }
      const r = hovered.getBoundingClientRect();
      Object.assign(box.style, {top: `${r.top}px`, left: `${r.left}px`, width: `${r.width}px`, height: `${r.height}px`});
      box.hidden = false;
    }
    function stopPointing(chosen) {
      pointing = false;
      doc.documentElement.classList.remove('qf-pointing');
      bar.hidden = true;
      box.hidden = true;
      doc.removeEventListener('mousemove', onMove, true);
      doc.removeEventListener('click', onPick, true);
      doc.removeEventListener('keydown', onKey, true);
      doc.removeEventListener('focusin', onFocus, true);
      win.removeEventListener('scroll', onScroll, true);
      if (chosen) target = {selector: selectorFor(chosen, doc.body), label: labelFor(chosen)};
      panel.classList.add('qf-open');
      render();
      point.focus();
    }
    const onMove = event => outline(event.target);
    const onFocus = event => outline(event.target);
    const onScroll = () => { if (hovered) outline(hovered); };
    function onPick(event) {
      if (bar.contains(event.target)) return;   // Cancel button
      event.preventDefault();
      event.stopPropagation();
      if (!ours(event.target)) stopPointing(event.target);
    }
    function onKey(event) {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); stopPointing(null); }
      else if (event.key === 'Enter' && !ours(doc.activeElement)) {
        event.preventDefault();
        event.stopPropagation();
        stopPointing(doc.activeElement);
      }
    }
    point.addEventListener('click', () => {
      pointing = true;
      panel.classList.remove('qf-open');
      doc.documentElement.classList.add('qf-pointing');
      bar.hidden = false;
      doc.addEventListener('mousemove', onMove, true);
      doc.addEventListener('click', onPick, true);
      doc.addEventListener('keydown', onKey, true);
      doc.addEventListener('focusin', onFocus, true);
      win.addEventListener('scroll', onScroll, true);
      const main = doc.getElementById('main-content');
      if (main) main.focus({preventScroll: true});
    });
    bar.querySelector('[data-qf-point-cancel]').addEventListener('click', () => stopPointing(null));

    // ---- send ----------------------------------------------------------------------------------
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const kind = (form.querySelector('input[name="kind"]:checked') || {}).value || 'confusing';
      if (oneLine(body.value, 10).length < 3) { status.textContent = 'Write a few words first.'; body.focus(); return; }
      const send = form.querySelector('[data-qf-send]');
      send.disabled = true;
      status.textContent = 'Sending…';
      const result = await win.AC.post('/community/notes', {kind, body: body.value, context: collect(doc, win, target)});
      send.disabled = false;
      if (result.error) { status.textContent = result.error; return; }
      body.value = '';
      target = null;
      render();
      status.textContent = result.message || 'Thanks. Your note is in.';
    });

    // ---- "Was this clear?" -------------------------------------------------------------------
    doc.querySelectorAll('[data-qf-rate]').forEach(rate => {
      const surface = rate.dataset.qfRate;
      const note = rate.querySelector('[data-qf-rate-status]');
      const more = rate.querySelector('[data-qf-rate-more]');
      rate.querySelectorAll('[data-qf-rate-kind]').forEach(button => button.addEventListener('click', async () => {
        const kind = button.dataset.qfRateKind;
        const result = await win.AC.post('/community/notes', {kind, body: '', context: {...collect(doc, win, null), surface}});
        if (result.error) { note.textContent = result.error; return; }
        rate.querySelectorAll('[data-qf-rate-kind]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
        note.textContent = kind === 'clear' ? 'Thanks, noted.' : 'Thanks. What wasn’t clear?';
        more.hidden = kind === 'clear';
      }));
      more.addEventListener('click', () => open('confusing'));
      // The guide shows its rating on the result step only: follow the tracker as the pilot moves.
      if (rate.dataset.qfRateWhen === 'result') {
        const track = doc.getElementById('track');
        const sync = () => { rate.hidden = !doc.querySelector('#track li.result [aria-current="step"]'); };
        if (track && win.MutationObserver) new win.MutationObserver(sync).observe(track, {childList: true, subtree: true, attributes: true, attributeFilter: ['aria-current']});
        sync();
      } else {
        rate.hidden = false;
      }
    });

    if (win.location.hash === '#qf-panel') open();
    return {open, shut, render, isPointing: () => pointing, target: () => target};
  }

  const api = {oneLine, maskDigits, selectorFor, labelFor, stepName, collect, describe, init};
  if (typeof window !== 'undefined') window.AstraQuickFeedback = api;
  if (typeof document !== 'undefined' && document.addEventListener)
    document.addEventListener('DOMContentLoaded', () => { api.instance = init(document, window); });
})();
