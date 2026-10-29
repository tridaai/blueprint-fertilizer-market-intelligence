"""Regional rollups (R14, roadmap F21-DR3).

A regional rollup takes the head season outlook's own
member estimates — the artefacts the R2 outlook sums for
its product rollups — and groups them by their district's
region: district lines, region subtotals, a national
total per product and a grand total. It is a sum of named
members and nothing else:

- the members are exactly the outlook's ``estimate_ids``,
  bound by id on the rollup's face;
- a member struck partial names its district as partial,
  in its region and product; a tracked district the
  outlook does not name is named as missing and
  contributes nothing — the rollup never prints a silent
  zero for a district it has no artefact for;
- the season's head supply gap per product rides on the
  rollup by reference — its own figures, its own id —
  because a gap is struck for the whole tracked market
  and there are no district gap figures to sum. Where
  the gap was struck from this rollup's outlook, the
  verifier grades the cross-check that its demand figure
  equals the rollup's national total for the product.

The rollup is insert-only and content-addressed: struck
over a moved outlook it supersedes the old head by link,
and :func:`verify_rollup` re-performs it by a second
route — grouping the store's estimate rows directly —
so a figure that drifted from its members is named.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

from . import rollup_rules as pack
from .demand import TONNE_TOL, head_of
from .generator import PRODUCTS


class RollupRefused(RuntimeError):
    """A rollup candidate failed re-performance and was
    refused wholesale — nothing of it is stored but the
    refusal artefact that names the problems."""

    def __init__(self, problems: list[str], refusal_id: str | None = None):
        self.problems = problems
        self.refusal_id = refusal_id
        super().__init__("rollup refused: " + "; ".join(problems))


class RegionalRollup(BaseModel):
    rollup_id: str
    fingerprint: str
    crop_year: str
    season: str
    as_of: str
    built_by: str
    rules_version: str
    outlook_id: str
    outlook_as_of: str
    products: list[dict]
    national_total_tonnes: float
    status: str  # complete / partial
    partial_districts: list[str]
    missing_districts: list[str]
    supersedes: str | None = None


class RollupRefusal(BaseModel):
    refusal_id: str
    fingerprint: str
    crop_year: str
    season: str
    as_of: str
    built_by: str
    rules_version: str
    problems: list[str]


def _fingerprint(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Composition (the builder's route: off the outlook's member ids)
# ---------------------------------------------------------------------------


def _gap_line(store, product: str, crop_year: str, season: str,
              outlook_id: str) -> dict | None:
    """The product's head gap, carried by reference: its
    own figures under its own id, with the demand basis
    stated — whether it was struck from this outlook."""
    gap = head_of(store.list_gaps(product, crop_year, season), "gap_id")
    if gap is None:
        return None
    return {
        "gap_id": gap["gap_id"],
        "band": gap["band"],
        "gap_tonnes": gap["gap_tonnes"],
        "gap_pct_of_demand": gap["gap_pct_of_demand"],
        "programme_cover_pct": gap["programme_cover_pct"],
        "slipped_tonnes": gap["slipped_tonnes"],
        "demand_tonnes": gap["demand_tonnes"],
        "demand_outlook_id": gap["demand_outlook_id"],
        "demand_basis": (
            pack.GAP_BASIS_THIS_OUTLOOK
            if gap["demand_outlook_id"] == outlook_id
            else pack.GAP_BASIS_EARLIER_OUTLOOK),
        "as_of": gap["as_of"],
    }


def _product_block(product: str, members: list[dict],
                   districts: dict[str, dict],
                   gap_line: dict | None) -> dict:
    """One product's block: its member lines grouped into
    region subtotals, the national total, and the naming
    of every partial and missing district."""
    by_region: dict[str, list[dict]] = {
        region: [] for region in pack.REGION_ORDER}
    for member in members:
        by_region[member["region"]].append(member)
    present = {m["district_id"] for m in members}
    regions = []
    partial_names: list[str] = []
    missing_names: list[str] = []
    for region in pack.REGION_ORDER:
        rows = sorted(by_region[region],
                      key=lambda m: m["district_id"])
        region_missing = sorted(
            (d for d in districts.values()
             if d["region"] == region
             and d["district_id"] not in present),
            key=lambda d: d["district_id"])
        region_partial = [m["district_name"] for m in rows
                          if m["status"] == "partial"]
        regions.append({
            "region": region,
            "total_tonnes": round(
                sum(m["total_tonnes"] for m in rows), 3),
            "estimate_count": len(rows),
            "partial_count": len(region_partial),
            "partial_districts": region_partial,
            "missing_districts": [d["name"] for d in region_missing],
            "status": (
                pack.STATUS_PARTIAL
                if region_partial or region_missing
                else pack.STATUS_COMPLETE),
        })
        partial_names.extend(region_partial)
        missing_names.extend(d["name"] for d in region_missing)
    return {
        "product": product,
        "members": members,
        "regions": regions,
        "national_tonnes": round(
            sum(r["total_tonnes"] for r in regions), 3),
        "estimate_count": len(members),
        "partial_count": sum(
            1 for m in members if m["status"] == "partial"),
        "partial_districts": partial_names,
        "missing_districts": missing_names,
        "status": (
            pack.STATUS_PARTIAL if partial_names or missing_names
            else pack.STATUS_COMPLETE),
        "gap": gap_line,
    }


def build_rollup(store, crop_year: str, season: str, as_of: str,
                 built_by: str) -> RegionalRollup:
    """Build (do not store) the candidate rollup for one
    season, off the head outlook's member ids."""
    outlook = head_of(store.list_outlooks(crop_year, season), "outlook_id")
    if outlook is None:
        raise ValueError(
            f"no season outlook for {crop_year} {season} — a "
            "rollup sums an outlook's members, and there is "
            "no outlook to name")
    districts = {d["district_id"]: d for d in store.list_districts()}
    members_by_product: dict[str, list[dict]] = {
        product: [] for product in PRODUCTS}
    for estimate_id in outlook["estimate_ids"]:
        estimate = store.get_estimate(estimate_id)
        if estimate is None:
            raise ValueError(
                f"outlook member {estimate_id} is not in the store")
        district = districts[estimate["district_id"]]
        members_by_product[estimate["product"]].append({
            "district_id": estimate["district_id"],
            "district_name": district["name"],
            "region": district["region"],
            "estimate_id": estimate["estimate_id"],
            "status": estimate["status"],
            "total_tonnes": estimate["total_tonnes"],
            "as_of": estimate["as_of"],
        })
    region_rank = {region: i for i, region in enumerate(pack.REGION_ORDER)}
    blocks = []
    for product in PRODUCTS:
        members = sorted(
            members_by_product[product],
            key=lambda m: (region_rank[m["region"]], m["district_id"]))
        blocks.append(_product_block(
            product, members, districts,
            _gap_line(store, product, crop_year, season,
                      outlook["outlook_id"])))
    partial = sorted({name for block in blocks
                      for name in block["partial_districts"]})
    missing = sorted({name for block in blocks
                      for name in block["missing_districts"]})
    fingerprint = _fingerprint({
        "scope": [crop_year, season], "pack": pack.RULES_VERSION,
        "outlook": outlook["outlook_id"], "products": blocks,
    })
    return RegionalRollup(
        rollup_id=f"ROL-{crop_year}-{season}-{fingerprint[:10]}",
        fingerprint=fingerprint,
        crop_year=crop_year, season=season, as_of=as_of,
        built_by=built_by, rules_version=pack.RULES_VERSION,
        outlook_id=outlook["outlook_id"],
        outlook_as_of=outlook["as_of"],
        products=blocks,
        national_total_tonnes=round(
            sum(b["national_tonnes"] for b in blocks), 3),
        status=(pack.STATUS_PARTIAL if partial or missing
                else pack.STATUS_COMPLETE),
        partial_districts=partial, missing_districts=missing,
    )


