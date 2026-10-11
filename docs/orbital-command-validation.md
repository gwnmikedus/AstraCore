# Orbital Command validation

Validated on 11 October 2026 against the running production application at
`https://astracore.hoppyhome.nl/`, using the owner's authenticated Chrome session.
Templates and static assets are served from this checkout. Anonymous browser checks
used the same running server through its localhost origin, without production cookies.

## Rendered application

- Inspected the platform introduction at `/about`, signed-in dashboard, guided and
  advanced PI planners, Operate, area, settings, welcome, profile, roadmap, contribution,
  feedback and credits pages. Checked Hull and Chart themes, 1366 px desktop, 1920 px
  marketing composition, and 320–390 px narrow layouts. Checked document widths;
  intentional table scrolling stays inside its container.
- Inspected the dedicated portrait hero, desktop station crop, PI artwork, community
  directions, warm explanatory band and both 1200 × 630 social covers. Labels, controls,
  numbers and actual EVE schematics remain HTML or existing official game assets.
- Exercised public preview choices and walkthrough tabs. Their examples remain clearly
  illustrative. Fittings and fleet cards lead to the existing idea flow.
- Verified the real dashboard's incomplete-build action and Operate plan progress and
  template link. Inspected live planner comparisons, net income, effort and hauling
  advice. No plans, wizard answers, account permissions or community content were
  deliberately submitted or changed. PI settings matched the values recorded before
  inspection. Normal planner initialization can still persist its current view state.
- Checked keyboard menu opening, Escape dismissal and focus restoration. Existing
  navigation and walkthrough tests cover outside dismissal, focus handling and reduced
  motion. The primary marketing copy stays still; decorative scroll motion is covered by the
  subsequent motion regression checks. The existing global reduced-motion
  CSS remains in place. An OS-level reduced-motion preference was not changed during QA.
- Verified useful script-free public behavior through a temporary localhost-only GET
  proxy that omitted script elements from the real server's responses: native menu,
  FAQ disclosures and the correct login action. This checks the native fallback without
  changing Chrome's JavaScript settings. Guided planner calculations still require their
  existing JavaScript. The proxy was stopped after testing.
- Checked application console output and content-hashed image URLs. No application
  errors were observed; unrelated browser-extension messages were excluded.

Screenshots of the actual application are retained locally under
`docs/audits/orbital-command/`. They are excluded from Git because signed-in captures
can contain private operation data.

## Automated checks

- Python suite: 153 tests, including dashboard setup/partial-build/completed-build state
  regression coverage and responsive asset hashing, content types and immutable delivery.
- Browser helper suite: 33 tests, including planner sliders, navigation, walkthrough and
  other existing interaction behavior.
- Release metadata and `v1.2.0` consistency checks; whitespace/diff checks.
- Required GitHub checks must pass before the protected `main` branch is squash-merged.

## Product boundaries

PI remains the available module. Other operation areas are community directions, with
no availability dates or new permissions. Forecasts retain their existing yield, price,
tax and hauling assumptions. Authentication, account data, backend calculations, ESI
scopes, database migrations and feedback submission behavior were not changed.

The released process must be restarted after merging to load packaged v1.2.0 metadata;
templates and image checks alone do not establish the running release version.
