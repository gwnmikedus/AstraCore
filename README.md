# AstraCore

One EVE Online login, one profile, several tools ("modules"). v1 ships one module, **AstraCore PI**: it plans
Planetary Interaction for **all your characters across several systems** at once, weighs ISK against your time,
and runs it day to day from **Operate**.

Source and contributions: [gwnmikedus/AstraCore](https://github.com/gwnmikedus/AstraCore).
Report bugs or suggest improvements through [GitHub Issues](https://github.com/gwnmikedus/AstraCore/issues/new/choose).
Read [CONTRIBUTING.md](CONTRIBUTING.md) for setup and pull requests, [SECURITY.md](SECURITY.md) for private vulnerability reports,
and [docs/releases.md](docs/releases.md) for versioning and release notes.

The original software is **source available under PolyForm Noncommercial 1.0.0**. Noncommercial use, modification
and distribution are permitted subject to [LICENSE](LICENSE) and [NOTICE](NOTICE); commercial rights are not granted.
This is not an OSI-approved open-source license. EVE materials and other third-party assets retain their own terms
listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The public `/roadmap`, `/project` and `/releases` pages are available without signing in.
Signed-in users can preview and submit ideas or bugs at `/feedback`. Public GitHub issue status
is synchronized without credentials; publishing platform reports requires an Issues read/write
GitHub App installed on this repository, configured using the fields in `docs/env.example`.
Polling defaults to five minutes. A signed Issues webhook is optional; leave it inactive until
its shared secret is configured. Reports remain private and withdrawable while queued.

The site runs on a Mac and is published at `https://astracore.hoppyhome.nl` through a Cloudflare Tunnel, only
while that Mac runs it. Anyone with the URL can log in (an invite list gates production), so profiles are
fully separated, sessions are server-side, and EVE tokens are encrypted at rest.

## Quick start (fresh clone, local mode)

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[test]"
cp docs/env.example .env.local           # then fill in your own values, see "Env files"
chmod 600 .env.local
./astracore start                        # http://localhost:8765
```

Open <http://localhost:8765>, log in with EVE, and follow the onboarding. `./astracore stop` stops it.
Running in the foreground for development works too: `.venv/bin/python -m astracore`
(`ASTRACORE_RELOAD=1` reloads on code changes).

## Two modes

| | local (`./astracore start`) | production (`./astracore start --prod`) |
|---|---|---|
| Env file / data folder | `.env.local` / `data/local/` | `.env.production` / `data/production/` |
| URL, EVE callback | `http://localhost:8765/auth/callback` | `https://astracore.hoppyhome.nl/auth/callback` |
| EVE application | "Astracore (dev)" | "AstraCore" |
| Cloudflare tunnel | not started | started (and stopped first on `stop`) |
| Secure cookies, HSTS | off | on |
| `/docs`, debug tracebacks | on | off (branded error pages, errors in `data/logs/`) |
| Invite list | off | on |
| "LOCAL" badge in the header | yes | no |

Each mode has its own EVE application and database because EVE refresh tokens only work with the
application that issued them. Production refuses to start if its secrets are missing.

## Env files

Never commit them (`.env*` is gitignored) and keep them `chmod 600`. Keys (see `docs/env.example`):

| Key | What |
|---|---|
| `ASTRACORE_MODE` | `local` or `production` (the start script sets it too) |
| `ASTRACORE_PUBLIC_URL` | `http://localhost:8765` or `https://astracore.hoppyhome.nl` |
| `ASTRACORE_PORT`, `ASTRACORE_DATA` | `8765`, `data/local` or `data/production` |
| `EVE_CLIENT_ID`, `EVE_CLIENT_SECRET`, `EVE_CALLBACK_URL` | from developers.eveonline.com (one application per mode) |
| `ASTRACORE_TOKEN_KEY` | Fernet key that encrypts EVE tokens. **Back it up**: lose it and everyone has to log in again. Generated (with a loud warning) in local mode if missing. |
| `ASTRACORE_SESSION_SECRET` | keys the stored session ids and signed messages |
| `ASTRACORE_ADMIN_CHARACTER_IDS` | characters whose profile is the admin (admin page, VOC buyback %, invite list) |
| `ASTRACORE_ALLOWED_CHARACTERS` / `_CORPS` / `_ALLIANCES` | invite list (production); more can be added on `/admin` without a restart |
| `ASTRACORE_SOLVE_CONCURRENCY` | plans solved at the same time (default 2) |
| `CLOUDFLARE_TUNNEL_TOKEN` | production only; from the Cloudflare dashboard. Never printed or logged. |

Generate keys with `.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
and `python3 -c "import secrets; print(secrets.token_hex(32))"`.

## EVE applications

On <https://developers.eveonline.com> create one application per mode with the callback URLs above and
**every scope any bundle can request** (see `/what-we-read`; the current list: the eight `pi.required` scopes plus
`esi-planets.read_customs_offices.v1` and `esi-ui.write_waypoint.v1`). Sign-in itself asks for nothing extra:
it requests only the required bundle of the enabled modules; optional bundles are opt-in per character on the profile page.

## On / off

```bash
./astracore start --prod      # backup + migrations, app on 127.0.0.1:8765, then the tunnel; prints the URL
./astracore stop              # tunnel first (visitors get Cloudflare's offline page), then the app
./astracore status
./astracore logs
```

Without a terminal:

- **Astracore Control.app** (repo root): double-click for a small menu. It shows the current status and offers
  Start local test / Start production (asks for confirmation) / Stop / Restart / Open site / Show logs.
  It is built per Mac (`ops/app/build.sh`, also after a fresh clone) and isn't in git. Drag it to the Dock if you like;
  it keeps working from there as long as the repo stays where it was built.
- **Launchers/** folder: one double-clickable `.command` per action: `Start Astracore (local test)`,
  `Start Astracore (production)`, `Stop Astracore`, `Astracore status`, `Astracore logs`. The start ones open the site.

Only one mode runs at a time (both use port 8765): stop one before starting the other. Every start makes a
SQLite backup in `data/backups/<mode>/` (the newest 14 are kept) and runs pending migrations. PID files live in
`data/run/`, logs in `data/logs/`.

Start at login (optional, off by default): see `ops/launchd/nl.hoppyhome.astracore.plist.template`.

## Cloudflare Tunnel

The tunnel `astracore` is **dashboard-managed**: the public hostname `astracore.hoppyhome.nl → http://127.0.0.1:8765`
and its DNS record live in the Cloudflare dashboard (Zero Trust → Networks → Tunnels). There is no `config.yml` on the Mac.
It is separate from the `yams` tunnel; leave that one alone.

On a new Mac: put `cloudflared` in `bin/` (or on the PATH) and copy the tunnel token from the dashboard
(Tunnels → astracore → install command) into `.env.production` as `CLOUDFLARE_TUNNEL_TOKEN`. The start script runs
`cloudflared tunnel run` as a child process with the token in its environment. Don't use `cloudflared service install`:
that starts it at boot and breaks the on/off switch.

## Layout

```
astracore                 the on/off script
src/astracore/
  core/        auth (EVE SSO), sessions + CSRF, accounts (move/merge/reset), registry, pages, solve gate, formatting, icons
  esi/         ESI client (shared rate/error budget), SSO tokens (JWT validated against EVE's JWKS), character sync
  modules/pi/  AstracorePI: planner/, intel/, static_data/, routes, store (per-profile data), templates
  templates/   layout, home, dashboard, profile, onboarding, privacy, what we read, admin, errors
  static/      css (astracore.css, the brand stylesheet), fonts (Barlow, IBM Plex Mono), js (fmt, icons, astracore), img, icons (Lucide)
tests/
```

Adding a module: build `src/astracore/modules/<id>/`, call `registry.register(Module(...))` with its bundles,
nav, dashboard tile and reset hooks, and include its router in `app.py`. Home cards, the dashboard, the module
switcher, "What we read", sign-in scopes and resets pick it up from the registry.

## AstracorePI

1. **Log in** with your characters (profile page). Skills, slots, colonies, hangars, contracts, orders and wallet are read from ESI.
2. **Area**: your alliance's sov space and where you already have colonies, grouped by region/constellation; plus the drop-off.
3. **Plan**: one question per screen (goal, logins, area, products, planets, teamwork, selling, batches). Every answer card
   is planned live; the suggestion is the best ISK once your time is counted at what an hour is worth to you.
   The result has per-character build lists, routes, a templates zip and "How you get paid". Plans are saved per
   profile; one is the **active plan**. **Advanced** (`/pi/plan?view=advanced`) has every option on one screen.
4. **Operate**: extractors to restart, products waiting on launchpads, factories low on inputs, one "Consolidate & sell"
   card for everything in hangars, VOC contracts and sell orders in progress, and the ISK that came in vs. the active plan.

Only [DalShooth/EVE_PI_Templates](https://github.com/DalShooth/EVE_PI_Templates) templates are suggested
(`Miner - 00/LS - <P1>`, `Factory - <product>`); each template's CPU/PG is checked against every character's
Command Center Upgrades (nullsec miners CCU 4, lowsec miners 5, factories 2–3).

### Selling: VOC Hauling

- Courier tariff is read live from <https://vochauling.com>. Courier fee = max(min fee, m³ × rate + collateral × col%).
- Buyback (<https://buyback.vochauling.com>): 90% of Jita buy for P2–P4, P1 refused (appraisal at 7G-QIG, 2026-10-10).
  Instance-wide; the admin changes it on `/admin`.
- Batches whose courier fee would be eaten by the minimum fee fall back to another channel or are marked "hold".

### Model notes

- Planet richness isn't in ESI: it's estimated from security. Set it per planet on the Area page after scanning in game.
  Once 2+ of your colonies extract, richness is measured from your extractors (manual values still win).
- P0/hour/head is 1000 at richness 1.0 on a 3-day program until your characters have extractors; then it is calibrated
  with EVE's official extraction formula (<https://developers.eveonline.com/docs/guides/pi/>: bar width + decay).
  While it's an estimate, the plan's headline says so and shows the ISK at 0.5× and 2× the yield.
- Sales tax and broker fee come from the selling character's skills and standings. Customs tax is read from ESI for
  characters with the optional customs bundle switched on (needs a Director of the owning corp), otherwise the Settings value.
- A 2nd/3rd colony on the same resource on one planet counts at 70% / 49% yield (Settings).
- The engine solves a pooled integer program over (planet, template) pairs (PuLP/CBC). At most
  `ASTRACORE_SOLVE_CONCURRENCY` solves run at once; one request per profile; results are cached.

## Tests

```bash
.venv/bin/python -m pytest -q tests
node --test tests/test_ui.cjs            # shared request recovery, cancellation, queue limits
```

They never touch `data/` or the real env files. Covered: profile isolation, every login flow, scope bundles,
opt-in/opt-out, revocation on remove/reset, owner-hash changes, CSRF, cookie flags, JWT validation, the invite gate,
migration from an MVP database, the solve gate, and the planner.

## Access

Production lets in: admin characters (`ASTRACORE_ADMIN_CHARACTER_IDS`, always), everyone in **Dutch Legions** and
**Insidious.** (`ASTRACORE_ALLOWED_CORPS` / `_ALLIANCES` in `.env.production`), and whoever the admin invites on
`/admin` (characters, corporations or alliances; no restart needed). Characters already in a profile can always sign
in again; to take someone's access away, remove their profile under **People** on `/admin` (this revokes their EVE
logins) and take them off the invite list.

## Static files and caching

Every static URL the app renders carries a content hash (`/static/img/logo.svg?v=3f9a1c2b7d`, see
`core/assets.py`). Change a file and its URL changes, so browsers, phones and Cloudflare fetch the new one immediately.

- In templates, always write `{{ asset('img/x.svg') }}`, never a bare `/static/...` path. Module icons: `{{ asset(m.icon) }}`.
- In CSS, use relative `url(../fonts/x.woff2)`: the stylesheet is served with those rewritten to versioned URLs.
- Replaced an EVE image? Run `.venv/bin/python -m astracore.core.eveimg` to regenerate `static/js/eve-images.js`
  (a test fails if you forget).
- Headers: versioned files `public, max-age=31536000, immutable`; unversioned or stale-version files `no-cache`;
  pages and API `private, no-cache`; `/favicon.ico` and `/apple-touch-icon.png` `no-cache`.
- Templates and static files are read from disk on every request, so they go live without a restart; Python changes
  need `./astracore stop` + `./astracore start --prod`.

## Brand

The brand (tokens, type, logos, voice) lives in [`docs/brand/`](docs/brand/README.md) and the AstraCore design system
artifact it links to. `static/css/astracore.css` implements it; templates never use colour literals.

## EVE images

`src/astracore/static/img/eve/` holds a curated subset of `assets for possible usage/` (from the EVE Image Server, see its
`manifest.json`): PI commodity and planet icons, a few PI structure icons, the Dutch Legions / Insidious. logos and PI
ship renders. `core/eveimg.py` looks them up by name or type id (`eve_img()`, `planet_img()`, `logo_img()` in templates;
`AC.eveImg()` etc. in the browser, generated with `python -m astracore.core.eveimg`). Anything not bundled loads live from
images.evetech.net.

## Credits

AstraCore began with CosmicCarrot and welcomes contributions from fellow capsuleers. The introduction and
`/credits#contributors` showcase public GitHub contributor profiles; `/credits#creator` preserves the origin story.
The background community worker refreshes the contributor list hourly without credentials, follows pagination,
and keeps the last complete snapshot in the shared SQLite cache if GitHub is unavailable. Page loads do not
call GitHub. GitHub's own contributor data may take a few hours to update; the showcase links to its full list.
Bot accounts and anonymous commit identities are not displayed. Bug reports, testing and ideas are acknowledged
alongside the source contributors, with a link to the public discussion.

Astracore © 2026 is its own fan-made product; `/credits` thanks everything it builds on: ESI, EVE SSO and the Image Server
(Fenris Creations), DalShooth's templates, Fuzzwork's SDE, VOC Hauling, Lucide, Barlow, IBM Plex Mono, FastAPI, PuLP/CBC and more.
EVE Online material is used under the EVE Developer License: © 2014 CCP hf. All rights reserved. "EVE", "EVE Online",
"CCP", and all related logos and images are trademarks or registered trademarks of CCP hf.
