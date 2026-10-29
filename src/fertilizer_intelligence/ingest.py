"""The production data plane (R11): connector loads,
quarantine, corrections, and season-close actuals.

Facts enter this system from real feeds through one port —
``load_batch`` — under the ingest pack:

- the batch names a **registered source**; the registry
  states the fact class the source may deliver, the
  provenance its rows carry, and its freshness rule;
- a row without ``source`` or ``as_of`` is **refused at the
  port** — recorded on the batch report, never stored,
  never quarantined (it never arrived);
- a provenanced row that is malformed or contradictory is
  **quarantined with a named reason** and its raw payload;
  no engine ever reads a quarantined row, because it never
  reaches a fact table;
- a valid row lands insert-only under its natural key. A
  replay — the same batch again, or the same rows in a
  later batch — lands nothing twice: identical content
  counts as a duplicate, different content under a taken
  key quarantines as a conflict. Nothing is ever
  overwritten;
- the batch report reconciles exactly: received is
  inserted + duplicates + quarantined + refused.

**Corrections** are new facts, not edits: a correction
carries the full corrected row and names what it corrects —
a stored fact, a quarantined record, or the previous
correction in the key's chain. The stored fact is never
rewritten; the effective row for a key is the fold of the
chain over the stored base, and the chain verifier
re-performs that fold and checks every link.

**Season-close actuals** arrive through the same port as
their own fact class. They never touch an estimate: the
actuals report joins them to struck estimates by natural
key and reports unmatched rows, never drops them.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from . import ingest_rules as pack
from . import models
from .demand import head_of

_CLASS_MODELS = {
    pack.PRICE_POINTS: models.PricePoint,
    pack.SUPPLY_FACTS: models.SupplyFact,
    pack.IMPORT_ARRIVALS: models.ImportArrival,
    pack.POLICY_EVENTS: models.PolicyEvent,
    pack.COMPETITOR_POINTS: models.CompetitorPoint,
    pack.SEASON_ACTUALS: models.SeasonActual,
}

_CLASS_INSERTS = {
    pack.PRICE_POINTS: "insert_price_points",
    pack.SUPPLY_FACTS: "insert_supply_facts",
    pack.IMPORT_ARRIVALS: "insert_import_arrivals",
    pack.POLICY_EVENTS: "insert_policy_events",
    pack.COMPETITOR_POINTS: "insert_competitor_points",
    pack.SEASON_ACTUALS: "insert_season_actuals",
}


def _fingerprint(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Artefacts
# ---------------------------------------------------------------------------


class IngestBatch(BaseModel):
    batch_id: str
    fingerprint: str
    source_id: str
    fact_class: str
    loaded_by: str
    load_date: str
    received: int
    inserted: int
    duplicates: int
    quarantined: int
    refused: int
    inserted_keys: list[str] = Field(default_factory=list)
    duplicate_keys: list[str] = Field(default_factory=list)
    inserted_rows: dict[str, Any] = Field(default_factory=dict)
    quarantine: list[dict[str, Any]] = Field(default_factory=list)
    refusals: list[dict[str, Any]] = Field(default_factory=list)
    rules_version: str


class QuarantineRecord(BaseModel):
    quarantine_id: str
    batch_id: str
    source_id: str
    fact_class: str
    reason: str
    detail: str
    natural_key: str
    row: dict[str, Any] = Field(default_factory=dict)
    as_of: str


class FactCorrection(BaseModel):
    correction_id: str
    fingerprint: str
    fact_class: str
    natural_key: str
    key: dict[str, Any] = Field(default_factory=dict)
    corrects: str | None = None
    corrects_kind: str  # stored_fact | quarantine_record | correction
    corrected_by: str
    as_of: str
    row: dict[str, Any] = Field(default_factory=dict)
    supersedes: str | None = None
    rules_version: str


# ---------------------------------------------------------------------------
# Row handling
# ---------------------------------------------------------------------------


def _content(fact_class: str, raw) -> dict:
    """The comparable content of a row: the class's model
    applied to it, dumped. Stored rows and feed rows pass
    through the same model, so the comparison is exact."""
    return _CLASS_MODELS[fact_class].model_validate(raw).model_dump()


def _stored_content(store, fact_class: str) -> dict[str, dict]:
    """Natural-key label -> content for everything the class
    already holds."""
    read = getattr(store, pack.CLASS_STORE_READ[fact_class])
    out = {}
    for row in read():
        content = _content(fact_class, row)
        label = pack.key_label(fact_class, pack.natural_key(fact_class, content))
        out[label] = content
    return out


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_row(entry: dict, fact_class: str, raw, districts: set,
                  load_date: date):
    """Grade one raw row. Returns ("refused", refusal),
    ("quarantined", reason, detail) or ("ok", content)."""
    if not isinstance(raw, dict):
        return ("quarantined", pack.REASON_MALFORMED_ROW,
                "row is not an object")
    missing_prov = [
        field for field in ("source", "as_of")
        if not isinstance(raw.get(field), str) or not raw.get(field)
    ]
    if missing_prov:
        return ("refused", {
            "reason": pack.REFUSAL_MISSING_PROVENANCE,
            "missing": missing_prov,
        })
    missing_fields = [
        field for field in pack.CLASS_FIELDS[fact_class]
        if raw.get(field) is None
        or (isinstance(raw.get(field), str) and not raw.get(field))
    ]
    if missing_fields:
        return ("quarantined", pack.REASON_MALFORMED_ROW,
                f"missing fields: {', '.join(missing_fields)}")
    if raw["source"] != entry["provenance_source"]:
        return ("quarantined", pack.REASON_SOURCE_MISMATCH,
                f"row carries source {raw['source']!r}, the feed is "
                f"registered as {entry['provenance_source']!r}")
    try:
        as_of = date.fromisoformat(raw["as_of"])
    except ValueError:
        return ("quarantined", pack.REASON_MALFORMED_ROW,
                f"as_of is not an ISO date: {raw['as_of']!r}")
    try:
        content = _content(fact_class, raw)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        return ("quarantined", pack.REASON_MALFORMED_ROW,
                f"fails the {fact_class} model: "
                f"{first.get('loc', ('?',))} {first.get('msg', '')}")
    problem = _semantic_problem(fact_class, content, districts)
    if problem is not None:
        return ("quarantined", problem[0], problem[1])
    if as_of > load_date:
        return ("quarantined", pack.REASON_FUTURE_AS_OF,
                f"as_of {raw['as_of']} is after the load date "
                f"{load_date.isoformat()}")
    age = (load_date - as_of).days
    if age > entry["freshness_days"]:
        return ("quarantined", pack.REASON_STALE_BEYOND_FRESHNESS,
                f"as_of {raw['as_of']} is {age} days before the load "
                f"date, beyond the feed's {entry['freshness_days']}-day "
                f"freshness rule")
    return ("ok", content)


def _semantic_problem(fact_class: str, content: dict, districts: set):
    """Vocabulary and sign checks, on validated content.
    Returns (reason, detail) or None."""
    if fact_class == pack.PRICE_POINTS:
        if content["series_kind"] not in pack.SERIES_KINDS:
            return (pack.REASON_UNKNOWN_KIND,
                    f"series_kind {content['series_kind']!r} is not tracked")
        if content["item"] not in pack.PRICE_ITEMS:
            return (pack.REASON_UNKNOWN_PRODUCT,
                    f"item {content['item']!r} is not a tracked product "
                    f"or feedstock")
        if content["price"] <= 0:
            return (pack.REASON_NON_POSITIVE_PRICE,
                    f"price {content['price']} is not positive")
    elif fact_class == pack.SUPPLY_FACTS:
        if content["product"] not in pack.KNOWN_PRODUCTS:
            return (pack.REASON_UNKNOWN_PRODUCT,
                    f"product {content['product']!r} is not tracked")
        for field in ("planned_tonnes", "actual_tonnes"):
            if content[field] < 0:
                return (pack.REASON_NEGATIVE_QUANTITY,
                        f"{field} {content[field]} is negative")
    elif fact_class == pack.IMPORT_ARRIVALS:
        if content["product"] not in pack.KNOWN_PRODUCTS:
            return (pack.REASON_UNKNOWN_PRODUCT,
                    f"product {content['product']!r} is not tracked")
        if content["quantity_tonnes"] < 0:
            return (pack.REASON_NEGATIVE_QUANTITY,
                    f"quantity_tonnes {content['quantity_tonnes']} "
                    f"is negative")
    elif fact_class == pack.POLICY_EVENTS:
        if content["kind"] not in pack.POLICY_KINDS:
            return (pack.REASON_UNKNOWN_KIND,
                    f"kind {content['kind']!r} is not a tracked "
                    f"policy kind")
        for product in content["impacted_products"]:
            if product not in pack.KNOWN_PRODUCTS:
                return (pack.REASON_UNKNOWN_PRODUCT,
                        f"impacted product {product!r} is not tracked")
    elif fact_class == pack.COMPETITOR_POINTS:
        if content["product"] not in pack.KNOWN_PRODUCTS:
            return (pack.REASON_UNKNOWN_PRODUCT,
                    f"product {content['product']!r} is not tracked")
        if content["volume_tonnes"] < 0:
            return (pack.REASON_NEGATIVE_QUANTITY,
                    f"volume_tonnes {content['volume_tonnes']} "
                    f"is negative")
        if content["price"] <= 0:
            return (pack.REASON_NON_POSITIVE_PRICE,
                    f"price {content['price']} is not positive")
    elif fact_class == pack.SEASON_ACTUALS:
        if content["district_id"] not in districts:
            return (pack.REASON_UNKNOWN_DISTRICT,
                    f"district {content['district_id']!r} does not exist")
        if content["product"] not in pack.KNOWN_PRODUCTS:
            return (pack.REASON_UNKNOWN_PRODUCT,
                    f"product {content['product']!r} is not tracked")
        if content["actual_kind"] not in pack.ACTUAL_KINDS:
            return (pack.REASON_UNKNOWN_KIND,
                    f"actual_kind {content['actual_kind']!r} is not a "
                    f"tracked actual kind")
        if content["quantity_tonnes"] < 0:
            return (pack.REASON_NEGATIVE_QUANTITY,
                    f"quantity_tonnes {content['quantity_tonnes']} "
                    f"is negative")
    return None


# ---------------------------------------------------------------------------
# The connector port
# ---------------------------------------------------------------------------


def load_batch(store, source_id: str, rows: list, loaded_by: str,
               load_date: str) -> dict:
    """Land one connector batch from a registered source.

    Compute-or-return on the batch fingerprint: replaying
    the same batch (same source, loader, load date and rows)
    returns the stored report and lands nothing. Rows are
    graded in order against the stored facts plus the rows
    accepted earlier in this same batch, so a batch also
    cannot land its own rows twice."""
    entry = pack.source_entry(source_id)
    if entry is None:
        raise ValueError(f"unregistered ingest source: {source_id}")
    fact_class = entry["fact_class"]
    try:
        load_day = date.fromisoformat(load_date)
    except ValueError:
        raise ValueError(f"load_date is not an ISO date: {load_date!r}")
    fingerprint = _fingerprint({
        "source_id": source_id, "fact_class": fact_class,
        "loaded_by": loaded_by, "load_date": load_date, "rows": rows,
    })
    existing = store.ingest_batch_by_fingerprint(fingerprint)
    if existing is not None:
        return existing
    batch_id = f"ING-{fingerprint[:10]}"
    districts = {d["district_id"] for d in store.list_districts()}
    pending = _stored_content(store, fact_class)

    accepted: list[dict] = []
    inserted_keys: list[str] = []
    inserted_rows: dict[str, Any] = {}
    duplicate_keys: list[str] = []
    quarantine: list[dict] = []
    refusals: list[dict] = []

    for index, raw in enumerate(rows):
        verdict = _validate_row(entry, fact_class, raw, districts, load_day)
        if verdict[0] == "refused":
            refusals.append({"row_index": index, **verdict[1]})
            continue
        if verdict[0] == "quarantined":
            _, reason, detail = verdict
            key = pack.natural_key(fact_class, raw) if isinstance(raw, dict) else {}
            quarantine.append({
                "quarantine_id": f"QRN-{fingerprint[:10]}-{index:03d}",
                "reason": reason, "detail": detail,
                "natural_key": pack.key_label(fact_class, key),
                "row": raw,
            })
            continue
        content = verdict[1]
        key = pack.natural_key(fact_class, content)
        label = pack.key_label(fact_class, key)
        if label in pending:
            if pending[label] == content:
                duplicate_keys.append(label)
            else:
                quarantine.append({
                    "quarantine_id": f"QRN-{fingerprint[:10]}-{index:03d}",
                    "reason": pack.REASON_CONFLICTS_WITH_STORED,
                    "detail": f"a different row is already stored under "
                              f"{label} and facts are never overwritten",
                    "natural_key": label,
                    "row": raw,
                })
            continue
        pending[label] = content
        accepted.append(content)
        inserted_keys.append(label)
        inserted_rows[label] = content

    if accepted:
        model = _CLASS_MODELS[fact_class]
        insert = getattr(store, _CLASS_INSERTS[fact_class])
        insert([model.model_validate(content) for content in accepted])

    batch = IngestBatch(
        batch_id=batch_id, fingerprint=fingerprint,
        source_id=source_id, fact_class=fact_class,
        loaded_by=loaded_by, load_date=load_date,
        received=len(rows), inserted=len(accepted),
        duplicates=len(duplicate_keys), quarantined=len(quarantine),
        refused=len(refusals),
        inserted_keys=inserted_keys, duplicate_keys=duplicate_keys,
        inserted_rows=inserted_rows, quarantine=quarantine,
        refusals=refusals, rules_version=pack.RULES_VERSION,
    )
    store.insert_ingest_batch(batch.model_dump())
    for held in quarantine:
        store.insert_quarantine_record(QuarantineRecord(
            quarantine_id=held["quarantine_id"], batch_id=batch_id,
            source_id=source_id, fact_class=fact_class,
            reason=held["reason"], detail=held["detail"],
            natural_key=held["natural_key"], row=held["row"],
            as_of=load_date,
        ).model_dump())
    return store.get_ingest_batch(batch_id)


def verify_batch(store, batch_id: str) -> dict:
    """Re-perform a stored batch report against the store:
    the counts reconcile, the quarantine records on file
    are the ones the report names, and every inserted row
    is still stored with the content the report recorded."""
    batch = store.get_ingest_batch(batch_id)
    if batch is None:
        raise ValueError(f"no such ingest batch: {batch_id}")
    problems: list[str] = []
    total = (batch["inserted"] + batch["duplicates"]
             + batch["quarantined"] + batch["refused"])
    if total != batch["received"]:
        problems.append(
            f"counts do not reconcile: received {batch['received']} vs "
            f"inserted + duplicates + quarantined + refused = {total}")
    if batch["inserted"] != len(batch["inserted_keys"]):
        problems.append("inserted count disagrees with inserted_keys")
    if batch["duplicates"] != len(batch["duplicate_keys"]):
        problems.append("duplicate count disagrees with duplicate_keys")
    if batch["refused"] != len(batch["refusals"]):
        problems.append("refused count disagrees with refusals")
    records = store.list_quarantine_records(batch_id=batch_id)
    if len(records) != batch["quarantined"]:
        problems.append(
            f"quarantine records on file: {len(records)}, report "
            f"says {batch['quarantined']}")
    named = {held["quarantine_id"] for held in batch["quarantine"]}
    on_file = {record["quarantine_id"] for record in records}
    if named != on_file:
        problems.append("quarantine records on file differ from the "
                        "report's named records")
    for record in records:
        match = next((h for h in batch["quarantine"]
                      if h["quarantine_id"] == record["quarantine_id"]), None)
        if match is None:
            continue
        if record["reason"] != match["reason"] or record["row"] != match["row"]:
            problems.append(
                f"quarantine record {record['quarantine_id']} differs "
                f"from the batch report")
    stored = _stored_content(store, batch["fact_class"])
    for label, content in batch["inserted_rows"].items():
        if stored.get(label) != content:
            problems.append(
                f"inserted row {label} is no longer stored as loaded")
    return {
        "batch_id": batch_id, "verified": not problems,
        "problems": problems,
        "received": batch["received"], "inserted": batch["inserted"],
        "duplicates": batch["duplicates"],
        "quarantined": batch["quarantined"], "refused": batch["refused"],
    }


# ---------------------------------------------------------------------------
# Corrections: new facts, linked, chained, re-performed
# ---------------------------------------------------------------------------


def _chain_for(store, fact_class: str, label: str):
    """The key's corrections ordered along their supersedes
    links, plus any structural problems found on the way."""
    rows = store.list_fact_corrections(fact_class=fact_class,
                                       natural_key=label)
    problems: list[str] = []
    if not rows:
        return [], problems
    by_id = {row["correction_id"]: row for row in rows}
    roots = [row for row in rows if not row.get("supersedes")]
    if len(roots) > 1:
        problems.append(
            f"correction chain for {label} has {len(roots)} roots")
    children: dict[str, list[dict]] = {}
    for row in rows:
        parent = row.get("supersedes")
        if parent is None:
            continue
        if parent not in by_id:
            problems.append(
                f"correction {row['correction_id']} supersedes "
                f"{parent}, which is not in this chain")
        children.setdefault(parent, []).append(row)
    for parent, kids in children.items():
        if len(kids) > 1:
            problems.append(
                f"correction chain for {label} forks at {parent}")
    ordered: list[dict] = []
    seen: set[str] = set()
    current = roots[0] if roots else None
    while current is not None:
        if current["correction_id"] in seen:
            problems.append(
                f"correction chain for {label} cycles at "
                f"{current['correction_id']}")
            break
        seen.add(current["correction_id"])
        ordered.append(current)
        kids = children.get(current["correction_id"], [])
        current = kids[0] if kids else None
    if len(ordered) != len(rows) and not problems:
        problems.append(
            f"correction chain for {label} does not reach every "
            f"correction on file")
    return ordered, problems


def submit_correction(store, fact_class: str, row: dict,
                      corrects: str | None, corrected_by: str) -> dict:
    """Record a correction: a new fact carrying the full
    corrected row, linked to what it corrects. The stored
    fact is never rewritten — the correction joins the
    key's chain and the effective row moves.

    ``corrects`` names the chain head it extends, a
    quarantine record it resolves, or is None when it
    corrects the stored fact directly and no chain exists
    yet. Resubmitting an identical correction returns the
    one on record."""
    if fact_class not in pack.FACT_CLASSES:
        raise ValueError(f"unknown fact class: {fact_class}")
    if not isinstance(row, dict):
        raise ValueError("a correction row must be an object")
    missing_prov = [
        field for field in ("source", "as_of")
        if not isinstance(row.get(field), str) or not row.get(field)
    ]
    if missing_prov:
        raise ValueError(
            "a correction row is refused without provenance: "
            f"missing {', '.join(missing_prov)}")
    try:
        content = _content(fact_class, row)
    except ValidationError as exc:
        raise ValueError(
            f"correction row fails the {fact_class} model: {exc}"
        ) from exc
    key = pack.natural_key(fact_class, content)
    label = pack.key_label(fact_class, key)
    # An identical resubmission — same row, same named
    # target, same corrector — returns the record on file,
    # wherever the chain has since moved to.
    for existing in store.list_fact_corrections(
            fact_class=fact_class, natural_key=label):
        if existing["row"] == content \
                and existing["corrects"] == corrects \
                and existing["corrected_by"] == corrected_by:
            return existing
    stored = _stored_content(store, fact_class)
    chain, _ = _chain_for(store, fact_class, label)
    head = chain[-1] if chain else None

    corrects_kind: str
    if corrects is None:
        if head is not None:
            raise ValueError(
                f"a correction chain exists for {label} — name its "
                f"head {head['correction_id']} as what this corrects")
        if label not in stored:
            raise ValueError(
                f"nothing is stored under {label} and no quarantine "
                f"record was named — there is nothing to correct")
        corrects_kind = "stored_fact"
    elif corrects.startswith("QRN-"):
        record = store.get_quarantine_record(corrects)
        if record is None:
            raise ValueError(f"no such quarantine record: {corrects}")
        if record["fact_class"] != fact_class:
            raise ValueError(
                f"quarantine record {corrects} holds a "
                f"{record['fact_class']} row, not {fact_class}")
        corrects_kind = "quarantine_record"
    elif corrects.startswith("COR-"):
        target = store.get_fact_correction(corrects)
        if target is None:
            raise ValueError(f"no such correction: {corrects}")
        if target["fact_class"] != fact_class or \
                target["natural_key"] != label:
            raise ValueError(
                f"correction {corrects} belongs to a different key "
                f"({target['fact_class']}/{target['natural_key']})")
        if head is None or corrects != head["correction_id"]:
            raise ValueError(
                f"correction {corrects} is not the head of the "
                f"chain for {label} — corrections extend the head, "
                f"never a buried link")
        corrects_kind = "correction"
    else:
        raise ValueError(f"unresolvable corrects reference: {corrects}")

    supersedes = head["correction_id"] if head is not None else None
    fingerprint = _fingerprint({
        "fact_class": fact_class, "natural_key": label, "row": content,
        "corrects": corrects, "corrects_kind": corrects_kind,
        "corrected_by": corrected_by, "supersedes": supersedes,
    })
    existing = store.correction_by_fingerprint(fingerprint)
    if existing is not None:
        return existing
    correction = FactCorrection(
        correction_id=f"COR-{fingerprint[:10]}",
        fingerprint=fingerprint, fact_class=fact_class,
        natural_key=label, key=key, corrects=corrects,
        corrects_kind=corrects_kind, corrected_by=corrected_by,
        as_of=content["as_of"], row=content, supersedes=supersedes,
        rules_version=pack.RULES_VERSION,
    )
    store.insert_fact_correction(correction.model_dump())
    return store.get_fact_correction(correction.correction_id)


def effective_row(store, fact_class: str, key: dict) -> dict | None:
    """The row the key currently stands at: the stored fact
    folded through its correction chain, in chain order.
    None when the key holds nothing and no correction
    chain stands on a quarantined base."""
    label = pack.key_label(fact_class, key)
    stored = _stored_content(store, fact_class)
    current = stored.get(label)
    chain, problems = _chain_for(store, fact_class, label)
    if problems:
        raise ValueError(
            f"correction chain for {label} is broken: "
            + "; ".join(problems))
    for correction in chain:
        current = correction["row"]
    return current


def verify_correction_chain(store, fact_class: str, key: dict) -> dict:
    """Re-perform a key's correction chain: every link's
    fingerprint recomputes, the chain is one unbroken line
    from its base, each correction names the link or base
    it actually extends, and folding the chain from the
    base lands exactly on the chain head's row."""
    label = pack.key_label(fact_class, key)
    problems: list[str] = []
    chain, structural = _chain_for(store, fact_class, label)
    problems.extend(structural)
    stored = _stored_content(store, fact_class)
    base = stored.get(label)

    for correction in chain:
        recomputed = _fingerprint({
            "fact_class": correction["fact_class"],
            "natural_key": correction["natural_key"],
            "row": correction["row"],
            "corrects": correction["corrects"],
            "corrects_kind": correction["corrects_kind"],
            "corrected_by": correction["corrected_by"],
            "supersedes": correction["supersedes"],
        })
        if recomputed != correction["fingerprint"]:
            problems.append(
                f"correction {correction['correction_id']} fingerprint "
                f"mismatch — its record no longer matches its content")

    previous_id: str | None = None
    for index, correction in enumerate(chain):
        if index == 0:
            if correction["corrects_kind"] == "stored_fact":
                if base is None:
                    problems.append(
                        f"correction {correction['correction_id']} "
                        f"claims to correct a stored fact at {label}, "
                        f"but none is stored")
                if correction["corrects"] is not None:
                    problems.append(
                        f"correction {correction['correction_id']} is "
                        f"typed stored_fact but names "
                        f"{correction['corrects']}")
            elif correction["corrects_kind"] == "quarantine_record":
                record = store.get_quarantine_record(
                    correction["corrects"] or "")
                if record is None:
                    problems.append(
                        f"correction {correction['correction_id']} "
                        f"names quarantine record "
                        f"{correction['corrects']}, which is not on file")
            else:
                problems.append(
                    f"chain for {label} opens with a correction that "
                    f"corrects another correction — the base link is "
                    f"missing")
        else:
            if correction["corrects"] != previous_id and \
                    correction["corrects_kind"] != "quarantine_record":
                problems.append(
                    f"correction {correction['correction_id']} names "
                    f"{correction['corrects']} as what it corrects, "
                    f"but the chain reaches it from {previous_id}")
        previous_id = correction["correction_id"]

    effective = base
    for correction in chain:
        effective = correction["row"]
    if chain and effective != chain[-1]["row"]:
        problems.append("the re-performed fold does not land on the "
                        "chain head's row")
    return {
        "fact_class": fact_class, "natural_key": label,
        "verified": not problems, "problems": problems,
        "chain": [c["correction_id"] for c in chain],
        "base_present": base is not None,
        "effective": effective,
    }


