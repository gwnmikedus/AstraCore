# Astracore — final build instructions (v1: AstracorePI)

> For: the AI coding agent working in this repo (`/Users/mikehoppezak/Eve`).
> Written: 2026-10-10, after a walkthrough of the running MVP (`localhost:8765`) and a read of the code.
> Work phase by phase. Finish each phase's acceptance checks (and `pytest`) before starting the next.
> When something in this spec conflicts with the code, the spec wins. When it's unclear, stop and ask Mike.

---

## 0. What we're building

**Astracore** is the umbrella product: one EVE Online login, one profile, several tools ("modules").
v1 ships exactly one module: **AstracorePI** (the current PI Planner). Every other module is "coming later";
the architecture must make adding one a matter of registering it, not rewiring auth or navigation.

**Hosting model (decided):** the app runs on Mike's Mac and is published under a domain through a
**Cloudflare Tunnel**. It is online only while his machine runs it. So: it is a *public, multi-user* web app
(anyone with the URL can log in), served from a laptop. Every design choice below follows from that:
real user separation, secure sessions, encrypted tokens, protection against one user hogging the CPU, and
a one-command on/off switch.

### Non-goals for v1
- No other modules, no payments, no mobile app, no corp/alliance dashboards.
- No rewrite of the planner engine or the UI framework (keep FastAPI + Jinja + Pico CSS + vanilla JS).

---

## Already done before you start (2026-10-10)
- **Phase 0 is done:** git repo on `main`, baseline commit `MVP baseline (PI Planner) before Astracore rebuild`;
  DB backup at `data/backups/pi_planner-pre-astracore-20261010.sqlite3`. `.gitignore` covers `.env*`, `bin/`, `data/`, `.DS_Store`, `.pytest_cache/`.
- **Env files exist (chmod 600, gitignored):** `.env.local` (dev EVE app credentials copied from `.env`, generated token key + session secret)
  and `.env.production` (public URL, callback, client id, generated token key + session secret, admin IDs, invite list).
  The old `.env` is still read by the MVP; retire it once the app reads `.env.local`. Never print secret values in logs or chat.
- **EVE applications exist:** "Astracore (dev)" (client `d5bf352d…`, callback `http://localhost:8765/auth/callback`) and
  "AstraCore" (client `440238e5…`, callback `https://astracore.hoppyhome.nl/auth/callback`). Both have the full scope list registered.
- **Cloudflare tunnel exists** (§8.2), `cloudflared` is in `bin/`.
- **Decided:** admin = Mike's 5 characters (IDs in the env files); production invite list starts with those 5 characters (Mike adds corps/alliances later).
- `EVE_CLIENT_SECRET` in `.env.production` is filled. `CLOUDFLARE_TUNNEL_TOKEN` is filled too.

---

## 1. Phase 0 — safety net (do first)

1. ~~git init + baseline commit~~ (done). Work in commits per phase from here.
2. ~~Back up the database~~ (done).
3. `pytest -q tests` must pass before and after every phase.

---

## 2. Phase 1 — rename and brand

### 2.1 Package and naming
- Rename the package `pi_planner` → `astracore`, with the PI code as a module package:
  ```
  astracore/
    core/        app factory, auth/SSO, sessions, profiles, scopes, module registry, home, profile pages
    esi/         (moved from pi_planner/esi)
    modules/
      pi/        everything PI: planner/, intel/, static_data/, PI routes + templates
    templates/   base layout, home, profile, errors
    static/      css/astracore.css, img/ (logo, favicon, module icons)
  ```
- Run with `python -m astracore`. Env vars: `ASTRACORE_PORT` (default 8765), `ASTRACORE_DATA`.
  Keep reading the old `PI_PLANNER_*` names as fallbacks for one release.
- Data file: `data/astracore.sqlite3` (migrate from `pi_planner.sqlite3`, see §3.4).

