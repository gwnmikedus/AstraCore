# Touch navigation and safe-area validation

Validated on 11 October 2026 against the real authenticated deployment in Chrome.

Navigation now handles primary touch release once, ignoring the resulting compatibility
click. Movement beyond 12px and cancelled gestures do not activate it. Keyboard and mouse
retain their existing click path. Focus restoration uses `preventScroll`.

Desktop widths from 1080px reserve a 96px navigation gutter; the landing hero stays outside
it. Smaller screens keep the existing content width. After the header leaves view, a
non-interactive gradient blends from the viewport's top edge through the safe area and
around the toggle. The page opts into `viewport-fit=cover` and pads the shell for screen
cutouts. This replaces the bounded gradient that could start below iPhone browser chrome.
The original 28px icon, 48px button, top-of-page Menu caption and expanded Close caption
remain unchanged.

## Verification

- Native Chrome device-emulator input opened the menu on the first tap and closed it on
  the next, at the page top and after scrolling. Accessible expanded state matched.
- 96 rendered geometry checks covered dashboard, advanced planner, Operate, Area,
  Settings, profile, roadmap and credits at 320, 390, 1079, 1080, 1366 and 1920px in both
  themes. No header text/artwork intersections, horizontal overflow, changed button/icon
  dimensions or desktop toggle/content intersections were found.
- Additional 390px checks covered onboarding, guided planning, contribution and idea
  feedback. No failures were found. No planner answers or account data were edited.
- The mobile pane retained its normal width (375px in a 390px desktop Chrome viewport
  reserving a 15px scrollbar). No navigation gutter applies below 1080px.
- Keyboard Enter opened navigation; Escape closed it and restored toggle focus. Opening
  and closing at a settled scroll position preserved the scroll position exactly.
- 153 isolated Python tests and 42 browser helper unit tests passed. Touch tests cover
  compatibility clicks, absent compatibility clicks, cancelled/scrolling/secondary touches,
  rapid reopening and keyboard/mouse input following touch. Release and whitespace checks
  passed.

## Repeatable checks and limits

Run `scripts/audit_context_headers.js` in each affected browser/theme/viewport and require
an empty failures list. It now checks navigation dimensions and the desktop gutter as well
as header readability. Follow geometry checks with visual and input inspection.

Screenshots and the JSON audit are saved locally under `docs/audits/touch-navigation/`,
excluded from Git to keep account context out of the public repository.

Chrome emulation does not reproduce physical iPhone Safari's status bar, dynamic browser
bars, nonzero safe-area insets or touch event implementation. The owner's iPhone screenshot
was used to correct the top-edge treatment; a physical Safari recheck is still needed to
confirm that device's final appearance. Public surfaces were inspected in the signed-in
session; anonymous rendering remains covered by isolated application tests. No production
account was logged out or changed for verification.

## Safari edge follow-up (1.2.4)

A second physical iPhone screenshot still showed page content behind Safari's status bar
and a seam where the page's gradient began. Live asset URLs matched the files on disk;
this was not treated as proof of a stale browser cache. Production was restarted on 1.2.3
before preparing this follow-up.

WebKit's [viewport-edge colour explanation](https://bugs.webkit.org/show_bug.cgi?id=301756)
describes an opaque fixed/sticky edge as the source for an extended browser tint. A
background gradient alone does not supply an opaque `background-color`. The page now has
an explicit, non-interactive fixed edge in `void`, 14px plus the top safe inset in height.
The fade is fully opaque across the same height before blending away. This provides the
browser's sample colour without a visible boundary or an additional content gutter.

Ten further Chrome checks covered 320, 390, 1079, 1080 and 1366px in both themes without
geometry failures. At a settled scrolled position, the active edge was separately checked
in each theme: top/left 0, full viewport content width, 14px with zero Chrome safe inset,
opaque colour matching the body, and no pointer events. The expanded audit validates these
properties on scrolled mobile pages. All 153 Python tests passed again; release and
whitespace checks passed. The physical Safari limitation above still applies: its final
status-bar tint cannot be confirmed with Chrome emulation.
