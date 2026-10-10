# AstraCore brand book

AstraCore is a command center for EVE Online pilots who run more than one character. It reads your characters from ESI and turns them into plans you can fly: what to build, where to haul, what to train next. The brand should feel like ship equipment, not a SaaS dashboard: a dark hull, one hot orange core, hard 45° cuts and numbers you can trust.

## Who it is for

Capsuleers of **Dutch Legions** and the **Insidious.** alliance, mostly running two to ten alts, comfortable with spreadsheets and EVE's own UI. They know the game better than the app does. Write and design for someone who will notice a wrong number, a missing tax or a wasted click.

## The idea: the core

Everything in AstraCore is quiet hull, with one point of heat in the middle: the **core**. In the logo it is the orange square inside the frame and inside the O of the wordmark. On a screen it is the one thing the pilot should act on: the primary button, the current step, the recommended option, the live figure. If a screen has three orange things, it has no core.

## Name and modules

- Write **AstraCore**: one word, capital A and C. Never "Astracore", "Astra Core" or "ASTRACORE" in running text (the wordmark is uppercase; prose is not).
- Modules are **AstraCore + a plain name**: AstraCore PI today; later AstraCore Skills, Logistics, Industry, Market, Intel, Fleet. Inside the app, drop the prefix: "PI", "Skills".
- Each module has a **code** set in `label` inside an `ac-tag--code`: PI, SKL, LOG, IND, MKT, INT, FLT. Codes lead panel heads and nav tabs that belong to a module.
- Each module has a **glyph**: the frame of the mark with a different core shape. PI is a disc (a planet). The platform itself is the square. New modules get one simple solid shape (diamond, triangle, bar), always `signal`.

## Voice

AstraCore talks like a good fleet logistics officer: short, specific, calm, a bit dry. It assumes competence.