### 2.2 Naming rules in the UI
| Thing | Name |
|---|---|
| Product / site / `<title>` suffix | Astracore |
| PI module (nav, cards, page titles) | AstracorePI — in-module nav may shorten to "PI" |
| Page titles | `<Page> · AstracorePI · Astracore` |
| The person | "you" / "your profile" |
| A logged-in EVE character | "character" (never "account") |
| A group of characters on one EVE subscription | "EVE account" (see §3.2) |
| Where goods are collected and shipped from | **Drop-off** — everywhere. Today the Space page says "Hub (where your hauler starts)" and the plan says "drop-off". Use one word. |

### 2.3 Visual identity
- One stylesheet `static/css/astracore.css` that sets Pico variables + brand tokens on `:root`
  (`--ac-bg`, `--ac-surface`, `--ac-border`, `--ac-text`, `--ac-muted`, `--ac-accent`, `--ac-ok`, `--ac-warn`, `--ac-bad`).
  Dark is the default theme (EVE players expect it); keep a light theme working via `data-theme`.
  No colour literals in templates — move the inline `<style>` blocks out of `base.html`/`characters.html`/etc. into this file.
- Self-host Pico (copy the pinned 2.0.6 CSS into `static/`) instead of the jsDelivr link: the site shouldn't break when a CDN does.
- Logo: an "Astracore" wordmark + a simple mark (SVG, placeholder until Mike supplies the final one). Favicon from the mark.
  The PI module gets its own small icon. **Ask Mike for final logo/colours; use clean placeholders until then.**
- Replace emoji used as UI icons (🪐 ⚙ 📦 🏭 🚚 💰 ⏱ etc.) with one inline-SVG icon set (e.g. Lucide, copied in, MIT).
  Emoji are fine inside user-facing copy only where they add meaning — default to none.
