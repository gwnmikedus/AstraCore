# AstraCore brand

The production brand of AstraCore. The MVP look (Pico, navy and cyan, rounded cards) is retired.

- **Live design system** (tokens, component previews, assets, in both themes):
  https://claude.ai/artifact/EHW9iBXwWTsYgSPknnfyDB (private; share it from its Share menu).
- [`brand-book.md`](brand-book.md): audience, naming, voice, logo rules, colour, type, shape, numbers, icons, imagery, motion,
  accessibility, co-branding with Dutch Legions and Insidious.
- [`tokens.json`](tokens.json): every token with both theme values (Hull = dark, Chart = light) and a usage note.
- [`logos/`](logos/): master SVGs and `generate.py`, which draws them.

## In the app

- `src/astracore/static/css/astracore.css` is the only stylesheet. Tokens are CSS custom properties on `:root`
  (`--void`, `--hull`, `--signal`…); `data-theme="light"` switches to Chart. It keeps the app's existing class names
  (`.box`, `.card`, `.pill`, `.flash`…) and restyles them, so templates rarely need brand-specific markup.
- Fonts are self-hosted in `src/astracore/static/fonts/` (the CSP allows only `'self'`).
- Never use colour literals in templates. Orange (`--signal`) is for the one thing to act on per screen.
- When the brand changes, update the design system artifact, `docs/brand/` and `astracore.css` together.
