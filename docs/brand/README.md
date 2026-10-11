# AstraCore brand

The production brand of AstraCore. The MVP look (Pico, navy and cyan, rounded cards) is retired.

- **Live design system** (tokens, component previews, assets, in both themes):
  https://claude.ai/artifact/EHW9iBXwWTsYgSPknnfyDB (private; share it from its Share menu).
- [`brand-book.md`](brand-book.md): audience, naming, voice, logo rules, colour, type, shape, numbers, icons, imagery, motion,
  accessibility, co-branding with Dutch Legions and Insidious.
- [`tokens.json`](tokens.json): every token with both theme values (Hull = dark, Chart = light) and a usage note.
- [`logos/`](logos/): master SVGs and `generate.py`, which draws them.
- Orbital Command is the approved composition: a static platform hero, available PI story, real product walkthrough, and clearly marked community directions.
- `static/img/brand/orbital-command/manifest.json` records selected artwork dimensions, responsive variants and original generated provenance. Marketing illustrations remain separate from official EVE game imagery.
- The source kit is `assets for possible usage/orbital-command/` (local, excluded from Git). The served general cover is `static/img/share-card.png`, copied from `brand/social/platform-og.png`; PI uses `static/img/brand/orbital-command/pi-og.png`. Editable SVGs remain in the source kit. `social-card.svg` and its generator preserve the previous PI cover for reference.
- `static/css/orbital-command.css` extends shared page styles for marketing bands, compact context headers, grouped dashboard readouts and responsive artwork. Both theme tokens remain authoritative.

## In the app

- `src/astracore/static/css/astracore.css` defines the brand and shared components. `layout.css` supplies page rhythm; module styles extend those shared tokens. Tokens are CSS custom properties on `:root`
  (`--void`, `--hull`, `--signal`…); `data-theme="light"` switches to Chart. It keeps the app's existing class names
  (`.box`, `.card`, `.pill`, `.flash`…) and restyles them, so templates rarely need brand-specific markup.
- Fonts are self-hosted in `src/astracore/static/fonts/` (the CSP allows only `'self'`).
- Never use colour literals in templates. Orange (`--signal`) is for the one thing to act on per screen.
- When the brand changes, update the design system artifact, `docs/brand/` and `astracore.css` together.
- The public introduction is also available at `/about` while signed in. Its PI walkthrough stays separate from saved planner preferences.