- **Number formatting:** one formatter, one locale (EVE's own: `en`): `123,379 m³`, `46.2M ISK`, `1.24B ISK`.
  Today `num()` uses the browser locale (`toLocaleString()`), so a Dutch browser shows `123.379 m³` right next to
  `46.2M` — ambiguous. Also: no `-0`, no `94.5 restarts/week` (round counts), no raw `210138.5 m³` (use separators).
  Put the formatter in one JS file and one Jinja filter, and use it everywhere.

### 2.4 Legal footer (required)
- **CCP Games is now Fenris Creations** (rebrand after the split from Pearl Abyss). Never write "CCP" in new UI text.
  Replace "Not affiliated with CCP Games." with the copyright/trademark notice required by the current EVE Developer License Agreement,
  copied exactly from developers.eveonline.com (it may still say CCP hf. legally; use whatever the current text says, don't paraphrase).
  Footer data credit becomes "Data: ESI (Fenris Creations)". Grep the codebase for `CCP` and update user-facing strings; code comments may keep it.
- Keep the data/credits line (ESI, SDE, DalShooth templates, VOC).
- Add links: Privacy (§5.4), "What we read from your characters" (§4.4).

**Acceptance:** app starts as `python -m astracore`; no "PI Planner" string left in the UI; every page uses the
shared layout and stylesheet; numbers look identical in an `nl-NL` and an `en-US` browser.

---

## 3. Phase 2 — profiles, characters, EVE accounts (data model)

Today everything is global: one `characters` table, one `tokens` table, one `settings` row in `kv`,
one `plan_runs` list. With a public URL that means every visitor would see and edit Mike's data. Fix that first.

### 3.1 Concepts
- **Profile** — the Astracore user. Created automatically by the first EVE login. Has settings, plans, characters.
  No email, no password: identity is "you can log in as one of this profile's characters".
- **Character** — an EVE character linked to exactly **one** profile. Logging in with *any* linked character opens that profile.
- **EVE account** — an optional, user-named group of characters (e.g. "Main", "Alt account 2").
  **ESI does not reveal which characters share an EVE account** (the SSO token only identifies the character),
  so the grouping is set by the user. Default: each new character lands in "Unassigned"; the profile page lets the user
  create accounts and drag/select characters into them (max 3 characters per account, matching EVE).
  Purpose: show "which account has which characters" and, later, account-level info (training, Omega) per account.

### 3.2 Schema (new / changed tables)
```
profiles(id PK, created_at, last_login_at, display_name, main_character_id, settings_json)
eve_accounts(id PK, profile_id FK, name, sort)
characters(character_id PK, profile_id FK NOT NULL, eve_account_id FK NULL, name, owner_hash,
           corporation_*, alliance_*, enabled_modules_json, ... existing synced columns ...)
tokens(character_id PK FK, refresh_token_enc, access_token_enc, expires_at, scopes)
sessions(id PK (random 32B, hashed), profile_id FK, created_at, last_seen_at, user_agent, ip_hint)
module_settings(profile_id, module_id, settings_json, PRIMARY KEY(profile_id, module_id))
plan_runs(+ profile_id FK)
planet_overrides(+ profile_id FK, PK (profile_id, planet_id))
```
- Shared, non-personal caches stay global: `http_cache`, prices, SDE, VOC tariff, sov/space data.
- **Every query on personal data takes a `profile_id`.** Add a test that creates two profiles and asserts neither
  can read, change or delete the other's characters, plans, settings or overrides through any route.
- Split today's `Settings`: per-profile preferences (effort, tiers, cycle, area, selling choices, batch size, sales-tax
  overrides, yield fallback…) go to `module_settings`; instance-wide data (VOC buyback %, VOC tariff) becomes
  **admin settings**, editable only by the admin profile (Mike, set by `ASTRACORE_ADMIN_CHARACTER_IDS` in `.env`).
- Move `hour_isk` and `guide_step` from `localStorage` into the profile's PI settings (they are choices, not browser state).

### 3.3 Character ownership changes
- Store the JWT `owner` claim (character owner hash; confirm the claim name against a real token) at every login/refresh. If it changes, the character was
  transferred to another player: drop its token, unlink it from the profile, and tell the profile on next visit.
- Refresh failing with `invalid_grant` = access revoked/password changed: mark the character "needs login", keep its data.

### 3.4 Migration of the current data
- One-off migration on first start: create profile #1, attach all existing characters to it (put them in "Unassigned"),
  move `kv.settings` into its PI settings, attach existing `plan_runs` and `planet_overrides`, re-encrypt tokens (§4.5).
- Make it idempotent and keep the pre-migration backup.

**Acceptance:** two different EVE characters logged in from two browsers produce two separate profiles with no shared
personal data; Mike's current five characters, settings and plans survive the migration intact.

---

## 4. Phase 3 — login, sessions and ESI scopes

### 4.1 Login flows (all through EVE SSO)
| Situation | Result |
|---|---|
| Signed out, character **already linked** to a profile | Sign in to that profile; update its token. |
| Signed out, character **unknown** | Create a new profile with this character; sign in; send to onboarding (§5.2). |
| Signed in, "Add character", character **unknown** | Link to the current profile. |
| Signed in, "Add character", character **already in this profile** | Refresh its token/scopes; say "updated". |
| Signed in, "Add character", character **linked to another profile** | Show a choice: "Move <name> to this profile" or cancel. The fresh SSO login proves ownership. If it was that profile's last character, offer to **merge** the two profiles (characters, plans; current profile's settings win). |
| SSO returns a different character than the one the user meant to re-authorise (they picked another in the EVE SSO character picker) | Handle it as "Add character" and tell them which character was actually authorised. |

- `state` must be bound to the browser session (cookie) and to the intent (`login` / `add` / `upgrade:<module>`), single-use, 10-minute expiry. Today `_pending_states` is a process-global dict — keep it server-side but key it per session.
- Validate the access-token JWT properly (signature via the JWKS from `https://login.eveonline.com/.well-known/oauth-authorization-server`, `iss`, `aud`, `exp`) instead of only base64-decoding it — it is now a public login.
- Callback URL comes from the active mode (§8.0): `http://localhost:8765/auth/callback` in local mode, `https://astracore.hoppyhome.nl/auth/callback` in production mode — each on its own EVE application.

### 4.2 Sessions
- Server-side sessions (`sessions` table), cookie `ac_session`: `HttpOnly`, `Secure`, `SameSite=Lax`, 30-day sliding expiry.
- "Sign out" and "Sign out everywhere" (deletes all sessions of the profile).
- CSRF token on every POST form and `fetch` (the PI wizard posts JSON to `/api/*`).