def build_refusal(crop_year: str, season: str, as_of: str,
                  built_by: str, problems: list[str]) -> RollupRefusal:
    fingerprint = _fingerprint({
        "scope": [crop_year, season], "as_of": as_of,
        "built_by": built_by, "problems": problems,
        "pack": pack.RULES_VERSION,
    })
    return RollupRefusal(
        refusal_id=f"RLX-{fingerprint[:10]}", fingerprint=fingerprint,
        crop_year=crop_year, season=season, as_of=as_of,
        built_by=built_by, rules_version=pack.RULES_VERSION,
        problems=problems,
    )


# ---------------------------------------------------------------------------
# Re-performance: the verifier's second route
# ---------------------------------------------------------------------------


def _expected_blocks(store, outlook: dict,
                     districts: dict[str, dict]) -> list[dict]:
    """Rebuild the expected product blocks by grouping the
    store's estimate rows directly — filtered to the
    outlook's named members, summed from the rows — never
    through the builder's per-member lookups, so a defect
    in one route cannot hide in the other."""
    wanted = set(outlook["estimate_ids"])
    grouped: dict[str, dict[str, dict]] = {
        product: {} for product in PRODUCTS}
    for row in store.list_estimates(crop_year=outlook["crop_year"],
                                    season=outlook["season"]):
        if row["estimate_id"] in wanted:
            grouped[row["product"]][row["district_id"]] = row
    blocks = []
    for product in PRODUCTS:
        members = []
        for district_id, row in grouped[product].items():
            district = districts[district_id]
            members.append({
                "district_id": district_id,
                "district_name": district["name"],
                "region": district["region"],
                "estimate_id": row["estimate_id"],
                "status": row["status"],
                "total_tonnes": row["total_tonnes"],
                "as_of": row["as_of"],
            })
        region_rank = {r: i for i, r in enumerate(pack.REGION_ORDER)}
        members.sort(key=lambda m: (region_rank[m["region"]],
                                    m["district_id"]))
        gap = head_of(store.list_gaps(product, outlook["crop_year"],
                                      outlook["season"]), "gap_id")
        gap_line = None
        if gap is not None:
            gap_line = {
                "gap_id": gap["gap_id"], "band": gap["band"],
                "gap_tonnes": gap["gap_tonnes"],
                "gap_pct_of_demand": gap["gap_pct_of_demand"],
                "programme_cover_pct": gap["programme_cover_pct"],
                "slipped_tonnes": gap["slipped_tonnes"],
                "demand_tonnes": gap["demand_tonnes"],
                "demand_outlook_id": gap["demand_outlook_id"],
                "demand_basis": (
                    pack.GAP_BASIS_THIS_OUTLOOK
                    if gap["demand_outlook_id"] == outlook["outlook_id"]
                    else pack.GAP_BASIS_EARLIER_OUTLOOK),
                "as_of": gap["as_of"],
            }
        blocks.append(_product_block(product, members, districts,
                                     gap_line))
    return blocks


