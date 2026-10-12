"""Colony setups = one DalShooth/EVE_PI_Templates template placed on one planet.

Only setups that map 1:1 onto a template from the repo are generated:
  * miner   - "Miner - 00/LS - <P1>": extracts one P0 and turns it into P1 for export.
  * factory - "Factory - <product>": imports inputs and builds a P2/P3/P4 product.
Throughput comes from the template's own structure counts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..static_data import dalshooth
from ..static_data import pi_rules as R
from ..static_data.sde_loader import PIData

BASIC_P1_PER_HOUR = 40.0     # 20 P1 per 30-minute cycle
P0_PER_P1 = 150.0

# Command Center Upgrades levels DalShooth's templates need (template_min_ccu over the repo, 2026-10):
# most factories fit level 2 and every factory fits 3, nullsec miners need 4 and lowsec miners 5.
# Below FACTORY_CCU no template fits, so the planner leaves the character out.
FACTORY_CCU = 2
ALL_FACTORIES_CCU = 3
NULLSEC_MINER_CCU = 4
LOWSEC_MINER_CCU = 5


def can_plan(ch: dict) -> bool:
    """At least one DalShooth template fits the character's command centers."""
    return int(ch.get("ccu_level") or 0) >= FACTORY_CCU


def ccu_note(level) -> dict:
    """What a Command Center Upgrades level allows, and the next level worth training.
    `status` is ok / warn / bad, `label` what fits now, `next` the training advice ('' when nothing is left)."""
    lvl = int(level or 0)
    if lvl >= LOWSEC_MINER_CCU:
        return {"status": "ok", "label": "OK for every template", "next": ""}
    if lvl >= NULLSEC_MINER_CCU:
        return {"status": "ok", "label": f"Nullsec miners and factories (lowsec miners need {LOWSEC_MINER_CCU})",
                "next": ""}
    if lvl >= FACTORY_CCU:
        some = "Factories only" if lvl >= ALL_FACTORIES_CCU else "Most factories only"
        return {"status": "warn", "label": some,
                "next": f"Train Command Center Upgrades to {NULLSEC_MINER_CCU} for nullsec miners "
                        f"({LOWSEC_MINER_CCU} for lowsec)."}
    return {"status": "bad", "label": "Can't be planned yet",
            "next": f"Train Command Center Upgrades to {FACTORY_CCU} to use this character for factories "
                    f"({NULLSEC_MINER_CCU} recommended for nullsec miners)."}


@dataclass
class Setup:
    kind: str                       # miner | factory
    product: int
    template: dict
    out: Dict[int, float]           # units/day leaving the planet at full utilisation
    inputs: Dict[int, float] = field(default_factory=dict)   # units/day imported
    p0: List[int] = field(default_factory=list)

    @property
    def min_ccu(self) -> int:
        return template_min_ccu(self.template)

    @property
    def scalable(self) -> bool:
        return self.kind == "factory"

    @property
    def layout(self) -> Dict[str, int]:
        t = self.template
        keys = ("ecus", "heads", "basic", "advanced", "hightech", "launchpads", "storage")
        return {k: t[k] for k in keys if t.get(k)}


def template_min_ccu(tpl: dict) -> int:
    """Lowest Command Center level whose CPU/PG fits the template's structures."""
    counts = {k: v for k, v in dict(ecu=tpl.get("ecus"), head=tpl.get("heads"), basic=tpl.get("basic"),
                                    advanced=tpl.get("advanced"), hightech=tpl.get("hightech"),
                                    launchpad=tpl.get("launchpads"), storage=tpl.get("storage")).items() if v}
    for lvl in range(6):
        if R.fits(lvl, **counts):
            return lvl
    return 6  # doesn't fit at all


def head_rate(head_yield: float, richness: float, cycle_days: float) -> float:
    return head_yield * richness * R.cycle_factor(cycle_days)


def p1_from_p0(pi: PIData) -> Dict[int, int]:
    out = {}
    for p1 in pi.of_tier(1):
        r = pi.recipe(p1)
        if r and len(r.inputs) == 1:
            out[next(iter(r.inputs))] = p1
    return out


