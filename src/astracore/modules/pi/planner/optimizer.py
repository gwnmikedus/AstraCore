"""Suggestion engine: which DalShooth templates to place on which planets, for whom.

Two stages so the live sliders stay fast:

1. Pooled integer program over (planet, template) pairs. n[j] = how many of your
   characters place template j on that planet. Factories get a utilisation
   z[j] in [0, n[j]]. Item flows must balance; leftovers are sold. A factory runs no faster
   than its launchpad/storage can buffer for one extractor cycle, so it needs one restock per
   cycle at most.

       maximise  sold value - customs tax
                 - w_m3 * m3/day moved - w_sys * systems used - w_fac * factories

2. Assign the colonies to characters: keep colonies that already exist, keep
   factory chains (factory + its miners) on one character where possible, and
   keep each character in as few systems as possible. Any goods that still have
   to move between characters are listed as transfers.
"""
from __future__ import annotations

import copy
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import pulp

from ..settings import Settings, time_weights
from ..intel import area as area_mod
from ..intel import richness as rich
from ..static_data import dalshooth, voc
from ..static_data.pi_rules import HIGH_TECH_PLANETS, PLANET_TYPES
from ..static_data.sde_loader import PIData
from . import economics as eco
from . import notices, operate, routing, setups, skills, upkeep

NO_FIT = "No templates fit the planets in your area. Allow more systems or more jumps from the drop-off."
MINER_CCU = 4  # DalShooth nullsec miners fit a level-4 command center (lowsec miners need 5)
BUFFER_HEADROOM = 0.99  # factories are planned to fill at most 99% of their space in one cycle


# Search steps per solve (see _solve); the time limit only guards against a stuck solver.
SOLVER_MAX_NODES = 1000
SOLVER_SAFETY_SECONDS = 30

def _factory_planets(sys: dict) -> set:
    """Up to two planets per system are offered as factory sites (keeps the model small):
    one Barren/Temperate (P4-capable) and one other planet."""
    chosen = []
    ht = [p for p in sys["planets"] if p["type"] in HIGH_TECH_PLANETS]
    other = [p for p in sys["planets"] if p["type"] not in HIGH_TECH_PLANETS
             and p["type"] not in ("Shattered", "Unknown")]
    if ht:
        chosen.append(ht[-1]["planet_id"])
    if other:
        chosen.append(other[-1]["planet_id"])
    return set(chosen)


def existing_product(pi: PIData, col: dict) -> Optional[int]:
    best, best_tier = None, -1
    for pin in col.get("pins", []):
        sid = pin.get("schematic_id")
        if sid and sid in pi.schematics:
            out = pi.schematics[sid].output
            if pi.tier(out) > best_tier:
                best, best_tier = out, pi.tier(out)
    if best is None:
        for pin in col.get("pins", []):
            ex = pin.get("extractor_details") or {}
            if ex.get("product_type_id"):
                return ex["product_type_id"]
    return best


def resolve_hub(area: dict, s: Settings, systems: Dict[int, dict], overrides: dict) -> Optional[dict]:
    """The hub is where products are dropped off for selling. Auto mode prefers a VOC
    courier/buyback location close to the selected space; otherwise the best PI spot."""
    if s.hub_system:
        hub = area_mod.system_by_name(area, s.hub_system)
        if hub:
            return hub
    sub = {"systems": {str(k): {**v, "neighbours": [n for n in v["neighbours"] if n in systems]}
                       for k, v in systems.items()}}
    best_pi = area_mod.suggest_hub(sub, overrides)
    voc_hubs = [area_mod.system_by_name(area, n) for n in voc.COURIER_ORIGINS]
    voc_hubs = [h for h in voc_hubs if h]
    if voc_hubs and best_pi:
        dist = area_mod.jumps_from(area, best_pi["system_id"])
        near = [h for h in voc_hubs if dist.get(h["system_id"], 99) <= 3]
        if near:
            return min(near, key=lambda h: dist.get(h["system_id"], 99))
    return best_pi