### 4.3 Scope model: required always, optional opt-in
Today the app requests **every scope the EVE application has (≈75)** — including sending mail, writing contacts and
fleet control — on every login. On a public site that's the fastest way to lose trust. Replace it with bundles.

**Core (always, at sign-in):** no scopes. A scope-less SSO login still identifies the character. (`publicData` is not needed.)

**Module bundles** — declared by each module in the registry (§6):

| Bundle | Scopes | Why (shown to the user) |
|---|---|---|
| `pi.required` | `esi-planets.manage_planets.v1`, `esi-skills.read_skills.v1`, `esi-assets.read_assets.v1`, `esi-universe.read_structures.v1`, `esi-contracts.read_character_contracts.v1`, `esi-markets.read_character_orders.v1`, `esi-wallet.read_character_wallet.v1`, `esi-characters.read_standings.v1` | colonies & extractors, CCU/tax skills, products in hangars and their location names, VOC contracts, sell orders, ISK actually earned, broker-fee standings |
| `pi.optional.customs` | `esi-planets.read_customs_offices.v1` | Real POCO tax for corps where you're a Director (otherwise the settings value is used) |
| `pi.optional.waypoints` | `esi-ui.write_waypoint.v1` | "Send route to my EVE client" button on the plan/pickup route (new small feature) |

Note: the code already calls `/characters/{id}/standings/` and `/corporations/{id}/customs_offices/`, but `REQUIRED_SCOPES`
lists neither — that's why standings/customs silently fall back today. The table above fixes that.

**Rules**
- Sign-in from the home page requests **core + the required bundles of modules the profile has enabled**
  (v1: just `pi.required`), so one login gives a working PI module. A brand-new user enabling PI = same login.
- Optional bundles are off by default. The user turns them on per character on the profile page → SSO re-login for that
  character requesting `required ∪ already-granted optional ∪ new bundle` → store the new refresh token, revoke the old one.
- Turning a bundle **off**: re-login with the smaller set (or, if the user doesn't want to log in again, stop using the
  scopes and show "granted but unused — re-login to drop it"). Never silently keep using a scope the user switched off.
- A character missing a module's required scopes stays linked and can still sign you in; the module shows
  "<name> needs one more EVE login for AstracorePI" with a button.
- When a future module ships, its bundle appears on the profile page as **opt-in** ("Enable <module> for <character>").
  Never add scopes to existing characters without a login the user started.
- The EVE application on developers.eveonline.com must list every scope any bundle can request (it does today; keep it, but the
  app only *requests* what the bundles say).

### 4.4 "What we read" page
Generated from the registry: per module, per bundle, each scope in plain words + what it's used for + "we never write
to your account except: setting waypoints if you enable it". Linked from the login button, the profile page and the footer.

### 4.5 Token storage
- Encrypt refresh and access tokens at rest (Fernet, key `ASTRACORE_TOKEN_KEY` in `.env`, generated on first run if missing;
  warn loudly if it's absent so a lost key isn't a silent data loss).
- `.env` stays out of git (it already is) and gets `chmod 600` (`save_env` already does this).

### 4.6 Removing connections and resetting
- **Remove a character:** revoke its refresh token with EVE SSO (`POST https://login.eveonline.com/v2/oauth/revoke`,
  Basic auth with client id/secret, body `token_type_hint=refresh_token&token=…`), delete token + synced data, remove it from
  plans' character lists. If it's the last character: explain that the profile will be deleted and require confirmation (= reset).
  If it's the character you're signed in with, you stay signed in (the session belongs to the profile, not the character).
- **Reset profile** (danger zone): offer "Download my data (JSON)" first; then type-to-confirm the profile name;
  revoke every token with EVE SSO; delete profile, characters, accounts, settings, plans, overrides, sessions; sign out; land on home
  with "Your profile was deleted."
- **Reset only AstracorePI** (softer option): wipes PI settings, plans and overrides, keeps characters.
- Also tell users they can revoke access themselves on EVE's third-party applications page (account management on eveonline.com).