- **Second person, active, plain.** "Restart the extractors on Tash-Murkon V before downtime." Not "It is recommended that extractors be restarted."
- **Numbers first, and real.** Every ISK figure is after customs tax, broker fees and sales tax; say so once, then just give the number. "48.2M ISK/day", not "great returns".
- **EVE words, used correctly.** Capsuleer, pilot, alt, ISK, ESI, CCU, ECU, P0–P4, Jita 4-4, haul, courier contract, downtime. Don't explain them unless the pilot asks.
- **Sentence case** everywhere in source text. Labels, tabs, tags and buttons are uppercased by CSS (`label` style), never typed in caps.
- **No hype, no emoji, no exclamation marks.** No "supercharge", "unlock", "seamless", "AI-powered". No "Oops!". Errors say what happened and the fix: "Mira Vantor's EVE login expired. Log in again to keep her planets in the plan."
- **Trust lines are literal.** "Read-only by default. We only change something in your game if you switch on Send routes to EVE for a character."
- **Dutch audience, English product.** UI copy is English (EVE's lingua franca). A Dutch aside is fine in community posts, never in the UI.

| Write | Not |
| --- | --- |
| Build this plan | Let's get started! |
| 3 extractors stop in 6 hours | Heads up: some of your stuff needs attention |
| Needs login | Error 401 |
| Skip for now | Maybe later 🙂 |

## Logo

The mark is a square **frame with two cut corners** (top-right, bottom-left: the same 45° cut the UI uses) around a solid **core**. The wordmark is custom chamfered lettering; its O carries the same core. Files are in the Logos asset group.

- Use the **wordmark** wherever the name needs to be read: the top bar, the landing page, social cards. Use the **mark** alone where space is square: favicon, app icon, avatars, loading states.
- **Never set the mark beside the wordmark.** The O already holds the core; two cores compete.
- Clear space: the height of the wordmark on all sides. Minimum size: wordmark 12px tall, mark 16px.
- On `void`/`hull` (Hull theme) use the `-on-dark` files; on Chart grounds the `-on-light` files. Mono files for one-colour print, engraving and in-game bios.
- The core is always `#ff6a1a` (`signal` at full strength) in colour versions, on both grounds.
- Don't: round the frame, rotate it, outline the core, add a glow or gradient, recolour the frame orange, or place it on a photo without a `void` plate.

## Color

Two themes. **Hull** (dark) is the default and the brand's home; **Chart** (light, warm paper) is for daylight use and print. Every token has a value in both.

- Grounds: page on `void`; content on `hull`; lifted things (menus, hovered rows, table heads) on `hull-raised`. Edges are `line` (decorative) and `line-strong` (controls, 3:1).
- Text: `ink` for everything that matters, `ink-muted` for labels and meta, `ink-faint` only for disabled and placeholders.
- **`signal` is the core.** Primary button, current step, active tab underline, selected option, the mark's core. One or two per screen. Text on a `signal` fill is `on-signal`.
- **`scan`** is the cold second voice: links inside prose, a second chart series, "you are here". Never a button.
- **Status is blue/amber/red, and always worded.** `status-ok` is deliberately blue, so good and bad never depend on red/green vision. `status-danger` sits close to `signal` in lightness; that is acceptable only because every danger state carries a word and an icon. Text on status fills is `on-status`.
- No gradients. No translucent glass. The only shadow is `shadow-lift`, for floating layers.

## Typography

Three families, all on Google Fonts:

- **Barlow Condensed** (`display`): headings, titles, and the uppercase `label` style for tabs, tags, buttons and table headers. Its narrow, engineered shapes are the closest open match to EVE's own UI type.
- **Barlow** (`sans`): all running text in `body`, `body-strong`, `small`.
- **IBM Plex Mono** (`mono`): every number a pilot compares: `figure-xl` for readouts, `figure` in tables and metrics, `code` for scopes and pasted in-game text. Numbers are tabular and right-aligned in columns.

Rules: headings in sentence case; `label` in uppercase with its 0.12em tracking; no italics in UI; one `display-xl` per page at most. The landing display scales from 54px on phones to 88px on desktop. The root size is 15px.

## Shape: cuts, not curves

- **Nothing is rounded.** `radius-0` everywhere; `radius-dot` only for the 8px live dot.
- **The chamfer** is the signature: cut the top-right and bottom-left corners of panels (`chamfer-md`), readouts and option cards (`chamfer-sm`), hero blocks and large images (`chamfer-lg`). Use `.ac-chamfer`, which redraws the hairline across both cuts. Buttons, inputs and tags stay square (their focus rings must not be clipped).
- **Hairlines, not shadows.** Panels are `hull` with a 1px `line` frame on `void`. Selected things get a `signal` edge; current tabs a 2px `signal` underline (`stroke-bar`).

## Layout and spacing

- A 4px grid: `space-1` to `space-12`. Panels pad `space-6` (desktop) / `space-4` (phone) and sit `space-6` apart; sections `space-8`; major bands `space-12`.
- Content max width `container`; planner pages use a fixed `rail` on the left for controls and a fluid result column.
- Controls are `control-h` tall; the top bar is `bar-h`.
- Density is a feature: pilots compare a lot of numbers. Prefer a table to a grid of cards when there are more than six of something.

## Numbers

- ISK: full with thousands separators in tables (`9,812,400`); abbreviated in readouts (`48.2M`, `1.32B`), one decimal. Always say the unit once per block ("ISK/day").
- Time: `6h 12m`, `3d 4h`; EVE time (UTC) when it refers to downtime or contracts.
- Deltas lead with ▲, ▼ or — and use `status-ok` / `status-danger` / `ink-muted`.
- Never show a number you would not defend; when data is stale, say how stale ("last ESI refresh 3 days ago").

## Iconography

- **Lucide** (ISC) for interface icons: the Icons asset group holds the app's set. Inline them as SVG so they take `currentColor`; size 16px (`.ac-ic`) next to text, stroke 1.75. Icons lead their label; icon-only buttons need an `aria-label`.
- **EVE's own icons** for anything that exists in the game: item and commodity icons, planet types, ship renders, corporation and alliance logos, all from the EVE Image Server (`images.evetech.net`). Show them square, never cropped round, at 24/32/64px.
- No emoji, no illustrations of people, no stock space art.

## Imagery

- Only CCP's own images (ships, structures, planets) on `void` or in a `chamfer-lg` frame. They are credited in the footer: "EVE Online and all related images are © CCP hf., used under the EVE Developer License."
- No AI-generated nebulae, no lens flares, no gradient space backgrounds. Space is black; the hull is graphite.
- Compose the EVE assets into equipment views: orbital network diagrams, production chains, and labelled ship plates. Diagrams are explicitly illustrations; income figures only come from the planner. The public preview shows operational trade-offs without inventing ISK forecasts.
- The share cover uses the actual wordmark, outlined Barlow and IBM Plex Mono, theme tokens, and bundled EVE planets. Its editable source and generator live beside this book.

## Motion

Instrument-like and short: 120ms linear for colour changes, 200ms ease-out for bars filling and panels opening. Nothing bounces, nothing floats on hover (no `translateY` lifts). Progress bars fill; numbers do not count up. The public hero tells the operation in four scenes: every character and colony system, a valid P1–P2–P3 production plan, the next operating actions and consolidated pickup, then the selected sale route. Give each scene ten seconds; its headline and artwork change together with a 550ms gradient reveal and restrained crossfade. Keep the call to action and scene frame stable. Feature tabs, keyboard navigation, and pause/resume give the pilot control; choosing a feature stops automatic advancement. Pause advancement during focus and stop motion when offscreen or the document is hidden. Routes follow actual source and destination ports across desktop and mobile layouts, with cargo completing one leg before the next begins. Use real schematics, valid planet resources, and supported courier destinations; label illustrative systems, player actions, and compressed time. The selling scene offers Jita, Amarr, and local RF-K9W routes; the local route bypasses the jump freighter. It never implies live ESI activity. Respect `prefers-reduced-motion` by disabling automatic advancement, transitions, animations, and smooth scrolling. The first scene and primary action remain visible without JavaScript.

Navigation uses the AstraCore mark as a 48px disclosure control on every page. The frame turns, the orange core resolves into a close mark, and the menu reveals over a softened backdrop in 320ms; closing takes 180ms. Keep the wordmark as a separate home link. Group operation, account, and information links, mark the current page, and preserve the same header dimensions on mobile. The native disclosure remains usable without JavaScript. Escape restores focus to the icon; outside clicks and keyboard focus leaving the menu dismiss it. Short viewports scroll within the menu, and reduced motion removes the reveal and mark animation.

## States and focus

The header always exposes theme switching beside the profile or login action. A sun invites Chart (light); a moon invites Hull (dark). Rotate and crossfade the icons while page colours settle in 350ms, preserve the choice across pages and tabs, and remove all motion for reduced-motion preferences. Keep both controls separate from the navigation disclosure.

The introduction and credits pages lead with the people building AstraCore. Show public GitHub contributors with avatars and profile links in alphabetical order, using the shared surface, border, typography and focus tokens. Avoid commit-count rankings: code, documentation, testing, ideas and bug reports all help the project. Link to the contribution guide and GitHub discussion so newcomers have a clear way to join.

The origin plate follows the contributor showcase and introduces CosmicCarrot as the founding capsuleer with the official EVE portrait and verified corporation/alliance names. Keep its coffee and permanent-hosting contributions optional, link both to the same Revolut destination, and describe hosting as a funding goal while the app still runs from the founder's own machine. Use the same plate on the introduction and credits pages; the footer carries a compact contributor link and support action. Keep the existing `/credits#creator` link available for the origin story.

- Hover: edges step from `line` to `line-strong`; secondary buttons fill `hull-raised`; primary goes `signal-strong`.
- Selected: `signal-tint` fill plus a `signal` edge or bar.
- Disabled: `ink-faint` on `hull-raised`, no edge.
- **Focus:** a solid 2px `focus` ring (`signal`) with a 2px offset on every interactive element; inside a chamfered card it is drawn as an inset ring so the cut cannot clip it. It holds at least 3:1 on `void`, `hull` and `hull-raised` in both themes.

## Accessibility

All text pairs named in token notes are at least 4.5:1 in both themes; `line-strong`, icons and the focus ring at least 3:1. Status always has a word and an icon. Touch targets are at least `control-h` (36px) with `space-2` between them; on phones primary actions grow to 44px.

## Co-branding with Dutch Legions and Insidious.

AstraCore is built for these pilots, but it is not their official tool. Show the corporation and alliance logos (Partners asset group, from the EVE Image Server) only as membership marks: "Open to members of Dutch Legions and Insidious." at the size of a 32px portrait, after the AstraCore wordmark, never merged with it, never recoloured, never larger than it.

## Replacing the MVP styles

The current app (Pico + `astracore.css`, navy and cyan, rounded cards, pills and left-border alerts) is the MVP look and is retired by this system. Map old to new when migrating: `--ac-bg` → `void`, `--ac-surface` → `hull`, `--ac-surface-2` → `hull-raised`, `--ac-border` → `line`, `--ac-text` → `ink`, `--ac-muted` → `ink-muted`, `--ac-accent` → `signal` (primary actions) or `scan` (links), `--ac-gold` → `signal`, `--ac-ok`/`--ac-warn`/`--ac-bad` → `status-ok`/`status-warn`/`status-danger`, `--ac-radius` → `radius-0` plus `.ac-chamfer`. `.pill`, `.status` and `.badge` become `ac-tag`; `.flash` and `.warnbox` become `ac-notice`; `.card` becomes `ac-readout`; `.page-guide .opt` becomes `ac-option`; `.track` becomes `ac-steps`. Drop Pico rather than re-theming it.
