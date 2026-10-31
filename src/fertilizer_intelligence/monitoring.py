"""Cost, freshness & reliability monitoring (R18,
roadmap F21-AM2): the per-run cost ledger, and the
monitoring board struck from the record.

The engines measure the market; this layer measures
the system. It has three parts, all under the
monitoring pack:

- **The run ledger.** A recording wrapper stands
  between the service and its model port on the
  service's own drafting paths. Every completed call
  lands as an insert-only run record — purpose,
  profile, model, tokens, and the cost the pack's
  integer rates price them at — numbered in a
  gapless sequence, so the ledger is a sequence to
  reconcile, not a pile to sample. The wrapper
  records hashes of the prompt and the reply, never
  the text: the ledger prices calls, it does not
  become a second copy of what was said.
- **The freshness board.** Per registered source:
  the newest fact date it has landed by the board
  date, that fact's age against the registry's
  freshness window, and the state the pack names —
  fresh, stale, or never loaded, with the never-
  loaded sources named rather than absent.
- **The reliability lines.** Per source, the fold
  of its batch reports and the corrections recorded
  against its fact class; per reporter, the fold
  of their landed reports, their review outcomes
  and their screening record. Every figure derives
  from stored artefacts and acts alone; a rate with
  nothing decided behind it is stated as unmeasured.
  The board is advisory, exactly like the integrity
  board: striking it writes nothing back, moves no
  weight and changes no standing.

The board is an insert-only artefact: re-striking
at a later date supersedes the head by link, the
same strike repeated is the same artefact, and the
verifier re-performs every run record and every
board by a second route, its totals cross-checked
by direct sums over the ledger.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from pydantic import BaseModel

from . import configuration as config_engine
from . import ingest_rules as ingest_pack
from . import monitoring_rules as pack


def _fingerprint(payload: dict) -> str:
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# The run ledger: every service model call, recorded.
# ---------------------------------------------------------------------------


class ModelRun(BaseModel):
    run_id: str
    fingerprint: str
    seq: int
    purpose: str
    profile: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_nano_usd: int | None
    prompt_sha256: str
    reply_sha256: str
    at: str
    rules_version: str


def build_run(store, purpose: str, reply, at: str,
              prompt: str) -> ModelRun:
    """The run record for one completed call, priced
    by the pack. The sequence number is the ledger's
    own count at strike time, so the ids form the
    gapless sequence the verifier reconciles."""
    if purpose not in pack.PURPOSES:
        raise ValueError(
            f"run purpose {purpose!r} is outside the "
            f"monitoring pack's vocabulary "
            f"{sorted(pack.PURPOSES)}")
    try:
        date.fromisoformat(at)
    except (TypeError, ValueError):
        raise ValueError(
            f"run date is not an ISO date: {at!r}") from None
    seq = len(store.list_model_runs()) + 1
    cost = pack.cost_nano_usd(
        reply.profile, reply.input_tokens, reply.output_tokens)
    fingerprint = _fingerprint({
        "seq": seq, "purpose": purpose,
        "profile": reply.profile, "model": reply.model,
        "input_tokens": reply.input_tokens,
        "output_tokens": reply.output_tokens,
        "cost_nano_usd": cost,
        "prompt_sha256": _sha256(prompt),
        "reply_sha256": _sha256(reply.text),
        "at": at, "pack": pack.RULES_VERSION,
    })
    return ModelRun(
        run_id=f"RUN-{seq:06d}", fingerprint=fingerprint,
        seq=seq, purpose=purpose, profile=reply.profile,
        model=reply.model,
        input_tokens=reply.input_tokens,
        output_tokens=reply.output_tokens,
        cost_nano_usd=cost,
        prompt_sha256=_sha256(prompt),
        reply_sha256=_sha256(reply.text), at=at,
        rules_version=pack.RULES_VERSION)


class RecordingPort:
    """The wrapper the service puts around its own
    port at each drafting handoff: the call delegates
    untouched, and a completed call lands its run
    record before the reply travels on. A call the
    inner port refuses raises through and records
    nothing — the ledger counts runs, not attempts."""

    def __init__(self, inner, store, purpose: str, at: str):
        if purpose not in pack.PURPOSES:
            raise ValueError(
                f"run purpose {purpose!r} is outside the "
                f"monitoring pack's vocabulary "
                f"{sorted(pack.PURPOSES)}")
        self._inner = inner
        self._store = store
        self._purpose = purpose
        self._at = at

    @property
    def profile_name(self) -> str:
        return self._inner.profile_name

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    def complete(self, system: str, prompt: str):
        reply = self._inner.complete(system, prompt)
        run = build_run(self._store, self._purpose, reply,
                        self._at, prompt)
        self._store.insert_model_run(run.model_dump())
        return reply


# ---------------------------------------------------------------------------
# The monitoring board: struck from the record.
# ---------------------------------------------------------------------------


class MonitoringBoard(BaseModel):
    board_id: str
    fingerprint: str
    as_of: str
    cost: dict
    freshness: list[dict]
    reliability_sources: list[dict]
    reliability_reporters: list[dict]
    totals: dict
    rules_version: str
    supersedes: str | None = None


def _cost_section(runs: list[dict]) -> dict:
    def fold(rows: list[dict], key: str) -> list[dict]:
        grouped: dict[str, dict] = {}
        for run in rows:
            line = grouped.setdefault(run[key], {
                key: run[key], "runs": 0, "input_tokens": 0,
                "output_tokens": 0, "cost_nano_usd": 0,
                "unrated_runs": 0})
            line["runs"] += 1
            line["input_tokens"] += run["input_tokens"]
            line["output_tokens"] += run["output_tokens"]
            if run["cost_nano_usd"] is None:
                line["unrated_runs"] += 1
            else:
                line["cost_nano_usd"] += run["cost_nano_usd"]
        return [grouped[k] for k in sorted(grouped)]

    return {
        "runs": len(runs),
        "input_tokens": sum(r["input_tokens"] for r in runs),
        "output_tokens": sum(r["output_tokens"] for r in runs),
        "cost_nano_usd": sum(
            r["cost_nano_usd"] for r in runs
            if r["cost_nano_usd"] is not None),
        "unrated_runs": sum(
            1 for r in runs if r["cost_nano_usd"] is None),
        "by_profile": fold(runs, "profile"),
        "by_purpose": fold(runs, "purpose"),
    }


def _freshness_rows(store, as_of: str) -> list[dict]:
    board_day = date.fromisoformat(as_of)
    # Freshness is judged under the windows in force at
    # the board's date (R19): the configuration
    # register's version when one governs, the ingest
    # registry's otherwise. The board row carries the
    # window it was judged under, so the re-performance
    # in verify resolves the same way and compares.
    windows = config_engine.resolve_config(
        store, "freshness", as_of)["values"]["windows_days"]
    rows: list[dict] = []
    for source_id in sorted(ingest_pack.SOURCES):
        entry = {**ingest_pack.SOURCES[source_id],
                 "freshness_days": windows.get(
                     source_id,
                     ingest_pack.SOURCES[source_id]["freshness_days"])}
        batches = [
            b for b in store.list_ingest_batches(source_id=source_id)
            if b["load_date"] <= as_of]
        fact_dates = [
            content["as_of"]
            for batch in batches
            for content in batch["inserted_rows"].values()
            if content.get("as_of")]
        if not batches:
            rows.append({
                "source_id": source_id,
                "fact_class": entry["fact_class"],
                "cadence": entry["cadence"],
                "owner": entry["owner"],
                "window_days": entry["freshness_days"],
                "batches": 0, "last_load_date": None,
                "last_fact_as_of": None, "age_days": None,
                "state": pack.STATE_NEVER_LOADED})
            continue
        last_fact = max(fact_dates) if fact_dates else None
        age = (board_day - date.fromisoformat(last_fact)).days \
            if last_fact else None
        state = pack.STATE_FRESH \
            if age is not None and age <= entry["freshness_days"] \
            else pack.STATE_STALE
        rows.append({
            "source_id": source_id,
            "fact_class": entry["fact_class"],
            "cadence": entry["cadence"],
            "owner": entry["owner"],
            "window_days": entry["freshness_days"],
            "batches": len(batches),
            "last_load_date": max(b["load_date"] for b in batches),
            "last_fact_as_of": last_fact,
            "age_days": age,
            "state": state})
    return rows


def _source_reliability_rows(store, as_of: str) -> list[dict]:
    rows: list[dict] = []
    for source_id in sorted(ingest_pack.SOURCES):
        entry = ingest_pack.SOURCES[source_id]
        batches = [
            b for b in store.list_ingest_batches(source_id=source_id)
            if b["load_date"] <= as_of]
        if not batches:
            continue
        received = sum(b["received"] for b in batches)
        quarantined = sum(b["quarantined"] for b in batches)
        corrections = len([
            c for c in store.list_fact_corrections(
                fact_class=entry["fact_class"])
            if c["as_of"] <= as_of])
        rows.append({
            "source_id": source_id,
            "fact_class": entry["fact_class"],
            "batches": len(batches),
            "received": received,
            "inserted": sum(b["inserted"] for b in batches),
            "duplicates": sum(b["duplicates"] for b in batches),
            "quarantined": quarantined,
            "refused": sum(b["refused"] for b in batches),
            "quarantine_rate": round(quarantined / received, 4)
            if received else None,
            "corrections": corrections})
    return rows


def _reporter_reliability_rows(store, as_of: str) -> list[dict]:
    from .field import derive_review_state  # the one fold
    from . import integrity_rules as integrity_pack

    landed = [r for r in store.list_field_report_artefacts()
              if r["as_of"] <= as_of]
    screenings = {s["report_id"]: s
                  for s in store.list_field_screenings()}
    rows: list[dict] = []
    for reporter in sorted({r["reporter"] for r in landed}):
        mine = [r for r in landed if r["reporter"] == reporter]
        outcomes = {"unreviewed": 0, "confirmed": 0,
                    "queried": 0, "rejected": 0}
        for report in mine:
            acts = [a for a in store.list_field_review_acts(
                        report["report_id"])
                    if a["as_of"] <= as_of]
            outcomes[derive_review_state(acts)] += 1
        decided = (outcomes["confirmed"] + outcomes["queried"]
                   + outcomes["rejected"])
        held = released = 0
        for report in mine:
            screening = screenings.get(report["report_id"])
            if screening is None \
                    or screening["verdict"] != integrity_pack.VERDICT_HELD:
                continue
            held += 1
            releases = [
                a for a in store.list_field_screening_acts(
                    screening["screening_id"])
                if a["act"] == integrity_pack.ACT_RELEASE
                and a["as_of"] <= as_of]
            if releases:
                released += 1
        rows.append({
            "reporter": reporter,
            "reports_landed": len(mine),
            "review_outcomes": outcomes,
            "decided": decided,
            "confirmation_rate": round(
                outcomes["confirmed"] / decided, 4)
            if decided else None,
            "rate_note": None if decided
            else pack.NO_DECIDED_NOTE,
            "screenings_held": held,
            "screenings_released": released})
    return rows


def build_monitoring_board(store, as_of: str) -> MonitoringBoard:
    """Strike (do not store) the monitoring board at a
    date: the cost ledger folded to the date, every
    registered source's freshness judged against the
    registry's window, and the reliability lines for
    sources and reporters folded from their batch
    reports, corrections, review acts and screenings.
    Every figure derives from stored artefacts alone,
    and the board writes nothing back."""
    runs = [r for r in store.list_model_runs()
            if r["at"] <= as_of]
    cost = _cost_section(runs)
    freshness = _freshness_rows(store, as_of)
    sources = _source_reliability_rows(store, as_of)
    reporters = _reporter_reliability_rows(store, as_of)
    totals = {
        "runs": cost["runs"],
        "cost_nano_usd": cost["cost_nano_usd"],
        "sources": len(freshness),
        "sources_fresh": sum(
            1 for row in freshness
            if row["state"] == pack.STATE_FRESH),
        "sources_stale": sum(
            1 for row in freshness
            if row["state"] == pack.STATE_STALE),
        "sources_never_loaded": sum(
            1 for row in freshness
            if row["state"] == pack.STATE_NEVER_LOADED),
        "reporters": len(reporters),
        "reports": sum(
            row["reports_landed"] for row in reporters),
    }
    fingerprint = _fingerprint({
        "as_of": as_of, "cost": cost, "freshness": freshness,
        "reliability_sources": sources,
        "reliability_reporters": reporters, "totals": totals,
        "inputs": {
            "runs": [r["run_id"] for r in runs],
            "batches": sorted(
                b["batch_id"] for b in store.list_ingest_batches()
                if b["load_date"] <= as_of),
            "corrections": sorted(
                c["correction_id"]
                for c in store.list_fact_corrections()
                if c["as_of"] <= as_of),
            "reports": sorted(
                [r["report_id"], r["payload_hash"]]
                for r in store.list_field_report_artefacts()
                if r["as_of"] <= as_of),
        },
        "pack": pack.RULES_VERSION,
        "ingest_pack": ingest_pack.RULES_VERSION,
    })
    return MonitoringBoard(
        board_id=f"MON-{fingerprint[:10]}",
        fingerprint=fingerprint, as_of=as_of, cost=cost,
        freshness=freshness, reliability_sources=sources,
        reliability_reporters=reporters, totals=totals,
        rules_version=pack.RULES_VERSION)


# ---------------------------------------------------------------------------
# Verification: a second route over the raw store.
# ---------------------------------------------------------------------------


def verify_monitoring(store, as_of: str) -> list[str]:
    """Re-perform the whole monitoring layer: every
    run record's sequence is gapless, its fingerprint
    re-performs from its fields, and its cost is the
    pack's price of its tokens; every monitoring
    board re-performs field for field at its own
    date, its supersedes chain stands in strike
    order, and its cost totals cross-check against
    direct sums over the ledger — the opposite walk
    from the board's own fold."""
    problems: list[str] = []
    runs = store.list_model_runs()
    for index, run in enumerate(runs):
        want_id = f"RUN-{index + 1:06d}"
        if run["run_id"] != want_id or run["seq"] != index + 1:
            problems.append(
                f"model run {run['run_id']}: the ledger "
                f"sequence is broken — position {index + 1} "
                f"carries id {run['run_id']} and seq "
                f"{run['seq']}, not {want_id}")
        if run["purpose"] not in pack.PURPOSES:
            problems.append(
                f"model run {run['run_id']}: purpose "
                f"{run['purpose']!r} is outside the pack's "
                "vocabulary")
        expected_cost = pack.cost_nano_usd(
            run["profile"], run["input_tokens"],
            run["output_tokens"])
        if run["cost_nano_usd"] != expected_cost:
            problems.append(
                f"model run {run['run_id']}: its cost "
                f"{run['cost_nano_usd']} is not the pack's "
                f"price of {run['input_tokens']} in / "
                f"{run['output_tokens']} out on profile "
                f"{run['profile']} ({expected_cost})")
        rebuilt = _fingerprint({
            "seq": run["seq"], "purpose": run["purpose"],
            "profile": run["profile"], "model": run["model"],
            "input_tokens": run["input_tokens"],
            "output_tokens": run["output_tokens"],
            "cost_nano_usd": run["cost_nano_usd"],
            "prompt_sha256": run["prompt_sha256"],
            "reply_sha256": run["reply_sha256"],
            "at": run["at"], "pack": pack.RULES_VERSION,
        })
        if rebuilt != run["fingerprint"]:
            problems.append(
                f"model run {run['run_id']}: its "
                "fingerprint does not match its fields")
    boards = store.list_monitoring_boards()
    ordered = sorted(boards, key=lambda b: (b["as_of"], b["board_id"]))
    for idx, board in enumerate(ordered):
        want = ordered[idx - 1]["board_id"] if idx else None
        if board["supersedes"] != want:
            problems.append(
                f"monitoring board {board['board_id']}: "
                f"supersedes {board['supersedes']}, but the "
                f"strike order says {want}")
        rebuilt = build_monitoring_board(store, board["as_of"])
        for field in ("board_id", "fingerprint", "cost",
                      "freshness", "reliability_sources",
                      "reliability_reporters", "totals"):
            if rebuilt.model_dump()[field] != board[field]:
                problems.append(
                    f"monitoring board {board['board_id']}: "
                    f"its {field} does not re-perform from "
                    "the record at its date")
        # The opposite walk for the money: sum the
        # ledger rows directly, never through the
        # board's own fold.
        direct = [r for r in runs if r["at"] <= board["as_of"]]
        direct_cost = sum(
            r["cost_nano_usd"] for r in direct
            if r["cost_nano_usd"] is not None)
        if direct_cost != board["cost"]["cost_nano_usd"] \
                or len(direct) != board["cost"]["runs"]:
            problems.append(
                f"monitoring board {board['board_id']}: "
                "its cost totals disagree with a direct "
                "sum over the run ledger")
    return problems