**Acceptance:** tests for every row in §4.1; a test that a fresh sign-in requests exactly `pi.required`; opt-in/opt-out round
trip; remove-character and reset-profile call the revoke endpoint (mock it) and leave no rows behind for that profile.

---

## 5. Phase 4 — home page, dashboard, profile page

### 5.1 Public home (`/`, signed out)
Today `/` immediately redirects into Characters/Space/Planner, so a visitor never lands anywhere. Build a real landing page:
1. **Hero:** Astracore wordmark, one-line promise ("Tools for capsuleers. One login for all your characters."), primary button
   = official **"Log in with EVE Online"** SSO button image from developers.eveonline.com, secondary link "What we read from your characters".
2. **Module card: AstracorePI** — 2–3 sentences on what it does that others don't (plans across several systems and all your
   characters at once; real ISK after POCO tax, courier fees and sales tax; templates + VOC courier values; daily Operate view),
   plus a static screenshot of a plan.
3. **How it works** — 3 steps: Log in with your characters → Answer a few questions → Build, then run it from Operate.
4. **"More modules are coming"** — one understated card, no names or dates.
5. **Trust strip:** read-only by default, tokens encrypted, remove any character or your whole profile at any time.
6. Footer (§2.4).
Mobile-friendly; no horizontal scroll at 375 px.

### 5.2 First run (new profile)
After the first login: short onboarding on one page — "Welcome, <name>" → "Add your other characters" (big add button,
list fills as they come back from SSO) → "Group them by EVE account (optional)" → "Start AstracorePI". Skippable at every point.

### 5.3 Signed-in home (`/` = dashboard)
- Header: Astracore logo, module switcher (only AstracorePI in v1), profile menu (portrait of main character → Profile, What we read, Sign out).
- **AstracorePI tile** with live status: plan ISK/day, colonies built vs planned, extractors ending within 24 h,
  products waiting for pickup, ISK earned last 7 days; primary button goes to the right place (§7.1).
- Warnings strip: characters needing a login, transferred characters, stale data ("last ESI refresh 3 days ago").

### 5.4 Profile page (`/profile`)
- **EVE accounts** as columns/cards, each listing its characters (portrait, name, corp/alliance, last refresh, scope status);
  "Unassigned" column; add/rename/delete account; move characters between accounts. Choose the **main character** (avatar, display name).
