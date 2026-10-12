"""Plain-English help for AstraCore PI: the glossary page (/pi/glossary) and the short "?" answers.

Every "?" in the guided setup and the plan result takes its words from `answers()`, so the browser and
the server show the same text, and its "More" link points at a glossary entry here (`/pi/glossary#<id>`).
Keep answers to 1-3 friendly sentences; the glossary entry can say a little more.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .planner import compare
from .static_data import dalshooth

GLOSSARY_URL = "/pi/glossary"

# (id, term, text): the order they appear on the glossary page.
GLOSSARY: List[Dict[str, str]] = [
    {"id": "isk-vs-time", "term": "ISK versus your time",
     "text": "AstraCore doesn't just chase the biggest ISK number. It subtracts the value of your time: hauling, extra "
             "systems on your pickup round and factory restocks all cost minutes, priced at what an hour is worth to "
             "you. That's why a wider area or more processing can show a little less ISK: it's the one that saves you "
             "time. Differences under about 1% or 0.5M ISK a day count as about the same."},
    {"id": "time-estimate", "term": "Your time per week",
     "text": "A rough yardstick, the same for every plan, so answers can be compared fairly. It adds up extractor "
             "restarts, logins, pickups, systems visited, the volume hauled, factory restocks, transfers and "
             "contracts. It's not a stopwatch: use it to compare, not to schedule your evening."},
    {"id": "p0-p4", "term": "P0 to P4",
     "text": "The tiers of PI products. P0 is the raw resource your extractors pull from a planet. A miner colony "
             "turns it into P1. Factory colonies combine P1 into P2, P2 into P3, and P3 (sometimes with P1) into P4. "
             "Each step is worth more per m³, so there's less to haul, but every factory needs feeding."},
    {"id": "higher-tiers", "term": "Why higher tiers are rare",
     "text": "A factory only pays if enough input reaches it. One P3 factory eats the output of many miners, every "
             "factory takes a slot a miner could have used, and only some planets can host one. So with a few "
             "characters, \"Up to P4\" often gives the same plan as \"Up to P2\". That's normal economics, not a bug."},
    {"id": "yield", "term": "Yield estimate and calibration",
     "text": "Yield is how much P0 an extractor head pulls per hour. Until your extractors have run, AstraCore uses an "
             "estimate, scaled by planet richness and how long your extraction program runs. Once your colonies have "
             "run a while, it measures the real rate from ESI (calibration) and plans with that instead."},
    {"id": "shared-deposits", "term": "Shared deposits",
     "text": "Several of your characters can each have a colony on the same planet. When they extract the same "
             "resource, they share its deposits, so each extra colony is counted at a lower yield (by default the "
             "second at 70% of the first, the third at 49%). Placing their heads on different hotspots helps."},
    {"id": "drop-off", "term": "Drop-off",
     "text": "The system where you collect your products before selling or shipping them. Choose somewhere you "
             "can reach near your colonies; available selling routes depend on this choice. Your pickup round "
             "starts and ends there."},
    {"id": "batch", "term": "Batch",
     "text": "Everything you sell in one go: the products collected since the last shipment, sent off together "
             "every week, two weeks or month. Bigger batches spread a courier's minimum fee; smaller ones pay out sooner."},
    {"id": "transfer", "term": "Transfer",
     "text": "Moving products between your own characters, for example one character's P1 feeding another's factory. "
             "You move the items in EVE yourself, for example with an item exchange contract."},
    {"id": "buffer", "term": "Buffer",
     "text": "The space on a colony that holds stock between visits: its launchpads, storage facilities and command "
             "center. The buffer decides how many days a factory can run on one restock, or how long a miner can "
             "fill up before you collect."},
    {"id": "restock", "term": "Restock",
     "text": "Bringing a factory its inputs. On each visit you drop off enough for the next few days (as many as its "
             "buffer holds) and take the products made since last time."},
    {"id": "buyback", "term": "Buyback",
     "text": "Selling products straight to VOC where you are, at a set share of the Jita buy price. No hauling and no "
             "waiting, but a bit less ISK, and VOC's buyback takes P2 and up, not P1."},
    {"id": "voc", "term": "VOC Hauling",
     "text": "A hauling service in Delve (United East-Indian Compagnie). You give them a courier contract at the "
             "drop-off and they fly it to Jita or Amarr for a fee: per m³, with a minimum per contract. They also run "
             "the buyback. AstraCore plans with their published rates; it isn't affiliated with them."},
    {"id": "self-haul", "term": "VOC or hauling yourself",
     "text": "By default the plan ships through VOC, so you don't fly cargo out of null yourself. On the Selling step "
             "you can pick your own trip to Jita or Amarr instead: no courier fee, but the journey time, fuel and "
             "the risk of losing the cargo are yours, and AstraCore doesn't price them."},
    {"id": "ccu", "term": "CCU (Command Center Upgrades)",
     "text": "The skill that sets how much CPU and power a command center has, so which templates fit. DalShooth's "
             "factories need level 2 or 3, nullsec miners level 4 and lowsec miners level 5. Below level 2 a "
             "character can't be planned yet."},
    {"id": "poco", "term": "POCO (customs office)",
     "text": "The Player-Owned Customs Office in orbit around a planet. Every time you launch or import products, its "
             "owner charges a tax. AstraCore uses your Settings value, or the real rate where your characters "
             "can read it."},
    {"id": "esi", "term": "ESI",
     "text": "EVE's official API. With your permission, AstraCore reads your colonies, skills, hangars and contracts "
             "through it. It only reads, except sending waypoints to your client if you allow that.",
     "link": "/what-we-read", "link_label": "What we read"},
    {"id": "dalshooth", "term": "DalShooth templates",
     "text": "Free in-game PI templates made by the community (DalShooth's EVE_PI_Templates). AstraCore picks which "
             "template goes on which planet; it never makes templates itself. You load the template in game and place it.",
     "link": dalshooth.REPO_URL, "link_label": "DalShooth's templates on GitHub"},
]
TERMS = {g["id"] for g in GLOSSARY}


def _num(x: float) -> str:
    return f"{x:g}"


def _term_answer(term_id: str, label: str) -> Dict[str, str]:
    entry = next(entry for entry in GLOSSARY if entry["id"] == term_id)
    return {"label": label, "text": entry["text"], "more": term_id}


def time_note() -> str:
    """How the time estimate adds up: the minutes from planner/compare.py, so they can't drift apart."""
    c = compare
    return (f"A rough yardstick, the same for every answer: {_num(c.MIN_PER_RESTART)} min per extractor restart, "
            f"{_num(c.MIN_PER_LOGIN)} min per character login, {_num(c.MIN_PER_PICKUP)} min per colony pickup and "
            f"{_num(c.MIN_PER_SYSTEM_VISIT)} min per system on each pickup round, {_num(c.MIN_PER_60K_M3)} min per "
            f"60,000 m³ hauled, {_num(c.MIN_PER_RESTOCK)} min per factory restock, {_num(c.MIN_PER_TRANSFER)} min "
            f"per transfer and {_num(c.MIN_PER_BATCH)} min of contracts per batch "
            f"(+{_num(c.MIN_SELL_ORDERS_WEEK)} min a week for sell orders).")


