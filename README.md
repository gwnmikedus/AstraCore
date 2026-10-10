# Astracore

One EVE Online login, one profile, several tools ("modules"). v1 ships one module, **AstracorePI**: it plans
Planetary Interaction for **all your characters across several systems** at once, weighs ISK against your time,
and runs it day to day from **Operate**.

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

Double-click `Start Astracore.command` / `Stop Astracore.command` in Finder for the same. Every start makes a
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
  static/      css (Pico 2.0.6 + astracore.css), js (fmt, icons, astracore), img, icons (Lucide)
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
```

They never touch `data/` or the real env files. Covered: profile isolation, every login flow, scope bundles,
opt-in/opt-out, revocation on remove/reset, owner-hash changes, CSRF, cookie flags, JWT validation, the invite gate,
migration from an MVP database, the solve gate, and the planner.

## Data credits

ESI and EVE SSO (Fenris Creations), Fuzzwork SDE schematics, DalShooth templates, VOC Hauling, Pico CSS (MIT),
Lucide icons (ISC). © 2014 CCP hf. All rights reserved. "EVE", "EVE Online", "CCP", and all related logos and images are
trademarks or registered trademarks of CCP hf.
