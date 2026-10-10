# PI Planner (localhost:8765) review – 2026-10-10

Plan under test: hub 7G-QIG, SG-CTQ, effort 50, P4 max, 3 systems, 3 jumps, 3 colonies/planet, cross-character on, batch 28 d.
Result: 39.2M ISK/day, 27 P1 miners (Silicon/IF/Biomass) + 2 Microfiber Shielding factories in 39P-1J, NIDJ-K, 8RQJ-2.

## Verified correct
- P0 per planet type, planet type IDs, CC CPU/PG per CCU level, structure CPU/PG, POCO base values (import = half), SDE schematic rates, ESI volumes (P1 0.19, P2 0.75, P3 3, P4 50).
- Plan arithmetic recomputed by hand (miner 1,958 Silicon/day at -0.56; factory 1,440/day needing 11,520 of each input; 28-day batch quantities; POCO ~5M/day explains 39.2M/day vs 1.24B per batch).
- VOC tariff identical to vochauling.com; courier fee 78.16M for 99,908 m3 / 1.32B collateral is correct; Jita->Amarr fallback for small Silicon batch is correct.
- 00 miner template fits CCU 4 (link length ~346 km, app estimate matches). 18/18 tests pass.

## Issues (priority order)
1. P0 yield is a guess (1000/head/h, no colonies to calibrate). ISK scales ~linearly: 39M @1000, 73M @2000, 100M @3000; product mix changes (no factories @5000).
2. Calibration formula (intel/richness.py `calibrate_head_yield`) ignores ESI's 15-min bar width + decay (official formula: https://developers.eveonline.com/docs/guides/pi/): off 0.77x (15-min cycles) to 2.5x (2-h cycles); only right for 30-min cycles. `CYCLE_YIELD_FACTOR` also off (1-day +56% real vs +35%; 7-day -37% vs -25%).
3. Colonies per planet = 3 stacks the same resource on one planet with no depletion model -> overstated. With 1 per planet: 33.4M/day.
4. No self-contained P0->P1->P2 planet option (only DalShooth miner/factory templates). evepi.online has this ("Brain-dead P2"): no P1 export tax, ~75% less m3.
5. Sales tax setting 4.5%, but 4 of 5 chars have Accounting 0 (7.5% base); Han Nin Lo has Accounting 4 (~4.2%). Skills are read but unused.
6. Drop-off at a non-VOC system (e.g. HZAQ-W) silently values all P1 at 0.
7. "Max ISK" can show less than "Balanced" (39.1 vs 39.2; 71.2 vs 73.1 @2000).
8. Operate: finished couriers shown under "In the pipeline"; buyback contracts list raw type IDs + non-PI items; 614.6M P1 in Konora gets "no enabled way to sell".
9. Check in game: templates saved at CCU 5 on Temperate, applied to Lava/Ice with CCU 4 (Krat Bier, CosmicCarr0t).

## vs evepi.online
evepi: good ESI dashboard/alerts, but planner is one system only, relative "Profit" scores (no ISK), no hauling/selling costs; its P2 auto-pick put 5 chars on HZAQ-W I and picked by coverage, not profit.
Local app: multi-system/multi-character, absolute ISK net of POCO/courier/tax, VOC contract values, template zip, CCU checks.
Verdict: local app is the better planner once #1-#3 are dealt with; build 2-3 colonies, fix calibration, then re-plan.

---

# Astracore rebuild: backlog status and QA (2026-10-10)

## Backlog (spec §7.6), checked against code and tests
| # | Issue | Status |
|---|---|---|
| 1 | P0 yield is a guess | Still a guess until colonies run (needs in-game data). The plan headline now says so and shows the ISK at 0.5× / 2× yield; calibration kicks in automatically. |
| 2 | Calibration ignores bar width + decay | Fixed: `static_data/extraction.py` implements the official formula; `test_calibration_uses_bar_width_and_decay`, `test_cycle_factor_follows_ccp_formula`. |
| 3 | Stacked colonies have no depletion | Fixed: `stack_yield_pct` (70% / 49%); `test_stacked_colonies_share_deposits`. |
| 4 | No self-contained P0→P2 planet | Won't fix: no DalShooth template exists and templates are never authored by us. |
| 5 | Sales tax ignores skills | Fixed: taxes from the seller's skills/standings; `test_taxes_from_skills`. |
| 6 | Non-VOC drop-off values P1 at 0 | Fixed: courier from the nearest VOC pickup; `test_non_voc_dropoff_couriers_from_nearest_pickup`. |
| 7 | Max ISK below Balanced | Fixed for alternatives (`test_more_effort_never_shows_less_isk`); the Goal question no longer shows ISK at all. |
| 8 | Operate: finished couriers, raw IDs, non-PI items, "no enabled way to sell" | Fixed: completed contracts in their own list, items filtered (`test_pipeline_hides_old_and_non_pi`), unknown structures named, one Consolidate & sell card with a haul reality check. |
| 9 | CCU-5 templates on CCU-4 characters / other planet types | App warns ("Check in game: …"). Needs an in-game check by Mike. |

## Automated QA (`pytest`, 67 tests)
Profile isolation (two profiles, every personal route); every login row; scopes per bundle; opt-in/opt-out;
revoke on remove/reset; owner-hash change unlinks; invalid_grant → needs login; CSRF; cookie flags; session rotation;
JWT validation (signature, iss, aud, exp); invite gate; migration from an MVP database; solve gate (concurrency,
supersede, cache, busy); /pi landing rules; 301s; formatter. Existing planner tests still pass.

## Manual walkthrough (local mode, on a copy of Mike's data)
- Landing page at 375 px: reads well, no horizontal scroll, EVE login button present. Profile dropdown fixed to stack on phones.
- Wizard start to finish: order Goal → Logins → Area → Products → Planets → Teamwork → Selling → Batches → Your plan;
  Goal has no ISK cards; one badge per question; advice drops sub-threshold noise; the first plan is saved as the active plan.
- Returning profile with a plan lands on Operate. Operate: no raw IDs, one Consolidate & sell card (Konora 210,139 m³:
  4 DST trips or 1 freighter run; VOC has no pickup in reach).
- `./astracore start` / `status` / `stop` in local mode: backup + migration ran, headers present, no processes left.

## Not done yet / needs Mike
- Real EVE logins (both applications): the SSO round trip, JWT `owner` claim name and scope prompts are verified with
  fakes only. Log in once locally and once in production.
- `./astracore start --prod` was not run by the agent (it publishes the site). Run it, check the domain, then `stop`
  and check the offline page.
- Optional Cloudflare Worker "Astracore is offline" page: not built.
- Final logo/colours, invite list corps/alliances (spec §10).
