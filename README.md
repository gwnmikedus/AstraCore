# Astracore

One EVE Online login for a set of tools. v1 ships **AstracorePI**, which plans Planetary Interaction for **all your characters across several systems** at once.
It weighs ISK against hauling effort so you can choose anything from "brain-dead passive" to "max ISK".

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m astracore       # http://localhost:8765 (local mode, reads .env.local)
```

## Use

1. **Characters**: log in with EVE once per character. Slots, Command Center Upgrades level,
   corp/alliance and current colonies are read from ESI.
2. **Space**: derived from your characters (your alliance's sov space + where you already have colonies),
   grouped by region/constellation. The best constellation is pre-selected; tick what you want to use.
3. **Plan**: a guided flow, one question per screen with a progress tracker: goal, how far to process, how often you
   log in, how far you fly, sharing planets, characters supplying each other, how you sell, batch size. Every answer
   card is planned live for your characters (ISK/day, your time per week, hauling, restarts, systems, factories) and the
   flow suggests the answer that pays best once your time is counted (an hour is worth 300M / 90M / 0 ISK for
   set-and-forget / balanced / max ISK, adjustable). The last screen is the full plan: per-character build lists, routes,
   a zip with exactly the templates needed, and "How you get paid" with the exact VOC courier contract values.
   **Advanced** (`/planner?view=advanced`) has every option as live sliders on one screen, plus products to avoid
   and the drop-off.
4. **Operate**: after setup. Extractors to restart, products waiting on launchpads, factories low on inputs,
   PI products in your hangars with what to do with them (buyback paste list or courier contract values),
   VOC courier/buyback contracts and sell orders in progress, and the ISK that actually came in vs. the plan.

## Selling: VOC Hauling

- Courier tariff is read live from <https://vochauling.com> (min fee, ISK/m³, collateral %) and shown in Settings.
  Courier fee = max(min fee, m³ × rate + collateral × col%).
- Buyback (<https://buyback.vochauling.com>): 90% of Jita buy for P2–P4, P1 refused (test appraisal at 7G-QIG on
  2026-10-10). Editable in Settings.
- Batches whose courier fee would be eaten by the minimum fee fall back to another channel or are marked "hold".

Only [DalShooth/EVE_PI_Templates](https://github.com/DalShooth/EVE_PI_Templates) templates are suggested:
`Miner - 00/LS - <P1>` (P0→P1) and `Factory - <product>` (P2/P3/P4). Each template's CPU/PG is checked against
every character's Command Center Upgrades level (nullsec miners need CCU 4, lowsec miners 5, factories 2–3).

## EVE login

The EVE application's credentials live in the local `.env` (`EVE_CLIENT_ID`, `EVE_CLIENT_SECRET`,
`EVE_CALLBACK_URL` - the callback must match the one registered at developers.eveonline.com).
Scopes used: `esi-planets.manage_planets.v1`, `esi-skills.read_skills.v1`.
Everything else (sov, systems, planets, gates, prices) uses public ESI.

## Model notes

- Planet richness isn't available from ESI. It's estimated from security; override per planet on the Area page after scanning in game.
  Once 2+ of your colonies extract, each planet's richness is measured from its extractors (manual overrides still win).
- P0/hour/head is a setting (default 1000 at richness 1.0, 3-day program) until your characters have extractors; then it is
  calibrated from ESI using CCP's extraction formula (<https://developers.eveonline.com/docs/guides/pi/>: bar width + decay).
  Program length uses the same formula (1 day ≈ 1.53×, 7 days ≈ 0.63× the hourly output of 3 days).
  The planner shows what the plan earns at 0.5× and 2× the assumed yield while it is still an estimate.
- Sales tax and broker fee come from the selling character's Accounting / Broker Relations and standings (the character with the
  lowest tax sells; others hand over products). Customs tax is read from ESI where a character can see it (Director of the owning
  corp), otherwise the Settings value.
- A 2nd/3rd colony of yours on the same resource on one planet is counted at 70% / 49% yield (Settings).
- Drop-offs where VOC doesn't pick up are couriered from the nearest VOC pickup; stock outside VOC's reach is valued as hauled to
  Jita/Amarr yourself.
- The engine solves a pooled integer program over (planet, template) pairs (PuLP/CBC, a few seconds),
  then assigns colonies to characters: existing matching colonies are kept, factory chains stay on one character
  unless "characters supply each other" is on, and each character is kept to as few systems as possible.

## Tests

```bash
.venv/bin/python -m pytest -q tests
```
