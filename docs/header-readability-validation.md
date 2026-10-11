# Header readability validation

Validated on 11 October 2026 in authenticated production Chrome.

The guided planner placed its Advanced link over the artwork: at 1470px the link
occupied x=1125–1359 while the artwork occupied x=1071–1391. The header's flex
override bypassed the shared reserved content area. The link now belongs to the
planning copy, and that header uses the shared padding reservation. Shared context
headers constrain content to available width and allow long labels to wrap.

## Verification

- 80 browser geometry checks found no header content/artwork intersections or horizontal
  page overflow. Dashboard, Operate, advanced planner, Area, Settings, profile, onboarding,
  credits, contribution, idea feedback and roadmap were checked at 1470px, 800px and 320px
  in both themes. The guided planner was checked at 1470px, 1024px, 800px, 761px, 760px,
  390px and 320px in both themes.
- Visually inspected the guided planner on desktop, at the narrowest artwork width
  (761px), and on a 320px phone. Its link sits on an opaque surface; artwork is hidden
  at 760px and below. The original navigation icon is unchanged.
- Calculated the Advanced link's contrast from computed text/surface colours:
  9.32:1 in Hull and 4.95:1 in Chart. Keyboard activation opens the existing advanced
  planner correctly. No planner answers or saved preferences were edited.
- All 153 Python tests passed. Release metadata, JavaScript audit syntax and whitespace
  checks passed. This change does not modify the PI engine, authentication or permissions.

## Repeatable browser audit

Evaluate `scripts/audit_context_headers.js` in the browser on each affected route,
theme and viewport. The result lists inspected headers and any content/artwork overlap
or horizontal overflow. Check that the expected header appears in `headers`, and require
an empty `failures` list. The script only reads rendered geometry; it changes no state.
Browser MCP evaluation can require omitting its final semicolon.

After the geometry audit, inspect representative screenshots and verify the visible
foreground/background contrast. Geometry alone cannot assess contrast, focus indicators
or whether a decorative crop looks right. This audit is a browser verification procedure;
CI does not launch a real renderer.

The connection-only PI entry header was not reachable with the owner's already connected
characters; its template is covered by the isolated application tests. No production data
was altered to force that state. Public headers were inspected in the owner's signed-in
session; authentication rendering was not changed by this fix.

Screenshots and the local JSON audit are under `docs/audits/header-readability/`, excluded
from Git so account context is not published in the repository.