- Per character: status (OK / needs login / transferred), granted bundles with toggles, "Refresh from ESI", "Remove".
- **Modules:** AstracorePI enabled (v1 always), per-character include/exclude for PI lives in the PI module (§7.2), not here.
- **Sessions:** list of signed-in browsers, "Sign out everywhere".
- **Danger zone:** Download my data · Reset AstracorePI · Reset profile.
- Privacy page (`/privacy`): what is stored (character ids/names, ESI data listed in §4.3, encrypted tokens), where (Mike's machine),
  how to delete (§4.6), no tracking/analytics, no selling of data.

**Acceptance:** signed-out `/` shows the landing page (no redirect); signed-in `/` shows the dashboard; profile page shows
accounts with their characters and all actions from §4.6 work end-to-end.

---

## 6. Module registry (keeps future releases cheap)

```python
Module(
  id="pi", name="AstracorePI", short="PI", status="live",          # "live" | "beta" | "coming"
  route_prefix="/pi", icon="static/img/modules/pi.svg",
  required_bundle=Bundle("pi.required", scopes=[...], why="..."),
  optional_bundles=[Bundle("pi.optional.customs", ...), Bundle("pi.optional.waypoints", ...)],
  nav=[("Operate", "/pi/operate"), ("Plan", "/pi/plan"), ("Area", "/pi/area"), ("Settings", "/pi/settings")],
  dashboard_tile=pi_tile,   # callable(profile) -> tile data
  on_character_removed=..., on_profile_reset=...,
)
```
- Home cards, dashboard tiles, nav, "What we read", sign-in scopes and reset hooks are all generated from this list.
- Modules with `status="coming"` are not registered in v1 (the home page uses the generic "more coming" card).

---

## 7. Phase 5 — AstracorePI: flow and UX fixes (from the walkthrough)

### 7.1 Routes and where you land
- Prefix everything: `/pi/area` (was `/space`), `/pi/plan` (was `/planner`, advanced = `/pi/plan?view=advanced`), `/pi/operate`,
  `/pi/settings`, `/pi/export/...`, `/pi/api/...`. 301-redirect the old paths for one release.
- Entering the module (`/pi`): no characters with PI scopes → "connect characters" panel; no area → Area; no saved plan → Plan wizard;
  **a plan exists → Operate** (that's the daily screen; today returning users are dropped back into the wizard).
- PI sub-nav: **Operate · Plan · Area · Settings** (Operate first once a plan exists). Drop the numbered 1–4 stepper
  in the global header; the stepper stays only inside the wizard. Characters move to the profile page; PI keeps a
  compact "Characters in this plan" panel (§7.2).

### 7.2 Characters inside PI
- The current Characters page mixes profile concerns (login, remove) with PI facts (slots, CCU level, colonies).
  In PI keep only: include/exclude per character, slots, CCU level with what it allows, current colonies, and the "needs login" state.
- Explain the CCU rule once at the top instead of on every card (nullsec miner templates need CCU 4, lowsec miners 5, factories 2–3),
  and show CCU 5 characters as explicitly "OK for every template" (today only CCU 4 gets a note, which reads like a warning).

### 7.3 Wizard order and content
Current order: Goal → Products → Logins → Area → Planets → Teamwork → Selling → Batches → Plan.
New order — lifestyle constraints first, then how to produce, then how to sell:
**Goal → Logins → Area → Products → Planets → Teamwork → Selling → Batches → Your plan.**
- Merge the **Area page (constellation picking + drop-off)** into the wizard's Area step as an "Advanced: pick constellations / drop-off" expander,
  so "where" is asked once. Keep the standalone Area page for editing later.
- **Goal step:** today it shows ISK cards that are almost identical (46.1M / 46.2M / 46.2M) and "Set and forget" even hauls *more*
  than Balanced (123,379 vs 123,362 m³). The goal is a preference (how much an hour of your time is worth), not a plan.
  Make it a plain choice with no ISK numbers, and show the "an hour of my time is worth" picker right there.
- **Only one badge story per question:** today "YOUR PICK" and "SUGGESTED" can sit on different cards and on a first visit
  the saved value is pre-picked. On a first visit pre-select the suggestion; afterwards show the user's pick and, if different,
  one line "We'd suggest X: +12.3M/day for 25 min more a week".
- **Cut noise in the advice text:** don't list differences that don't matter (e.g. "−17 m³ hauled/week", "+1 transfer").
  Use thresholds (ISK < 1% or < 0.5M/day, < 5% m³, < 5 min/week → omit; if everything is below threshold say "These answers make no real difference for your characters").
- "Question 1 of 8" next to a 9-dot tracker → label it "Step 1 of 8" and render the last dot as the result, not a step.
- Every "Next" saves; make sure it never saves a value the user didn't see/choose (only `picks`, not stale `st` fields).

### 7.4 Plan result
- Keep: per-character build lists, templates zip, VOC courier values, routes. Add "Send route to EVE" when the waypoint bundle is granted.
- Show the yield caveat prominently while P0 yield is still the 1000/h estimate (0.5× / 2× band already exists — move it into the headline).
- Save named plans per profile; "Set as active plan" (Operate compares against the active plan).

### 7.5 Operate
From the walkthrough (Mike's current data):
- Unresolved structure: "Location 1045667232374" — show "Unknown structure (no docking access)" + system name if known; never a raw ID.
- The same advice repeats per hangar ("VOC doesn't pick up here…", "Let Han Nin Lo sell this… 4.2% vs 7.5%"). Aggregate:
  one "Consolidate & sell" card with total m³ and value, the best seller once, and the per-location list underneath.
- A 210,138 m³ stack (Konora, 614.6M) gets "haul it to Jita yourself" — add the size reality check (freighter load, number of trips, or the
  VOC pickup alternative with its courier fee) instead of a one-liner.
- Number formatting (§2.3): `-0`, `210138.5 m³`.
- Plus open items from `pi-planner-review-2026-10-10.md` #8 (finished couriers listed under "In the pipeline", raw type IDs and
  non-PI items in buyback contracts). Check which are already fixed before touching them.

### 7.6 Planner correctness backlog (carry-over)
From `pi-planner-review-2026-10-10.md`, issues #1–#7 and #9. The README says calibration now uses the official (developers.eveonline.com) bar-width + decay formula
and that taxes come from skills — **verify each item against the current code and tests, close the fixed ones, fix the rest.**
Do not change the optimizer's behaviour in this branding work beyond these items.

### 7.7 Fairness and load (it's a laptop)
- Each wizard question runs one full solve per answer (3–4 CBC solves). With several users that saturates the Mac.
  Add a global solve semaphore (default 2 concurrent, `.env` configurable), a per-profile limit (1 in flight; newer request cancels older),
  and a cache keyed on (profile data hash, settings) so going Back/Next doesn't re-solve.
- Show a friendly "Astracore is busy, your plan is queued" state instead of timing out.
- ESI: all users share one IP. Respect ESI's error-limit and rate-limit headers globally (one shared budget), back off, and never let one
  profile's refresh burn it for everyone. Per-profile "Refresh from ESI" at most once per 5 minutes.

**Acceptance:** walk the wizard start-to-finish as a new profile — order as above, no near-duplicate ISK cards on Goal, no double badges,
no sub-threshold noise; returning profile with a plan lands on Operate; Operate shows no raw IDs and no repeated advice blocks;
`pytest` covers the semaphore and the cache.

---

## 8. Phase 6 — running it: Cloudflare Tunnel, on/off switch, hardening

### 8.0 Two modes: `local` and `production`
Public URL for now: **`https://astracore.hoppyhome.nl`** (subdomain, so the root of hoppyhome.nl stays free). Audience: a small invited group.

- `ASTRACORE_MODE=local|production`, selected by `./astracore start [--prod]` (default `local`).
- Each mode has its **own env file and its own data folder**: `.env.local` + `data/local/`, `.env.production` + `data/production/`.
  Reason: EVE refresh tokens are tied to the EVE application (client id) that issued them, so a character logged in on
  the local app can't be refreshed by the production app. Mixing them in one database breaks logins.
- Two EVE applications on developers.eveonline.com, same scope list:
  - **Astracore (dev)** — callback `http://localhost:8765/auth/callback`
  - **Astracore** — callback `https://astracore.hoppyhome.nl/auth/callback`
  The old "PI Planner" application can become the dev one (change its name and keep its callback).
- What the mode switches:

| | local | production |
|---|---|---|
| Public URL / callback | `http://localhost:8765` | `https://astracore.hoppyhome.nl` |
| Cloudflare tunnel | not started | started by `./astracore start --prod` |
| Cookie `Secure` flag, HSTS, proxy headers | off | on |
| `/docs`, debug tracebacks | on | off |
| Access gate (§8.3) | off | **on** |
| Visible "LOCAL" badge in the header | yes | no |

- Refuse to start production mode if `.env.production` is missing the client id/secret, `ASTRACORE_TOKEN_KEY` or the session secret.
- The Phase 2 migration of the current MVP database goes to `data/local/`. Production starts empty: invited users (Mike included) log in fresh there.

### 8.1 On/off (must be easy)
- `./astracore start` — starts the app (uvicorn on `127.0.0.1` only) and `cloudflared tunnel run astracore` in the background,
  writes PID files to `data/run/`, waits for `/healthz`, prints the public URL.
- `./astracore stop` — stops both cleanly (cloudflared first, so visitors get the offline page, then the app).
- `./astracore status` / `./astracore logs`.
- Double-clickable `Start Astracore.command` and `Stop Astracore.command` in the repo root that call the above (macOS).
- Optional: a launchd plist template for "start at login", **off by default**.
- On every start: SQLite backup (`data/backups/astracore-YYYYMMDD-HHMM.sqlite3`, keep 14) and pending migrations.

### 8.2 Tunnel setup (document in README, script what can be scripted)
- Uvicorn with `--proxy-headers --forwarded-allow-ips 127.0.0.1`, so redirects and the SSO callback use `https://<domain>`.
- `ASTRACORE_PUBLIC_URL` in each mode's env file (§8.0); the callback URL is derived from it.
- **Cloudflare side is done (2026-10-10):** dashboard-managed tunnel **`astracore`** (ID `ec1959ab-2bbc-476c-8588-5ecc890c7497`),
  published application `astracore.hoppyhome.nl → http://127.0.0.1:8765`, DNS CNAME created automatically.
  Separate from the `yams` tunnel (Mike's media server) — never touch that one.
- Because the tunnel is dashboard-managed: **no `config.yml`/ingress rules on the Mac**. Routes are changed in the dashboard only.
- Mac side: `cloudflared` is already downloaded to `bin/cloudflared` (arm64, gitignored; no Homebrew on this Mac). The start script uses it and falls back to `cloudflared` on PATH. `.env.production` exists (chmod 600). Mike puts the tunnel token (dashboard → Tunnels → astracore → install command) into
  `.env.production` as `CLOUDFLARE_TUNNEL_TOKEN`. The agent never asks for it in chat and never prints or logs it.
- `./astracore start --prod` runs `cloudflared tunnel run --token "$CLOUDFLARE_TUNNEL_TOKEN"` as a child process with a PID file.
  **Do not** use `cloudflared service install`: that starts it at boot and breaks the easy on/off.
- Production must listen on port 8765 on 127.0.0.1 (the route points there); fail start if the port is taken.
- When the Mac is off, Cloudflare shows its own error page. Optional nice-to-have: a tiny Cloudflare Worker on the hostname that
  serves a branded "Astracore is offline right now" page when the origin fails.

### 8.3 Hardening checklist
- Bind to `127.0.0.1` only (already true) — the tunnel is the only way in.
- Security headers: CSP (self + images.evetech.net + login.eveonline.com form action), `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, HSTS via Cloudflare.
- Turn off FastAPI's `/docs` and `/openapi.json` in production.
- Error pages: branded 404/500; no stack traces to visitors; errors to `data/logs/` (rotated).
- `/healthz` endpoint for the start script.
- Access gate, **on in production**: `ASTRACORE_ALLOWED_CHARACTERS` / `_CORPS` / `_ALLIANCES` in `.env.production`. A login passes if the character matches any list.
  Others get a polite "Astracore is invite-only right now" page and no profile is created. Admin page to add/remove entries without a restart.

**Acceptance:** `./astracore start` → site reachable on the domain with working EVE login; `./astracore stop` → domain shows offline page,
no processes left; fresh clone + README gets a second machine running in under 15 minutes.

---

## 9. Phase 7 — QA before calling it done

Automated (`pytest`):
- Profile isolation (two profiles, every personal route).
- All §4.1 login rows; scope requests per bundle; opt-in/opt-out; revoke on remove/reset; owner-hash change unlinks.
- CSRF rejected without token; session cookie flags.
- Migration from an MVP database copy.
- Existing planner tests still pass.

Manual walkthrough (record findings in the project doc):
1. Signed out on phone width → home page reads well, login button works.
2. New character → onboarding → add 2 more characters → group into accounts → start PI → wizard → plan → download templates.
3. Sign out, sign in with a *different* character of the same profile → same profile loads.
4. Opt in to waypoints for one character → button appears; opt out → it disappears.
5. Log in with a character that belongs to another profile while signed in → move flow; merge flow.
6. Remove a character; reset AstracorePI; reset profile → nothing left, EVE SSO token revoked.
7. Two browsers / two profiles planning at the same time → both get results, Mac stays responsive.
8. `./astracore stop` and `start` while a user is mid-wizard → they can continue after restart (state is server-side).

---

## 10. Open decisions for Mike
1. Which corps/alliances to add to the invite list (starts with Mike's 5 characters, §8.3).
2. Final logo/colours (§2.3) — placeholders until then. (Domain decided: `astracore.hoppyhome.nl`.)
3. Should a removed character's colonies stay in old saved plans (read-only history) or be stripped? Default in this spec: stripped.
