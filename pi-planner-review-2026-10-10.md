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
