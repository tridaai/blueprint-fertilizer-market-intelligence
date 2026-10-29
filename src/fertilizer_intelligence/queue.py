"""The shortage & gap action queue (R13, roadmap
F21-OW2).

Every tight or short supply gap becomes a work item with
an owner, a due state and a slot for a linked mitigation
scenario. The queue follows the repo's established
discipline — the alert lifecycle's discipline, applied to
gaps:

- **Membership is derived from the gap artefacts.** The
  queue holds exactly one item per non-comfortable gap
  head: the current head of every product × season gap
  family whose band is tight or short. When a family's
  head moves — a successor gap struck over a moved
  record — the successor's item is the member and the
  old item leaves the queue view, though its acts stay
  on record forever.
- **An item is struck with an owner.** The queue pack
  names a default owner per product; the item carries
  that name from its first moment, so a gap is never
  ownerless while it waits for a human to pick it up.
- **State is a fold of acts.** Assign, start, link a
  mitigation scenario, close — each a named, attributed,
  insert-only act. The item's current owner is the
  latest assign (or the struck default), its scenario
  slot is the latest link, its state is the fold. A
  close is valid only with a reason from the pack's
  stated vocabulary, and a link is valid only to a
  scenario fork that exists in the store — forks are
  linked by reference, never copied.
- **Due state is derived, never stored.** The item
  carries a due date struck from its band's term in the
  pack; whether it reads within term, due today, overdue
  or closed is computed at the read date.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

from pydantic import BaseModel

from . import queue_rules as pack
from . import supply_rules as supply_pack
from .demand import head_of
from .generator import PRODUCTS


class QueueStateError(RuntimeError):
    """An act was attempted against a queue item whose
    derived state does not allow it (starting a started
    item, acting on a closed item, acting on a missing
    item)."""


# ---------------------------------------------------------------------------
# Artefacts
# ---------------------------------------------------------------------------


class GapQueueItem(BaseModel):
    item_id: str
    fingerprint: str
    gap_id: str
    product: str
    crop_year: str
    season: str
    band: str  # tight / short, as struck
    gap_pct_of_demand: float
    slipped_tonnes: float
    default_owner: str
    struck_on: str  # the date the item was struck
    due_date: str  # struck_on + the pack's term for the band
    rules_version: str


class QueueAct(BaseModel):
    act_id: str
    item_id: str
    act: str  # assign / start / link_scenario / close
    actor: str
    as_of: str
    reason: str | None = None  # a close's stated reason, from the pack
    owner: str | None = None  # an assign's new owner
    fork_id: str | None = None  # a link's scenario fork, by reference
    note: str | None = None


def _fingerprint(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def item_id_for(gap: dict) -> str:
    """One item per gap artefact: the id is a function of
    the gap it answers, so a successor gap is a successor
    item and the same gap never yields two."""
    fingerprint = _fingerprint({
        "gap": gap["gap_id"], "pack": pack.RULES_VERSION,
    })
    return f"GAPQ-{fingerprint[:10]}"


def build_item(gap: dict, struck_on: str) -> GapQueueItem:
    """Strike (do not store) the item one gap artefact
    answers for: owner from the pack, due date from the
    band's stated term."""
    due = date.fromisoformat(struck_on) + timedelta(
        days=pack.DUE_DAYS[gap["band"]])
    fingerprint = _fingerprint({
        "gap": gap["gap_id"], "band": gap["band"],
        "struck_on": struck_on, "pack": pack.RULES_VERSION,
    })
    return GapQueueItem(
        item_id=item_id_for(gap), fingerprint=fingerprint,
        gap_id=gap["gap_id"], product=gap["product"],
        crop_year=gap["crop_year"], season=gap["season"],
        band=gap["band"],
        gap_pct_of_demand=gap["gap_pct_of_demand"],
        slipped_tonnes=gap["slipped_tonnes"],
        default_owner=pack.DEFAULT_OWNERS.get(
            gap["product"], pack.DEFAULT_OWNER_FALLBACK),
        struck_on=struck_on, due_date=due.isoformat(),
        rules_version=pack.RULES_VERSION,
    )


# ---------------------------------------------------------------------------
# Membership — derived from the gap artefacts, never curated
# ---------------------------------------------------------------------------


def member_gaps(store) -> list[dict]:
    """The queue's membership, derived: the head of every
    gap family whose band is not comfortable, in the
    queue's stated order (worst band first, then the
    furthest under demand, then product and season)."""
    families: dict[tuple, list[dict]] = {}
    for product in PRODUCTS:
        for gap in store.list_gaps(product):
            families.setdefault(
                (gap["product"], gap["crop_year"], gap["season"]),
                []).append(gap)
    members = []
    for rows in families.values():
        head = head_of(rows, "gap_id")
        if head is not None and head["band"] != "comfortable":
            members.append(head)
    return sorted(members, key=lambda g: (
        -supply_pack.BAND_RANK[g["band"]],
        g["gap_pct_of_demand"],
        g["product"], g["crop_year"], g["season"],
    ))


