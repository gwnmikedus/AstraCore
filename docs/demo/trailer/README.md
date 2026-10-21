# AstraCore PI trailer

A 60-second cinematic trailer for the home page ([#216](https://github.com/gwnmikedus/AstraCore/issues/216)). It sells the
idea rather than every feature: setting up PI is the chore everyone hates, AstraCore's guided setup makes it the
easy part, and Operate keeps watch afterwards. The home hero plays it live, edge to edge and without sound: the
scenes are drawn in code by a small player, so there is no video to download.

Everything on screen is fictional or illustrative: Demo Pilot Aurora, Beacon and Corvid, Demo Harbour, Demo Coast
and every figure are examples, labelled "Example data" or "Example figures" in the film. The plan scene keeps the
"Yield is an estimate" warning visible. Templates are credited to DalShooth (AstraCore never authors them) and the
end card says AstraCore is an independent fan-made tool and that EVE Online belongs to CCP. No production capture,
account data or CCP artwork is used: space, planets and maps are drawn in code.

## Story

| Time | Scene | On screen |
|---|---|---|
| 0:00 | Cold open | A terminal opens `pi_setup_v7_FINAL.xlsx`: tabs of questions and a `#REF!` |
| 0:03 | The spreadsheet | Setup questions fly past in depth: "Everybody hates setting up PI" |
| 0:07 | The promise | "What if setup was the fun part?" |
| 0:11 | Meet AstraCore | Guided Planetary Industry setup for EVE pilots |
| 0:14 | Your pilots | Characters with colony slots and PI skills, read from EVE |
| 0:19 | Your goal | The guided setup: *What do you want from PI?*, Balanced is picked |
| 0:25 | A few questions | Logins, area, products and selling with the wizard's real options: "Five questions. No spreadsheet." |
| 0:31 | Your space | A star map with the operating area and drop-off |
| 0:36 | Your plan | ISK per week, time per week, hauling and colonies, with the estimate warning |
| 0:42 | Build it | DalShooth templates matched to the plan and a three-step build list |
| 0:47 | It keeps watch | A planet's extractor links light up |
| 0:51 | Next action | Operate's Next up panel locks onto the next action |
| 0:55 | AstraCore PI | "PI setup, without the spreadsheet." with the address and credits |

The score is generated with the film (no samples): a tense drone, relief at the promise, a light groove under the
wizard and one big hit on the end card.

## Files

- [`film/`](film) is the film's source as written for the Motion player: `scenes.json` (order, length, palette and
  fonts), `base.css`, `shared.js` (the shared starfield, planet and wizard stepper), one `scene-*.js` per scene and
  `score.js`. Every frame is a pure function of time, so the same source always renders the same film.
- `scripts/trailer/build_hero_film.py` bundles the scenes for the home hero: `src/astracore/static/js/hero-film-scenes.js`
  and the stage styles in `src/astracore/static/css/hero-film.css`. `src/astracore/static/js/hero-film.js` is the
  player (timing helpers, word fades, the typed line and the demo pointer). The score isn't bundled.

## Updating the hero

Replace the files in `film/` with the Motion artifact's current modules whenever the film changes, then run:

```bash
python scripts/trailer/build_hero_film.py
```

It rewrites the scenes' inline `style="..."` attributes as `data-css` (the player applies them through CSSOM, as the
site's content security policy forbids style attributes) and scopes `base.css` to the hero's stage.
`tests/test_hero_film.py` fails while the bundle is out of date. Reduced motion shows the end card; the pause button
stops the film and is remembered in the browser.

`scripts/trailer/transcode.swift` and `poster.swift` still make a 1280×720 MP4 and a poster from the artifact's
**Export → MP4** if a video copy is ever needed elsewhere; the site no longer serves one.