def answers(settings: Any = None, head_yield: float = 0.0, calibrated: bool = False) -> Dict[str, Dict[str, str]]:
    """The "?" answers: {key: {"label": what the button asks, "text": 1-3 sentences, "more": glossary id}}."""
    stack = float(getattr(settings, "stack_yield_pct", 70.0) if settings is not None else 70.0)
    second, third = round(stack), round(stack * stack / 100)
    if calibrated:
        yield_text = ("This yield is measured from your own extractors (calibration), so ISK follows what your "
                      "colonies really produce. It updates as they keep running.")
    else:
        yield_text = (f"Until your extractors have run, AstraCore assumes {head_yield:,.0f} P0 an hour per extractor "
                      "head, scaled by planet richness and program length. Build 2–3 colonies and come back: "
                      "the plan then measures the real rate from your extractors.") if head_yield else (
                      "Until your extractors have run, AstraCore estimates the yield. Build 2–3 colonies and "
                      "come back: the plan then measures the real rate from your extractors.")
    return {
        "dropoff": _term_answer("drop-off", "What is a drop-off?"),
        "transfer": _term_answer("transfer", "What is a transfer between characters?"),
        "batch": _term_answer("batch", "What is a batch?"),
        "isk": {"label": "Why this ISK figure?", "more": "isk-vs-time",
                "text": "The plan weighs ISK against your time: hauling, extra systems and factory restocks cost "
                        "time, valued at what an hour is worth to you. So a wider or deeper option can show a bit "
                        "less ISK when it saves time. Differences under about 1% or 0.5M/day are about the same."},
        "time": {"label": "How is your time estimated?", "more": "time-estimate", "text": time_note()},
        "tier": {"label": "Why does a higher tier often give the same plan?", "more": "higher-tiers",
                 "text": "A factory pays only when enough miners feed it: a P3 factory eats the output of many "
                         "miners, each factory takes a miner's slot, and few planets can host one. The planner "
                         "adds a factory only when the ISK justifies it, so a higher limit often changes nothing."},
        "yield": {"label": "Why is yield an estimate?" if not calibrated else "How is yield measured?",
                  "more": "yield", "text": yield_text},
        "share": {"label": "What do shared colonies yield?", "more": "shared-deposits",
                  "text": f"Your colonies extracting the same resource on one planet share its deposits: the second "
                          f"one is counted at {second}% of the first, the third at {third}%. Put their extractor "
                          f"heads on different hotspots."},
        "upkeep": {"label": "What do restock and buffer mean?", "more": "restock",
                   "text": "A factory runs on inputs you bring it: each restock drops off enough for the days its "
                           "buffer (launchpads and storage) can hold. Miners fill the same space with products, "
                           "so collect before it's full."},
        "voc": {"label": "VOC or haul it yourself?", "more": "self-haul",
                "text": "The plan ships through VOC Hauling: a courier contract from your drop-off to Jita or Amarr, "
                        "priced per m³ with a minimum fee, or their buyback where you are. Your own trip saves the "
                        "fee, but its time, fuel and risk aren't priced in the ISK shown."},
    }


def entries() -> List[Dict[str, str]]:
    return GLOSSARY