# ---------------------------------------------------------------------------
# State — the fold of acts
# ---------------------------------------------------------------------------


def derive_state(acts: list[dict]) -> str:
    """An item's state is the fold of its acts: open until
    a start, in progress until a close, closed for good.
    Assigns and links do not move the state."""
    state = pack.STATE_OPEN
    for act in acts:
        if act["act"] == pack.ACT_START:
            state = pack.STATE_IN_PROGRESS
        elif act["act"] == pack.ACT_CLOSE:
            state = pack.STATE_CLOSED
    return state


def due_state(item: dict, state: str, as_of: str) -> str:
    """The due reading at a date, derived from the struck
    due date — never a stored flag."""
    if state == pack.STATE_CLOSED:
        return pack.DUE_CLOSED
    if as_of > item["due_date"]:
        return pack.DUE_OVERDUE
    if as_of == item["due_date"]:
        return pack.DUE_TODAY
    return pack.DUE_WITHIN_TERM


def item_view(store, item: dict, as_of: str) -> dict:
    """One item with everything a reader needs: its acts,
    its folded state, its current owner and scenario slot
    (the latest acts of their kinds, or the struck
    defaults), and its due state at the read date."""
    acts = store.list_queue_acts(item["item_id"])
    state = derive_state(acts)
    owner = item["default_owner"]
    fork_id = None
    for act in acts:
        if act["act"] == pack.ACT_ASSIGN and act["owner"]:
            owner = act["owner"]
        elif act["act"] == pack.ACT_LINK_SCENARIO:
            fork_id = act["fork_id"]
    return {
        **item,
        "acts": acts,
        "state": state,
        "owner": owner,
        "scenario_fork_id": fork_id,
        "due_state": due_state(item, state, as_of),
    }


def queue_views(store, as_of: str) -> list[dict]:
    """The queue as read at a date: one view per member
    gap, in membership order. A member gap with no struck
    item is a defect the verifier names — the service
    strikes missing items before it reads the queue."""
    views = []
    for gap in member_gaps(store):
        item = store.get_queue_item(item_id_for(gap))
        if item is None:
            continue
        views.append(item_view(store, item, as_of))
    return views


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_queue(store, as_of: str) -> list[str]:
    """Re-derive the queue from the gap artefacts and the
    acts: membership must be exactly the non-comfortable
    gap heads, each with exactly its one item; every
    item's folded state, owner, scenario slot and due
    state must re-derive; every act on record must be a
    valid act — a close speaking the pack's vocabulary, a
    link naming a fork that exists."""
    problems: list[str] = []
    members = member_gaps(store)
    member_item_ids = {item_id_for(g) for g in members}
    for gap in members:
        item = store.get_queue_item(item_id_for(gap))
        if item is None:
            problems.append(
                f"member gap {gap['gap_id']} ({gap['product']} "
                f"{gap['season']} {gap['crop_year']}, {gap['band']}) "
                "has no queue item")
    views = queue_views(store, as_of)
    if [v["item_id"] for v in views] != [
            item_id_for(g) for g in members
            if store.get_queue_item(item_id_for(g)) is not None]:
        problems.append("queue view membership does not match the "
                        "derived membership order")
    for item in store.list_queue_items():
        acts = store.list_queue_acts(item["item_id"])
        state = "open"
        owner = item["default_owner"]
        fork_id = None
        for act in acts:
            if act["act"] not in pack.ACTS:
                problems.append(
                    f"{item['item_id']}: unknown act {act['act']!r}")
            if act["act"] == "start":
                state = "in_progress"
            elif act["act"] == "close":
                state = "closed"
                if act["reason"] not in pack.CLOSE_REASONS:
                    problems.append(
                        f"{item['item_id']}: close reason "
                        f"{act['reason']!r} is outside the pack "
                        "vocabulary")
            elif act["act"] == "assign":
                if not act["owner"]:
                    problems.append(
                        f"{item['item_id']}: an assign names no owner")
                else:
                    owner = act["owner"]
            elif act["act"] == "link_scenario":
                fork_id = act["fork_id"]
                if not fork_id or store.get_scenario_fork(fork_id) is None:
                    problems.append(
                        f"{item['item_id']}: linked scenario "
                        f"{fork_id!r} is not a stored fork")
        view = item_view(store, item, as_of)
        if view["state"] != state or view["owner"] != owner \
                or view["scenario_fork_id"] != fork_id:
            problems.append(
                f"{item['item_id']}: folded view does not re-derive")
        rebuilt = build_item(
            {"gap_id": item["gap_id"], "product": item["product"],
             "crop_year": item["crop_year"], "season": item["season"],
             "band": item["band"],
             "gap_pct_of_demand": item["gap_pct_of_demand"],
             "slipped_tonnes": item["slipped_tonnes"]},
            item["struck_on"])
        if rebuilt.model_dump() != item:
            problems.append(
                f"{item['item_id']}: item does not re-perform from its "
                "gap and struck date")
    return problems