# ---------------------------------------------------------------------------
# Season-close actuals: the report that joins, never drops
# ---------------------------------------------------------------------------


def actuals_report(store, crop_year: str, season: str) -> dict:
    """Every actual imported for a season, joined to the
    head demand estimate at its natural key. An actual with
    no struck estimate is reported as unmatched — it is on
    record and named here, never dropped."""
    actuals = store.season_actuals(crop_year=crop_year, season=season)
    estimates = store.list_estimates(crop_year=crop_year, season=season)
    groups: dict[tuple, list[dict]] = {}
    for estimate in estimates:
        groups.setdefault(
            (estimate["district_id"], estimate["product"]), []
        ).append(estimate)
    heads = {}
    for natural, rows in groups.items():
        head = head_of(rows, "estimate_id")
        if head is not None:
            heads[natural] = head["estimate_id"]
    report_rows = []
    unmatched = []
    for actual in actuals:
        estimate_id = heads.get((actual["district_id"], actual["product"]))
        row = dict(actual)
        row["matched_estimate"] = estimate_id is not None
        row["estimate_id"] = estimate_id
        report_rows.append(row)
        if estimate_id is None:
            unmatched.append(pack.key_label(pack.SEASON_ACTUALS, {
                "district_id": actual["district_id"],
                "crop_year": actual["crop_year"],
                "season": actual["season"],
                "product": actual["product"],
                "actual_kind": actual["actual_kind"],
            }))
    return {
        "crop_year": crop_year, "season": season,
        "actual_count": len(report_rows),
        "matched_count": len(report_rows) - len(unmatched),
        "unmatched_count": len(unmatched),
        "unmatched": unmatched,
        "rows": report_rows,
    }
