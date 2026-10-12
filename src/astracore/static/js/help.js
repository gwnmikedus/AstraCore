// The "?" help toggle (browser side). Needs fmt.js (AC.esc). Same markup as the help_toggle macro in
// templates/_help.html: a button with aria-expanded/aria-controls and an answer that is hidden until it's
// pressed. Click, tap, Enter and Space toggle it; Escape closes it and returns focus to the "?".
// The button often sits inside something clickable (a guided-setup answer card): its clicks and keys
// never reach that, so asking "?" doesn't pick the answer.
(function () {
  let made = 0;

  // The button and its answer separately, for a "?" in a cramped spot (a table cell, a label in a grid):
  // put `button` there and `answer` where a paragraph fits.
  // {text, label, more (href), moreLabel, id, showLabel}: `text` and `label` are plain text.
  function helpParts({text = '', label = 'What does this mean?', more = '', moreLabel = 'More', id = '', showLabel = false} = {}) {
    const {esc} = window.AC;
    const hid = id || `help-${++made}`;
    const name = showLabel ? '' : ` aria-label="${esc(label)}" title="${esc(label)}"`;
    return {
      button: `<button type="button" class="help-btn${showLabel ? ' labelled' : ''}" aria-expanded="false" aria-controls="${esc(hid)}"${name}>` +
        `<span class="help-mark" aria-hidden="true">?</span>${showLabel ? `<span class="help-q">${esc(label)}</span>` : ''}</button>`,
      answer: `<span class="help-answer" id="${esc(hid)}" hidden>${esc(text)}${more ? ` <a href="${esc(more)}">${esc(moreLabel)}</a>` : ''}</span>`,
    };
  }
  function helpHTML(opts = {}) {
    const {button, answer} = helpParts(opts);
    return `<span class="help-toggle">${button}${answer}</span>`;
  }

  // An answer from the server's glossary.answers() ({label, text, more}) as toggle options.
  function helpOpts(answer, {glossary = '/pi/glossary', id = '', showLabel = false, text = ''} = {}) {
    return {text: text || answer.text, label: answer.label, id, showLabel, more: answer.more ? `${glossary}#${answer.more}` : ''};
  }
  function helpFor(answer, options = {}) {
    return answer ? helpHTML(helpOpts(answer, options)) : '';
  }
  function helpPartsFor(answer, options = {}) {
    return answer ? helpParts(helpOpts(answer, options)) : {button: '', answer: ''};
  }

  function answerOf(button) {
    return button.ownerDocument.getElementById(button.getAttribute('aria-controls'));
  }
  function setOpen(button, open) {
    button.setAttribute('aria-expanded', String(open));
    const answer = answerOf(button);
    if (answer) answer.hidden = !open;
  }
  function helpToggle(button) {
    setOpen(button, button.getAttribute('aria-expanded') !== 'true');
  }

  const inside = (target, selector) => (target && target.closest ? target.closest(selector) : null);

  function onClick(e) {
    const button = inside(e.target, '.help-btn');
    if (button) {
      e.preventDefault();
      e.stopPropagation();
      helpToggle(button);
    } else if (inside(e.target, '.help-answer')) {
      e.stopPropagation();       // a "More" link still opens; the card around it isn't picked
    }
  }

  function onKey(e) {
    const button = inside(e.target, '.help-btn');
    const answer = inside(e.target, '.help-answer');
    if (!button && !answer) return;
    e.stopPropagation();         // Enter/Space/arrows belong to the "?", not to a card around it
    if (e.key !== 'Escape') return;
    const owner = button || e.target.ownerDocument.querySelector(`.help-btn[aria-controls="${answer.id}"]`);
    if (owner && owner.getAttribute('aria-expanded') === 'true') {
      setOpen(owner, false);
      owner.focus();
    }
  }

  function helpInstall(doc) {
    doc.addEventListener('click', onClick, true);
    doc.addEventListener('keydown', onKey, true);
  }
  if (typeof document !== 'undefined' && document.addEventListener) helpInstall(document);

  window.AC = Object.assign(window.AC || {}, {helpHTML, helpParts, helpFor, helpPartsFor, helpToggle, helpInstall});
})();