def _tonnes_close(a: float, b: float) -> bool:
    return abs(a - b) <= TONNE_TOL


def verify_rollup(store, rollup: dict) -> list[str]:
    """Re-perform a stored rollup: its members are exactly
    the outlook's named members, every region and national
    figure is the sum of those members to the tonne by
    both routes, partial and missing districts are named
    exactly, each gap line is the head gap's own figures,
    and the rollup's identity matches its content."""
    problems: list[str] = []
    if rollup["rules_version"] != pack.RULES_VERSION:
        return [f"rollup names unknown rollup pack "
                f"{rollup['rules_version']}"]
    outlook = store.get_outlook(rollup["outlook_id"])
    if outlook is None:
        return [f"rollup's outlook {rollup['outlook_id']} is not "
                "in the store"]
    if outlook["crop_year"] != rollup["crop_year"] \
            or outlook["season"] != rollup["season"]:
        problems.append("the rollup's outlook is for another season")
    districts = {d["district_id"]: d for d in store.list_districts()}
    expected = _expected_blocks(store, outlook, districts)
    stated = {b["product"]: b for b in rollup["products"]}
    if set(stated) != set(PRODUCTS):
        problems.append("the rollup's products are not the tracked "
                        "products")
    for want in expected:
        got = stated.get(want["product"])
        if got is None:
            continue
        label = want["product"]
        if got["members"] != want["members"]:
            problems.append(
                f"{label}: member lines differ from the outlook's "
                "members as stored")
        for want_region in want["regions"]:
            got_region = next(
                (r for r in got["regions"]
                 if r["region"] == want_region["region"]), None)
            if got_region is None:
                problems.append(
                    f"{label}: region {want_region['region']} is "
                    "missing from the rollup")
                continue
            if not _tonnes_close(got_region["total_tonnes"],
                                 want_region["total_tonnes"]):
                problems.append(
                    f"{label} {want_region['region']}: rolled "
                    f"{got_region['total_tonnes']} != sum of members "
                    f"{want_region['total_tonnes']}")
            for key in ("estimate_count", "partial_count",
                        "partial_districts", "missing_districts",
                        "status"):
                if got_region[key] != want_region[key]:
                    problems.append(
                        f"{label} {want_region['region']}: {key} "
                        f"{got_region[key]} != re-performed "
                        f"{want_region[key]}")
        if not _tonnes_close(got["national_tonnes"],
                             want["national_tonnes"]):
            problems.append(
                f"{label}: national {got['national_tonnes']} != "
                f"sum of members {want['national_tonnes']}")
        member_sum = round(
            sum(m["total_tonnes"] for m in want["members"]), 3)
        if not _tonnes_close(got["national_tonnes"], member_sum):
            problems.append(
                f"{label}: national {got['national_tonnes']} != "
                f"direct member sum {member_sum}")
        region_sum = round(
            sum(r["total_tonnes"] for r in got["regions"]), 3)
        if not _tonnes_close(got["national_tonnes"], region_sum):
            problems.append(
                f"{label}: national {got['national_tonnes']} != "
                f"sum of its region totals {region_sum}")
        for key in ("estimate_count", "partial_count",
                    "partial_districts", "missing_districts", "status"):
            if got[key] != want[key]:
                problems.append(
                    f"{label}: {key} {got[key]} != re-performed "
                    f"{want[key]}")
        if got["gap"] != want["gap"]:
            problems.append(
                f"{label}: the gap line is not the head gap's own "
                "figures")
        elif got["gap"] is not None \
                and got["gap"]["demand_basis"] == \
                pack.GAP_BASIS_THIS_OUTLOOK \
                and not _tonnes_close(got["gap"]["demand_tonnes"],
                                      got["national_tonnes"]):
            problems.append(
                f"{label}: gap demand {got['gap']['demand_tonnes']} "
                f"!= rollup national total "
                f"{got['national_tonnes']} though the gap was "
                "struck from this outlook")
    grand = round(sum(b["national_tonnes"] for b in expected), 3)
    if not _tonnes_close(rollup["national_total_tonnes"], grand):
        problems.append(
            f"grand total {rollup['national_total_tonnes']} != "
            f"sum of product nationals {grand}")
    partial = sorted({n for b in expected
                      for n in b["partial_districts"]})
    missing = sorted({n for b in expected
                      for n in b["missing_districts"]})
    if rollup["partial_districts"] != partial:
        problems.append("the rollup's partial districts are not "
                        "the members' partial districts")
    if rollup["missing_districts"] != missing:
        problems.append("the rollup's missing districts are not "
                        "the districts the outlook leaves unnamed")
    expected_status = (pack.STATUS_PARTIAL if partial or missing
                       else pack.STATUS_COMPLETE)
    if rollup["status"] != expected_status:
        problems.append(
            f"rollup status {rollup['status']} != {expected_status}")
    fingerprint = _fingerprint({
        "scope": [rollup["crop_year"], rollup["season"]],
        "pack": rollup["rules_version"],
        "outlook": rollup["outlook_id"],
        "products": rollup["products"],
    })
    if fingerprint != rollup["fingerprint"] \
            or rollup["rollup_id"] != (
                f"ROL-{rollup['crop_year']}-{rollup['season']}-"
                f"{fingerprint[:10]}"):
        problems.append("the rollup's id does not match its content")
    return problems
