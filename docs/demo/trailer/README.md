# AstraCore PI trailer

A 60-second cinematic trailer for the home page ([#216](https://github.com/gwnmikedus/AstraCore/issues/216)). It sells the
idea rather than every feature: setting up PI is the chore everyone hates, AstraCore's guided setup makes it the
easy part, and Operate keeps watch afterwards. The home hero shows a poster card that opens the film in a dialog.

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
- `src/astracore/static/video/astracore-trailer.mp4` is the web copy: 1280×720 H.264 at 2.5 Mbit/s with AAC audio
  and fast start, about 19 MB.
- `src/astracore/static/img/trailer/trailer-poster-1280.jpg` is the poster, taken from the end card.

## Rebuilding the web copy

The maintainer edits the film in a private Motion artifact and exports a 1920×1080 MP4 from its Export button.
Then, on macOS (no FFmpeg needed):

```bash
swiftc -O scripts/trailer/transcode.swift -o /tmp/trailer-transcode
/tmp/trailer-transcode ~/Downloads/astracore-pi-trailer.mp4 src/astracore/static/video/astracore-trailer.mp4 1280 720 2500000
swiftc -O scripts/trailer/poster.swift -o /tmp/trailer-poster
/tmp/trailer-poster ~/Downloads/astracore-pi-trailer.mp4 58 /tmp/trailer-poster.png
sips -s format jpeg -s formatOptions 78 -Z 1280 /tmp/trailer-poster.png --out src/astracore/static/img/trailer/trailer-poster-1280.jpg
```

Replace the files in `film/` with the artifact's current modules whenever the film changes, so the repository keeps
the source of what is shown.
