# Motion and navigation validation

Validated on 11 October 2026 against the running production site through authenticated
Chrome. This update makes the existing section entrances perceptible and adds decorative
scroll parallax while retaining stable text, controls and operation data.

- Observed a marketing entrance in the real renderer: opacity began at 0.35 with a 24px
  offset, then progressed toward its settled state. Marketing entrances last 650ms;
  application entrances last 300ms. Sections containing keyboard focus are skipped.
- Measured the hero artwork's offset changing from 1.36px to its bounded 48px displacement
  after scrolling. The headline and actions do not receive parallax. On phones travel is
  limited to 12px; desktop story/card artwork is limited to 24px.
- Verified the visible Menu caption below the unchanged icon at the top on desktop and
  320–390px layouts, its compact
  scrolled state, Close text when opened while scrolled, Escape dismissal and focus
  restoration, and navigation from the menu back to the platform introduction.
- Inspected Hull and Chart mobile layouts and the supplied portrait crop. No horizontal
  page overflow was observed. Operate has no parallax targets and retains its readable
  controls, plan progress, template link and data. No saved preferences were edited.
- Verified script-free public content and the labeled native disclosure through the
  temporary localhost-only GET proxy described in the Orbital Command validation report.
  The proxy was stopped afterward. No application console errors were observed.
- All 153 Python tests and 38 browser-helper tests passed, along with release metadata and
  whitespace checks. New behavior tests exercise frame coalescing, bounded offsets,
  offscreen updates, hidden-tab suspension, smaller mobile travel, reduced-motion cleanup
  and restoration, focus preservation, and header visibility without changing menu state.

Reduced-motion behavior is regression-tested, including changing the preference while
motion is active. The owner's OS preference was not changed during browser inspection.
Content is never pre-hidden, and native navigation stays available without JavaScript.

Local screenshots are under `docs/audits/orbital-command-motion/` and are excluded from
Git. A still image shows menu discoverability and image crops; the live `/about` page is
the useful place to assess scroll motion.
