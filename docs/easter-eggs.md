# Easter eggs

AstraCore has a few small jokes for capsuleers. **They are intentional.** Please don't remove them in a copy or
cleanup pass; `tests/test_easter_eggs.cjs` and `tests/test_easter_eggs.py` fail if one disappears. If one has to
go, remove it here and in the tests in the same pull request, and say why.

## Capsuleer's logbook

Finding an egg counts. The first time each one is found, a short notice says so and gives the count ("Logbook: 4 of 15").
Signed in, finds are stored per profile (`core/logbook.py`, tables `logbook_finds` and `logbook_ranking`, migration v10);
signed out, they stay in the browser (`localStorage` key `ac_logbook`) and are added to the profile on the next signed-in visit.

- **Pointers:** the footer says "Rumour has it 15 things are hidden in AstraCore" until the first find, then counts. Four footer
  tips hint at eggs without giving them away.
- **The logbook** (`/logbook`, `templates/logbook.html`) is hidden (a 404) until a signed-in pilot has found 3. It lists their
  finds, a hint for every egg still missing, who found each one first and a ranking by points.
- **The ranking is opt-in:** a pilot picks one of their own characters on the logbook page. Removing that character, choosing
  "Nobody" or resetting the profile takes them off. Pilots who don't opt in are only counted ("3 pilots hunt in private").
- **Points:** 1 for the easy ones, 2 and 3 for harder ones, 5 for the calendar eggs, which the server only accepts on their day.
  Finds are reported by the browser, so the ranking is a game, not proof.
- Adding or removing an egg: change `EGGS` in `core/logbook.py` and `EGGS` in `static/js/easter-eggs.js` together (a test
  compares them), and the "Fifteen" in the hint tip.

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
| **Console greeting** | `static/js/easter-eggs.js` | Open the browser console and type `o7()`. |