# ----------------------------------------------------------------------------- stage 1
def _solve(pi: PIData, s: Settings, systems: Dict[int, dict], hub_id: int, area: dict,
           n_chars: int, total_slots: int, max_slots: int, slots_by_ccu: Dict[int, int],
           prices: Dict[int, float],
           templates: List[dict], overrides: dict, head_yield: float, characters: List[dict]):
    dist = area_mod.jumps_from(area, hub_id)
    scope = {sid: sys for sid, sys in systems.items() if dist.get(sid, 999) <= s.max_jumps}
    black = {b.lower() for b in s.product_blacklist}
    per_planet_cap = max(1, min(int(s.per_planet), n_chars))
    stack = max(0.0, min(1.0, s.stack_yield_pct / 100.0))
    poco = skills.customs_rates(characters)
    planets: Dict[int, dict] = {}
    cands: List[Tuple[int, setups.Setup, int]] = []
    cache: Dict[Tuple, List[Tuple[setups.Setup, int]]] = {}
    for sid, sys in scope.items():
        fac_ok = _factory_planets(sys)
        for p in sys["planets"]:
            r = rich.richness(p["planet_id"], sys["security"], overrides)
            planets[p["planet_id"]] = {**p, "system_id": sid, "system": sys["name"],
                                       "security": sys["security"], "richness": r}
            ok = p["planet_id"] in fac_ok
            key = (p["type"], round(r, 2), ok, sys["security"] < 0)
            if key not in cache:
                rate = setups.head_rate(head_yield, r, s.cycle_days)
                base = setups.for_planet(pi, p["type"], rate, templates, sys["security"],
                                         s.max_tier, ok, black)
                # More of your colonies extracting the same P0 on one planet share its deposits:
                # copy k of a miner yields stack^k of the first.
                opts = []
                for st in base:
                    copies = per_planet_cap if st.kind == "miner" else 1
                    for k in range(copies):
                        opts.append((setups.with_yield(pi, st, rate * stack ** k) if k else st, k))
                cache[key] = opts
            cands += [(p["planet_id"], st, k) for st, k in cache[key]]
    if not cands:
        return None, planets, scope, NO_FIT

    w = time_weights(s)
    per_planet = per_planet_cap
    prob = pulp.LpProblem("pi", pulp.LpMaximize)
    n = {j: pulp.LpVariable(f"n{j}", lowBound=0, upBound=1 if st.kind == "miner" else per_planet, cat="Integer")
         for j, (_, st, _) in enumerate(cands)}
    z = {j: pulp.LpVariable(f"z{j}", lowBound=0, upBound=per_planet)
         for j, (_, st, _) in enumerate(cands) if st.scalable}
    first_copy = {}
    for j, (pid, st, k) in enumerate(cands):
        if st.kind == "miner":
            if k == 0:
                first_copy[(pid, st.product)] = j
            else:  # a shared-deposit copy only after the full-yield one
                prob += n[j] <= n[first_copy[(pid, st.product)]]
    y = {sid: pulp.LpVariable(f"y{sid}", cat="Binary") for sid in scope}
    use = {j: (z[j] if j in z else n[j]) for j in n}

    cycle = max(0.0, float(s.cycle_days))

    def room(st: setups.Setup) -> float:
        # a little headroom so the rounded per-day flows shown on the plan still pass upkeep's check
        return upkeep.plan_capacity(st.layout) * BUFFER_HEADROOM

    produced, consumed = defaultdict(list), defaultdict(list)
    tax, m3, fac = [], [], []
    by_planet, by_system = defaultdict(list), defaultdict(list)
    for j, (pid, st, _) in enumerate(cands):
        u = use[j]
        if j in z:
            prob += z[j] <= n[j]
            fac.append(n[j])
            # One restock per extractor cycle: the launchpad/storage space must hold a full cycle of
            # inputs (and of the products made meanwhile), so run the factory no faster than that.
            per_cycle = max(eco.m3(pi, st.inputs), eco.m3(pi, st.out)) * cycle
            if per_cycle > room(st):
                prob += per_cycle * z[j] <= room(st) * n[j]
        for t, q in st.out.items():
            produced[t].append(q * u)
        for t, q in st.inputs.items():
            consumed[t].append(q * u)
        rate = poco.get(planets[pid]["system_id"])
        tax.append((eco.export_tax(pi, s, st.out, rate) + eco.import_tax(pi, s, st.inputs, rate)) * u)
        m3.append((eco.m3(pi, st.out) + eco.m3(pi, st.inputs)) * u)
        by_planet[pid].append(n[j])
        by_system[planets[pid]["system_id"]].append(n[j])

    sold = {}
    for t in set(produced) | set(consumed):
        v = pulp.LpVariable(f"s{t}", lowBound=0)
        prob += v == pulp.lpSum(produced.get(t, [])) - pulp.lpSum(consumed.get(t, []))
        sold[t] = v
    keep = 1.0  # values are already net of taxes, courier and buyback cuts
    prob += (pulp.lpSum(prices.get(t, 0.0) * keep * v for t, v in sold.items())
             - pulp.lpSum(tax) - w["isk_per_m3"] * pulp.lpSum(m3)
             - w["isk_per_system"] * pulp.lpSum(y.values())
             - w["isk_per_factory"] * pulp.lpSum(fac)
             - 1.0 * pulp.lpSum(n.values()))  # tie-breaker: never place a colony that adds nothing
    for vars_ in by_planet.values():
        prob += pulp.lpSum(vars_) <= per_planet
    for sid, vars_ in by_system.items():
        prob += pulp.lpSum(vars_) <= per_planet * len(scope[sid]["planets"]) * y[sid]
    prob += pulp.lpSum(n.values()) <= total_slots
    for lvl in sorted({st.min_ccu for _, st, _ in cands}):
        # colonies needing at least this CCU level must fit in the slots of characters that have it
        cap = sum(v for c, v in slots_by_ccu.items() if c >= lvl)
        prob += pulp.lpSum(n[j] for j, (_, st, _) in enumerate(cands) if st.min_ccu >= lvl) <= cap
    if not s.cross_character and z:
        # Each factory plus everything feeding it must fit in one character's slots.
        typical = defaultdict(list)
        for _, st, _ in cands:
            for t, q in st.out.items():
                typical[t].append(q)
        avg_out = {t: sum(v) / len(v) for t, v in typical.items()}
        feeders = []
        for j in z:
            st = cands[j][1]
            need = sum(q / avg_out[t] for t, q in st.inputs.items() if avg_out.get(t))
            feeders.append(need * z[j])
        prob += pulp.lpSum(feeders) <= (max_slots - 1) * pulp.lpSum(n[j] for j in z)
    if s.max_systems > 0:
        prob += pulp.lpSum(y.values()) <= s.max_systems

    # A node limit, not a clock, ends the search: the same inputs always give the same plan, however busy
    # the machine is. The plan is found early; the rest of a long search only proves it within 1%.
    # The time limit is a safety net that a normal solve never reaches.
    status = prob.solve(pulp.PULP_CBC_CMD(msg=False, maxNodes=SOLVER_MAX_NODES, threads=1, gapRel=0.01,
                                          timeLimit=max(SOLVER_SAFETY_SECONDS, int(s.solver_time_limit))))
    if prob.objective is None or pulp.value(prob.objective) is None:
        return None, planets, scope, f"Solver: {pulp.LpStatus[status]}"
    instances = []
    for j, (pid, st, share) in enumerate(cands):
        k = int(round(n[j].value() or 0))
        if k <= 0:
            continue
        util = ((z[j].value() or 0.0) / k) if j in z else 1.0
        if util < 0.02:
            continue
        for _ in range(k):
            instances.append({"planet_id": pid, "setup": st, "util": util, "share": share})
    return instances, planets, scope, None