def miners(pi: PIData, planet_type: str, rate: float, templates: List[dict],
           security: float) -> List[Setup]:
    res = []
    mapping = p1_from_p0(pi)
    for p0 in pi.p0_by_planet.get(planet_type, []):
        p1 = mapping.get(p0)
        tpl = dalshooth.find(templates, "miner", p1, security) if p1 else None
        if not tpl or not tpl["heads"] or not tpl["basic"]:
            continue
        p1_hour = min(tpl["heads"] * rate / P0_PER_P1, tpl["basic"] * BASIC_P1_PER_HOUR)
        res.append(Setup(kind="miner", product=p1, template=tpl, out={p1: p1_hour * 24}, p0=[p0]))
    return res


def with_yield(pi: PIData, st: Setup, rate: float) -> Setup:
    """Same miner at a different P0 rate (e.g. sharing the resource with another colony)."""
    tpl = st.template
    p1_hour = min(tpl["heads"] * rate / P0_PER_P1, tpl["basic"] * BASIC_P1_PER_HOUR)
    return Setup(kind=st.kind, product=st.product, template=tpl, out={st.product: p1_hour * 24}, p0=list(st.p0))


def factories(pi: PIData, planet_type: str, templates: List[dict], max_tier: int) -> List[Setup]:
    res = []
    for tpl in templates:
        if tpl["kind"] != "factory" or not tpl.get("product_id"):
            continue
        prod = tpl["product_id"]
        tier = pi.tier(prod)
        if tier < 2 or tier > max_tier:
            continue
        if tier == 4 and planet_type not in R.HIGH_TECH_PLANETS:
            continue
        r = pi.recipe(prod)
        n = tpl["hightech"] if tier == 4 else tpl["advanced"]
        if not r or not n:
            continue
        res.append(Setup(kind="factory", product=prod, template=tpl,
                         out={prod: r.per_hour_out() * n * 24},
                         inputs={t: q * n * 24 for t, q in r.per_hour_in().items()}))
    return res


def p1_equivalent(pi: PIData, tid: int, _depth: int = 0) -> float:
    """P1 units that go into one unit of `tid` (1 for a P1 product, 0 if unknown)."""
    tier = pi.tier(tid)
    if tier <= 1:
        return 1.0 if tier == 1 else 0.0
    r = pi.recipe(tid)
    out = r.per_hour_out() if r else 0.0
    if not out or _depth > 4:
        return 0.0
    return sum(q / out * p1_equivalent(pi, t, _depth + 1) for t, q in r.per_hour_in().items())


def factory_p1_need(pi: PIData, templates: List[dict], tier: int) -> Optional[float]:
    """P1 per day a typical DalShooth factory of this tier uses at full speed, counting P2/P3 inputs as the
    P1 that went into them: the median over the templates. None when no template of that tier exists."""
    needs = []
    for tpl in templates:
        prod = tpl.get("product_id")
        if tpl.get("kind") != "factory" or not prod or pi.tier(prod) != tier:
            continue
        r = pi.recipe(prod)
        n = tpl.get("hightech") if tier == 4 else tpl.get("advanced")
        if not r or not n:
            continue
        need = sum(q * n * 24 * p1_equivalent(pi, t) for t, q in r.per_hour_in().items())
        if need > 0:
            needs.append(need)
    if not needs:
        return None
    needs.sort()
    return needs[len(needs) // 2]


def for_planet(pi: PIData, planet_type: str, rate: float, templates: List[dict], security: float,
               max_tier: int, factory_ok: bool, blacklist: Optional[set] = None) -> List[Setup]:
    if planet_type in ("Shattered", "Unknown"):
        return []
    res = miners(pi, planet_type, rate, templates, security)
    if factory_ok and max_tier >= 2:
        res += factories(pi, planet_type, templates, max_tier)
    black = blacklist or set()
    return [x for x in res if pi.name(x.product).lower() not in black]
