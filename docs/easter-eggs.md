# Easter eggs

AstraCore has a few small jokes for capsuleers. **They are intentional.** Please don't remove them in a copy or
cleanup pass; `tests/test_easter_eggs.cjs` and `tests/test_easter_eggs.py` fail if one disappears. If one has to
go, remove it here and in the tests in the same pull request, and say why.

Every easter egg follows the same rules:

- it never blocks anything, shifts the layout or covers a control;
- it never hides real information or changes what something means (labels and `aria-label`s stay plain);
- it has no motion under `prefers-reduced-motion`;
- it fits the CSP: no inline scripts or styles, no third-party assets;
- it is plain text, with no emoji (brand book).

| Easter egg | Where | How to find it |
| --- | --- | --- |
| **Flashbang warning** | `templates/_navigation.html`, `static/js/astracore.js` (`themeTips`) | Hover or focus the theme switch in the dark theme. In the light theme it says "Rest your eyes". First added in #38, removed in #167, back in #277. |
| **Capsuleer tips** | `templates/base.html` footer, `static/js/flight-tips.js` | Each page starts on a random tip; while the footer is in view a new one comes every 20 seconds (paused on hover or focus, off under reduced motion). "One more tip" shows the next. |
| **The rare tip** | `static/js/flight-tips.js` (`RARE`) | About one page in fifty starts on it. |
| **Downtime nod** | `static/js/easter-eggs.js` (`footerLine`) | Between 11:00 and 11:30 UTC the footer tip mentions daily downtime. |
| **New Eden's birthday** | `static/js/easter-eggs.js` (`footerLine`) | On 6 May (UTC), the day EVE launched in 2003, the footer tip says happy birthday. |
| **April Fools, holidays, New Year** | `static/js/easter-eggs.js` (`footerLine`) | On 1 April, 24–26 December and 1 January (UTC) the footer tip has a line for the day. |
| **o7** | `static/js/easter-eggs.js` | Type o7 anywhere outside a text field, like you would in local. |
| **Make up your mind** | `static/js/easter-eggs.js` | Flip the theme six times within eight seconds. |
| **An hour of planning** | `static/js/easter-eggs.js` | Leave one page open for an hour. Shown once. |
| **Konami code** | `static/js/easter-eggs.js` | Type ↑ ↑ ↓ ↓ ← → ← → B A outside a text field. A short toast says CONCORD has been notified. |
| **o7 from the logo** | `static/js/easter-eggs.js` | Click the small AstraCore wordmark in the footer five times quickly. |
| **YC year** | `templates/base.html` footer | Hover the year in the copyright line: it's YC 128 in New Eden (year − 1898). Update it with the © year. |
| **Not on your overview** | `templates/error.html` | Hover the big 404 on a missing page. |
| **Console greeting** | `static/js/easter-eggs.js` | Open the browser console. |