# ----------------------------------------------------------------------------- stage 2
def _links(pi: PIData, instances: List[dict]) -> List[Tuple[int, int, int, float]]:
    """Greedy producer -> consumer matching: (producer idx, consumer idx, item, units/day)."""
    remaining = defaultdict(float)
    producers = defaultdict(list)
    for i, inst in enumerate(instances):
        for t, q in inst["setup"].out.items():
            remaining[(i, t)] = q * inst["util"]
            producers[t].append(i)
    links = []
    consumers = sorted((i for i, x in enumerate(instances) if x["setup"].inputs),
                       key=lambda i: -pi.tier(instances[i]["setup"].product))
    for c in consumers:
        inst = instances[c]
        for t, q in inst["setup"].inputs.items():
            need = q * inst["util"]
            for p in producers[t]:
                if need <= 1e-6:
                    break
                give = min(need, remaining[(p, t)])
                if give > 1e-6:
                    links.append((p, c, t, give))
                    remaining[(p, t)] -= give
                    need -= give
    return links


class _Slots:
    """Bookkeeping for assigning colony instances to characters."""

    def __init__(self, instances: List[dict], characters: List[dict], planets: Dict[int, dict]):
        self.inst, self.planets = instances, planets
        self.free = {c["character_id"]: int(c["slots"]) for c in characters}
        self.ccu = {c["character_id"]: int(c.get("ccu_level", 0)) for c in characters}
        self.used_planets = defaultdict(set)
        self.systems_of = defaultdict(set)
        self.owner: Dict[int, int] = {}
        self.allow_factories = True

    def sys(self, i: int) -> int:
        return self.planets[self.inst[i]["planet_id"]]["system_id"]

    def can(self, i: int, cid: int) -> bool:
        return (self.free[cid] > 0 and self.inst[i]["planet_id"] not in self.used_planets[cid]
                and self.ccu[cid] >= self.inst[i]["setup"].min_ccu)

    def place(self, i: int, cid: int) -> None:
        self.owner[i] = cid
        self.free[cid] -= 1
        self.used_planets[cid].add(self.inst[i]["planet_id"])
        self.systems_of[cid].add(self.sys(i))

    def unplace(self, i: int) -> None:
        cid = self.owner.pop(i)
        self.free[cid] += 1
        self.used_planets[cid].discard(self.inst[i]["planet_id"])
        self.systems_of[cid] = {self.sys(j) for j, c in self.owner.items() if c == cid}

    def keep_existing(self, pi: PIData, characters: List[dict]) -> None:
        for c in characters:
            for col in c.get("colonies", []):
                prod = existing_product(pi, col)
                for i, inst in enumerate(self.inst):
                    if i not in self.owner and inst["planet_id"] == col["planet_id"] \
                            and inst["setup"].product == prod and self.can(i, c["character_id"]):
                        self.place(i, c["character_id"])
                        break

    def place_rest(self) -> None:
        """Remaining (non-chain) colonies: stick to systems a character already visits."""
        rest = sorted((i for i in range(len(self.inst)) if i not in self.owner
                       and (self.allow_factories or not self.inst[i]["setup"].inputs)),
                      key=lambda i: (self.planets[self.inst[i]["planet_id"]]["system"], self.inst[i]["planet_id"]))
        for i in rest:
            sid = self.sys(i)
            opts = [c for c in self.free if self.can(i, c)]
            if opts:
                self.place(i, max(opts, key=lambda c: (sid in self.systems_of[c], -len(self.systems_of[c]), self.free[c])))


    def repair(self, movable=lambda i: True) -> None:
        """Place colonies the greedy pass left over by moving one already placed colony to another
        character (e.g. the only character with a free slot already has a colony on that planet)."""
        for i in range(len(self.inst)):
            if i in self.owner or (not self.allow_factories and self.inst[i]["setup"].inputs):
                continue
            pid = self.inst[i]["planet_id"]
            done = False
            for c in self.free:
                if done or self.ccu[c] < self.inst[i]["setup"].min_ccu:
                    continue
                if self.can(i, c):
                    self.place(i, c)
                    break
                # colonies of c that block i: the one on the same planet, or any (if c is full)
                blockers = [j for j, o in self.owner.items() if o == c and movable(j)
                            and (self.inst[j]["planet_id"] == pid if pid in self.used_planets[c]
                                 else self.free[c] == 0)]
                for j in blockers:
                    dest = [d for d in self.free if d != c and self.can(j, d)]
                    if not dest:
                        continue
                    self.unplace(j)
                    self.place(j, max(dest, key=lambda d: (self.sys(j) in self.systems_of[d], self.free[d])))
                    if self.can(i, c):
                        self.place(i, c)
                        done = True
                        break
                    # moving j didn't free c for i (other blocker): leave it moved, try the next


def _assign(pi: PIData, instances: List[dict], characters: List[dict], planets: Dict[int, dict],
            links: List[Tuple[int, int, int, float]]) -> Dict[int, int]:
    """Cross-character mode: keep chains together where possible, otherwise split them."""
    sl = _Slots(instances, characters, planets)
    sl.keep_existing(pi, characters)
    parent = list(range(len(instances)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for p, c, _, _ in links:
        parent[find(p)] = find(c)
    groups = defaultdict(list)
    for i in range(len(instances)):
        groups[find(i)].append(i)
    for g in sorted((g for g in groups.values() if len(g) > 1), key=len, reverse=True):
        g = [i for i in g if i not in sl.owner]
        pids = {instances[i]["planet_id"] for i in g}
        fits = [c for c in sl.free if sl.free[c] >= len(g) and len(pids) == len(g)
                and not (pids & sl.used_planets[c])
                and all(sl.ccu[c] >= instances[i]["setup"].min_ccu for i in g)]
        if fits:
            sids = {sl.sys(i) for i in g}
            cid = max(fits, key=lambda c: (len(sl.systems_of[c] & sids), sl.free[c]))
            for i in g:
                sl.place(i, cid)
        else:
            for i in g:
                opts = [c for c in sl.free if sl.can(i, c)]
                if opts:
                    sl.place(i, max(opts, key=lambda c: sl.free[c]))
    sl.place_rest()
    sl.repair()
    return sl.owner


def _assign_self_contained(pi: PIData, instances: List[dict], characters: List[dict],
                           planets: Dict[int, dict]) -> Tuple[Dict[int, int], List[Tuple[int, int, int, float]]]:
    """No transfers between characters: every factory gets its feeders on the same character.
    Factory utilisation is reduced to what those feeders can actually supply."""
    sl = _Slots(instances, characters, planets)
    sl.keep_existing(pi, characters)
    links: List[List] = []
    factories = sorted((i for i, x in enumerate(instances) if x["setup"].inputs),
                       key=lambda i: -pi.tier(instances[i]["setup"].product))
    in_chain = set()
    for f in factories:
        if f in in_chain:
            continue
        if f in sl.owner:
            cid = sl.owner[f]
        else:
            opts = [c for c in sl.free if sl.can(f, c)]
            if not opts:
                continue
            cid = max(opts, key=lambda c: (sl.free[c], sl.sys(f) in sl.systems_of[c]))
            sl.place(f, cid)
        in_chain.add(f)
        queue = [f]
        while queue:
            c = queue.pop(0)
            inst = instances[c]
            total = {t: q * inst["util"] for t, q in inst["setup"].inputs.items()}
            need = dict(total)
            stuck = set()
            # Feed all inputs evenly: always top up the input that is relatively the most short.
            while sl.free[cid] > 0:
                open_ = [t for t in need if need[t] > 1e-6 and t not in stuck]
                if not open_:
                    break
                t = max(open_, key=lambda t: need[t] / total[t])
                cand = [p for p in range(len(instances)) if p not in sl.owner
                        and t in instances[p]["setup"].out and sl.can(p, cid)]
                if not cand:
                    stuck.add(t)
                    continue
                p = max(cand, key=lambda p: (sl.sys(p) == sl.sys(f),
                                             instances[p]["setup"].out[t] * instances[p]["util"]))
                sl.place(p, cid)
                give = min(need[t], instances[p]["setup"].out[t] * instances[p]["util"])
                links.append([p, c, t, give])
                need[t] -= give
                if instances[p]["setup"].inputs:
                    in_chain.add(p)
                    queue.append(p)

    # utilisation: bottom-up, a factory runs only as fast as its inputs arrive
    for tier in (2, 3, 4):
        for c in [i for i in sl.owner if instances[i]["setup"].inputs
                  and pi.tier(instances[i]["setup"].product) == tier]:
            st = instances[c]["setup"]
            got = defaultdict(float)
            for lk in links:
                if lk[1] == c:
                    got[lk[2]] += lk[3]
            ratio = min((got[t] / q for t, q in st.inputs.items()), default=0.0)
            new_util = min(instances[c]["util"], ratio)
            old = instances[c]["util"] or 1.0
            instances[c]["util"] = new_util
            for t, q in st.inputs.items():  # surplus inputs are simply sold
                for lk in links:
                    if lk[1] == c and lk[2] == t:
                        lk[3] = min(lk[3], q * new_util)
            for lk in links:  # what this factory hands upward shrinks too
                if lk[0] == c:
                    lk[3] *= new_util / old
    for c in [i for i in list(sl.owner) if instances[i]["setup"].inputs and instances[i]["util"] < 0.02]:
        sl.unplace(c)  # factory that can't be fed on one character: drop it
        links = [lk for lk in links if c not in (lk[0], lk[1])]
    sl.allow_factories = False  # a factory without its own feeders is never worth a slot here
    sl.place_rest()
    linked = {x for lk in links for x in (lk[0], lk[1])}
    sl.repair(movable=lambda j: j not in linked)   # never pull a feeder away from its factory
    return sl.owner, [tuple(lk) for lk in links]


def add_feeds(pi: PIData, colonies: List[dict], links: List[tuple], prices: Dict[int, float]) -> None:
    """Which factories each colony supplies, from the feeder links (producer idx, consumer idx, type, units/day):
    `feeds` = [{character, product, item, units}] per colony. `value_at_factory` marks a feeder whose own
    market value is 0 or not meaningful (product not priced, e.g. after a thin-market re-plan): its ISK is
    counted at the factory it feeds, so it shouldn't read as a worthless colony."""
    by_idx = {c["idx"]: c for c in colonies}
    feeds: Dict[int, Dict[tuple, float]] = defaultdict(lambda: defaultdict(float))
    for p, c, t, q in links:
        if p in by_idx and c in by_idx and q > 0:
            fac = by_idx[c]
            feeds[p][(fac["character"], fac["product"], pi.name(t))] += q
    for col in colonies:
        rows = feeds.get(col["idx"], {})
        col["feeds"] = [{"character": ch, "product": prod, "item": item, "units": round(q, 1)}
                        for (ch, prod, item), q in sorted(rows.items(), key=lambda kv: -kv[1])]
        priced = prices.get(col["product_id"], 0) > 0
        col["value_at_factory"] = bool(col["feeds"]) and (col["value_per_day"] <= 0 or not priced)


# ----------------------------------------------------------------------------- public API
def plan(pi: PIData, s: Settings, area: dict, systems: Dict[int, dict], characters: List[dict],
         prices: Dict[int, float], templates: List[dict], overrides: Optional[dict] = None,
         head_yield: Optional[float] = None) -> dict:
    t0 = time.time()
    overrides = overrides or {}
    head_yield = head_yield or s.head_yield_per_hour
    eligible = [c for c in characters if setups.can_plan(c)]
    warnings = notices.low_ccu(characters, MINER_CCU)
    if not eligible:
        return {"error": "None of your characters can place the templates yet (Command Center Upgrades too low).",
                "warnings": warnings}
    if not systems:
        return {"error": "No area selected yet. Choose where your characters do PI first.", "error_steps": ["area"]}
    hub = resolve_hub(area, s, systems, overrides)
    if not hub:
        return {"error": "Could not determine a drop-off system.", "error_steps": ["area"]}
    if s.hub_system and hub["name"].lower() != s.hub_system.strip().lower():
        warnings.append(notices.note(
            "hub_fallback", f"Your drop-off {s.hub_system} isn't in the selected area, so {hub['name']} is used "
            "instead. Pick another drop-off or add its constellation.", steps=["area"]))

    total_slots = sum(int(c["slots"]) for c in eligible)
    max_slots = max(int(c["slots"]) for c in eligible)
    slots_by_ccu: Dict[int, int] = defaultdict(int)
    for c in eligible:
        slots_by_ccu[int(c["ccu_level"])] += int(c["slots"])
    instances, planets, scope, err = _solve(pi, s, systems, hub["system_id"], area, len(eligible),
                                            total_slots, max_slots, slots_by_ccu, prices, templates,
                                            overrides, head_yield, eligible)
    if err:
        return {"error": err, "warnings": warnings, **({"error_steps": ["area"]} if err == NO_FIT else {})}
    known = {pi.name(t).lower() for t in pi.items}
    unknown = sorted(b for b in s.product_blacklist if b.strip() and b.strip().lower() not in known)
    if unknown:
        warnings.append(notices.note(
            "unknown_product", f"Never produce: {notices.names(unknown)} isn't a PI product name, so nothing was "
            "left out for it. Check the spelling (for example Coolant, Mechanical Parts).", level="info"))
    far = len(systems) - len(scope)
    if far > 0:
        warnings.append(notices.note(
            "out_of_reach", f"{notices.plural(far, 'selected system')} {'is' if far == 1 else 'are'} more than "
            f"{notices.plural(s.max_jumps, 'jump')} from the drop-off {hub['name']} and not used. Raise max jumps "
            "or pick a closer drop-off.",
            guided=f"{notices.plural(far, 'system')} in your area {'is' if far == 1 else 'are'} too far from the "
                   f"drop-off {hub['name']} for your answer and not used.", steps=["area"], level="info"))

    if s.cross_character:
        links = _links(pi, instances)
        owner = _assign(pi, instances, eligible, planets, links)
    else:
        owner, links = _assign_self_contained(pi, instances, eligible, planets)
    by_id = {c["character_id"]: c for c in eligible}
    poco = skills.customs_rates(eligible)
    keep = 1.0  # values are already net of taxes, courier and buyback cuts

    existing = {(c["character_id"], col["planet_id"]): existing_product(pi, col)
                for c in eligible for col in c.get("colonies", [])}
    colonies = []
    check_in_game, other_type = defaultdict(set), set()
    for i, inst in enumerate(instances):
        if i not in owner:
            continue
        st, u, pl = inst["setup"], inst["util"], planets[inst["planet_id"]]
        cid = owner[i]
        out = {t: q * u for t, q in st.out.items()}
        inp = {t: q * u for t, q in st.inputs.items()}
        had = existing.get((cid, pl["planet_id"]), "none")
        action = "new" if had == "none" else ("keep" if had == st.product else "rebuild")
        notes = []
        if inst.get("share"):
            others = notices.plural(inst["share"], "other colony", "other colonies")
            notes.append(f"Shares its {', '.join(pi.name(t) for t in st.p0)} with {others} "
                         f"of yours on this planet: yield estimated at {s.stack_yield_pct ** inst['share'] / 100 ** (inst['share'] - 1):.0f}% "
                         f"of the first. Place heads on a different hotspot.")
        tpl_lvl = st.template.get("ccu_level")
        if tpl_lvl and tpl_lvl > int(by_id[cid].get("ccu_level", 0)):
            check_in_game[by_id[cid]["name"]].add((tpl_lvl, int(by_id[cid].get("ccu_level", 0))))
        tpl_type = PLANET_TYPES.get(st.template.get("planet_type_id"))
        if tpl_type and pl["type"] and tpl_type != pl["type"]:
            other_type.add((tpl_type, pl["type"]))
        rate = poco.get(pl["system_id"])
        colonies.append({
            "idx": i, "character_id": cid, "character": by_id[cid]["name"],
            "system": pl["system"], "system_id": pl["system_id"], "security": pl["security"],
            "planet_id": pl["planet_id"], "planet": pl["name"], "planet_type": pl["type"],
            "richness": round(pl["richness"], 2), "kind": st.kind,
            "product": pi.name(st.product), "product_id": st.product, "tier": pi.tier(st.product),
            "p0": [pi.name(t) for t in st.p0],
            "template": st.template["file"][:-5], "template_file": st.template["file"],
            "template_url": dalshooth.file_url(st.template), "layout": st.layout, "min_ccu": st.min_ccu,
            "utilisation": round(u, 3),
            "out_per_day": {pi.name(t): round(q, 1) for t, q in out.items()},
            "in_per_day": {pi.name(t): round(q, 1) for t, q in inp.items()},
            "value_per_day": round(sum(prices.get(t, 0) * q for t, q in out.items())
                                   - sum(prices.get(t, 0) * q for t, q in inp.items())),
            "m3_per_week": round((eco.m3(pi, out) + eco.m3(pi, inp)) * 7, 1),
            "tax_per_day": round(eco.export_tax(pi, s, out, rate) + eco.import_tax(pi, s, inp, rate)),
            "poco_pct": s.poco_tax_pct if rate is None else rate, "poco_from_esi": rate is not None,
            "action": action, "notes": notes,
        })
    colonies.sort(key=lambda c: (c["character"], c["system"], c["planet"]))
    add_feeds(pi, colonies, links, prices)
    for c in colonies:
        c["upkeep"] = upkeep.plan_buffer(pi, c, s.cycle_days)
    tight = [c for c in colonies if c["upkeep"]["issues"]]
    if tight:
        warnings.append(notices.storage([(c["planet"], c["product"]) for c in tight], s.cycle_days))
    if check_in_game:
        warnings.append(notices.ccu_check_in_game(check_in_game))
    if other_type:
        warnings.append(notices.note(
            "planet_type_check", "Check in game: some templates go on a different planet type than they were "
            "saved on (" + ", ".join(f"{a} → {b}" for a, b in sorted(other_type))
            + "). Apply one and check that every structure lands before relying on the plan."))

    # removals: existing colonies not in the plan
    planned = {(c["character_id"], c["planet_id"]) for c in colonies}
    names = operate.planet_names(area)
    removals = [{"character": by_id[cid]["name"], "character_id": cid, "planet_id": pid,
                 "planet": names.get(pid, {}).get("name", ""), "system": names.get(pid, {}).get("system", ""),
                 "current": pi.name(prod) if prod else "?"}
                for (cid, pid), prod in existing.items() if (cid, pid) not in planned]

    # transfers between characters
    idx_owner = {c["idx"]: c["character"] for c in colonies}
    transfers = defaultdict(float)
    for p, c, t, q in links:
        a, b = idx_owner.get(p), idx_owner.get(c)
        if a and b and a != b:
            transfers[(a, b, pi.name(t))] += q
    transfer_rows = [{"from": a, "to": b, "item": it, "units_per_day": round(q, 1)}
                     for (a, b, it), q in sorted(transfers.items())]
    if transfer_rows and not s.cross_character:
        warnings.append(notices.note(
            "transfers", "Some factory chains don't fit on one character, so a few goods must be contracted "
            "between your characters (see Transfers). Allow trading between characters, or set a lower max tier.",
            guided="Some factory chains don't fit on one character, so a few goods must be contracted between "
                   "your characters (see Transfers). Let your characters supply each other, or process less far.",
            steps=("chain", "tier")))

    # sales
    produced, consumed = defaultdict(float), defaultdict(float)
    for i, inst in enumerate(instances):
        if i not in owner:
            continue
        for t, q in inst["setup"].out.items():
            produced[t] += q * inst["util"]
        for t, q in inst["setup"].inputs.items():
            consumed[t] += q * inst["util"]
    sold = sorted(({"type_id": t, "item": pi.name(t), "tier": pi.tier(t), "units_per_day": round(produced[t] - consumed[t], 1),
                    "isk_per_day": round(prices.get(t, 0.0) * keep * (produced[t] - consumed[t])),
                    "m3_per_week": round((produced[t] - consumed[t]) * pi.volume(t) * 7, 1)}
                   for t in produced if produced[t] - consumed[t] > 0.5), key=lambda r: -r["isk_per_day"])

    # per-character summary + routes
    chars_out = []
    for c in eligible:
        mine = [x for x in colonies if x["character_id"] == c["character_id"]]
        sys_ids = sorted({x["system_id"] for x in mine})
        route = routing.pickup_route(area, hub["system_id"], sys_ids) if sys_ids else None
        chars_out.append({
            "character_id": c["character_id"], "name": c["name"], "slots": int(c["slots"]),
            "used": len(mine), "value_per_day": sum(x["value_per_day"] for x in mine),
            "m3_per_week": round(sum(x["m3_per_week"] for x in mine)),
            "systems": [planets_name for planets_name in sorted({x["system"] for x in mine})],
            "route": route,
        })

    revenue = sum(r["isk_per_day"] for r in sold)
    tax_day = sum(x["tax_per_day"] for x in colonies)
    used_sys = sorted({x["system_id"] for x in colonies})
    miners = sum(1 for x in colonies if x["kind"] == "miner")
    totals = {
        "isk_per_day": round(revenue - tax_day),
        "isk_per_week": round((revenue - tax_day) * 7),
        "m3_per_week": round(sum(x["m3_per_week"] for x in colonies)),
        "systems": len(used_sys),
        "system_visits": sum(len(c["systems"]) for c in chars_out),
        "colonies": len(colonies),
        "slots_total": total_slots,
        "miners": miners,
        "factories": len(colonies) - miners,
        "restarts_per_week": round(miners * 7 / max(0.5, s.cycle_days), 1),
        "transfers": len(transfer_rows),
        "max_tier_used": max((x["tier"] for x in colonies), default=0),
    }
    free = total_slots - len(colonies)
    if free > 0:
        warnings.append(notices.unused_slots(free, s.max_systems, s.max_jumps, s.per_planet))
    if not prices or not any(prices.values()):
        warnings.append(notices.note("no_prices", "No market prices loaded, so ISK values are 0. Refresh prices."))
    return {
        "hub": hub["name"], "hub_id": hub["system_id"], "systems_in_scope": len(scope),
        "solve_seconds": round(time.time() - t0, 2), "head_yield": head_yield,
        "colonies": colonies, "characters": chars_out, "removals": removals,
        "transfers": transfer_rows, "sold": sold, "totals": totals, "warnings": warnings,
        "templates_needed": sorted({x["template_file"] for x in colonies}),
        "tier_need": tier_need(pi, s, templates, colonies),
    }


def tier_need(pi: PIData, s: Settings, templates: List[dict], colonies: List[dict]) -> dict:
    """Why a plan stops below the tier it may use: what one factory of each higher tier eats, in miners.

    `factory_miners[tier]` is how many of this plan's average miners one typical factory of that tier
    needs at full speed; `miners` how many miners the plan has. Empty values where it can't be told."""
    miners = [x for x in colonies if x["kind"] == "miner"]
    p1 = sum(sum(x["out_per_day"].values()) for x in miners)
    per_miner = p1 / len(miners) if miners else 0.0
    out = {"allowed": int(s.max_tier), "used": max((x["tier"] for x in colonies), default=0),
           "miners": len(miners), "factory_miners": {}}
    if per_miner <= 0:
        return out
    for tier in range(2, 5):
        need = setups.factory_p1_need(pi, templates, tier)
        if need:
            out["factory_miners"][str(tier)] = max(1, round(need / per_miner))
    return out


ALTERNATIVES = [
    ("least", "Set and forget", 0),
    ("balanced", "Balanced", 50),
    ("max", "Max ISK", 100),
]


def alternatives(pi: PIData, s: Settings, area: dict, systems: Dict[int, dict], characters: List[dict],
                 prices: Dict[int, float], templates: List[dict], overrides: Optional[dict] = None,
                 head_yield: Optional[float] = None) -> List[dict]:
    """The same settings planned for each goal, each at its default value of the pilot's time."""
    out = []
    for code, name, effort in ALTERNATIVES:
        ss = copy.deepcopy(s)
        ss.effort, ss.hour_isk = effort, -1.0   # same time limit as the live plan, so the cards match it
        res = plan(pi, ss, area, systems, characters, prices, templates, overrides, head_yield)
        out.append({"code": code, "name": name, "effort": effort, "error": res.get("error"),
                    "totals": res.get("totals", {}),
                    "mix": _mix(res.get("colonies", []))})
    # Valuing time lower must never show less ISK. Stage 2 (fitting chains onto characters) and the
    # solver's small optimality gap can make such a plan come out a little lower; in that case show
    # the better plan for that option and point its card at that goal.
    best = None
    for a in out:
        isk = a["totals"].get("isk_per_day")
        if isk is None:
            continue
        if best is not None and isk <= best["totals"]["isk_per_day"]:
            a.update(totals=best["totals"], mix=best["mix"], effort=best["effort"], same_as=best["name"],
                     dominated=True)
        else:
            a["dominated"] = False
            best = a
    return out


def yield_sensitivity(pi: PIData, s: Settings, area: dict, systems: Dict[int, dict], characters: List[dict],
                      prices: Dict[int, float], templates: List[dict], overrides: Optional[dict] = None,
                      head_yield: Optional[float] = None, factors=(0.5, 2.0)) -> List[dict]:
    """The same settings re-planned at other P0 yields: shows how much the estimate matters."""
    base = head_yield or s.head_yield_per_hour
    out = []
    for f in factors:
        res = plan(pi, s, area, systems, characters, prices, templates, overrides, base * f)
        out.append({"factor": f, "head_yield": round(base * f), "error": res.get("error"),
                    "isk_per_day": res.get("totals", {}).get("isk_per_day"),
                    "mix": _mix(res.get("colonies", []))})
    return out


def _mix(colonies: List[dict]) -> str:
    c = defaultdict(int)
    for x in colonies:
        c[f"P{x['tier']} {'factory' if x['kind'] == 'factory' else 'miner'}"] += 1
    return ", ".join(f"{v}× {k}" for k, v in sorted(c.items()))
