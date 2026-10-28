"""Competitor & market-share intelligence (R6): observations,
shares and share movements.

Three artefacts, all insert-only and superseding by link like
the rest of the store:

- A **competitor observation** promotes one tracked competitor
  point (region x product x month, R1 facts) to a first-class
  artefact under the share rule pack (:mod:`.share_rules`).
  Provenance — the source label and the observation date — is
  part of the artefact, not metadata on the side: an
  observation without source or date is refused at build time
  and cannot be stored. The observation names the districts it
  covers (its region's districts) and the season its month is
  attributed to under the pack's unique-attribution rule.

- A **market share** states, per district x product x season
  and read date, Kaveri's volume against each tracked
  competitor's, computed in code from the stored observations,
  the district's R2 demand estimate and its recorded
  consumption — never from prose. Competitor volumes are
  whole-region figures, so the district's recorded market is
  distributed across sellers by the region's observed
  structure (the pack states why, and the construction);
  Kaveri's volume is the residual of the recorded
  consumption after the tracked competitors, named as a
  residual on the artefact. Every reading carries both of the
  pack's denominators, labelled: share of the observed market
  and share of total demand. The headline reading is computed
  over the fresh window only — months whose observations are
  stale at the read date are excluded and the exclusion is
  named on the artefact — and the full-season reading rides
  alongside, labelled as including stale figures. A
  district-season whose every month is excluded reads
  `not_current`; one with no competitor observation at all
  reads `no_observations`. Both are named states, never a
  silent old or empty number.

- A **share movement** compares the two crop years'
  full-season readings for one district x product x season,
  names the biggest mover, and carries that seller's
  observation provenance from both years — so a movement
  figure can be followed back to the tracked points it came
  from.

The month arithmetic follows the supply pack's spread rule
(a season total spread evenly over its six application
months, the final month carrying the rounding residual), so a
season's monthly market and demand figures sum back to their
season totals exactly.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from pydantic import BaseModel

from . import demand_rules
from . import share_rules as pack
from .generator import CROP_YEARS, SEASONS
from .supply import head_of

__all__ = [
    "CompetitorObservation",
    "MarketShare",
    "ShareMovement",
    "season_of_month",
    "month_end",
    "observation_from_point",
    "verify_observation",
    "compute_share",
    "verify_share",
    "compute_movement",
    "verify_movement",
    "season_close",
]


# -- calendar -------------------------------------------------------------------


def month_end(month: str) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    if mon == 12:
        return f"{year}-12-31"
    from datetime import timedelta

    return (date(year, mon + 1, 1) - timedelta(days=1)).isoformat()


def season_of_month(month: str) -> tuple[str, str] | None:
    """The pack's unique attribution: the season opening at
    this month when one opens there (November opens rabi),
    otherwise the season whose window contains the month,
    otherwise None — the month belongs to no tracked season."""
    windows = [
        (crop_year, season, demand_rules.season_price_window(crop_year, season))
        for crop_year in CROP_YEARS
        for season in SEASONS
    ]
    opening = [(cy, s) for cy, s, w in windows if w[0] == month]
    if opening:
        return opening[0]
    containing = [(cy, s) for cy, s, w in windows if w[0] <= month <= w[-1]]
    if containing:
        return containing[0]
    return None


def season_close(crop_year: str, season: str) -> str:
    """The default read date for a season's share: the
    month-end of its window's final month."""
    return month_end(demand_rules.season_price_window(crop_year, season)[-1])


def _spread(total: float, window: list[str]) -> dict[str, float]:
    """The supply pack's spread rule: a season total spread
    evenly over its window months, each month carrying
    round(total / n, 3) and the final month the rounding
    residual — so the months sum back to the total exactly."""
    share = round(total / len(window), 3)
    out = {}
    for index, month in enumerate(window):
        out[month] = (
            round(total - share * (len(window) - 1), 3)
            if index == len(window) - 1 else share
        )
    return out


def _fingerprint(material) -> str:
    blob = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _round(value: float, decimals: int) -> float:
    return round(value, decimals) + 0.0


# -- observations ---------------------------------------------------------------


class CompetitorObservation(BaseModel):
    observation_id: str
    competitor: str
    region: str
    district_ids: list[str]  # the districts of the region it covers
    product: str
    month: str
    crop_year: str | None = None  # None: the month belongs to no tracked season
    season: str | None = None
    volume_tonnes: float
    price: float  # INR/tonne, as tracked
    source: str  # provenance: where the figure came from
    source_class: str | None = None  # the pack's class for the source label
    as_of: str  # provenance: the observation date (the point's month-end)


def _slug(label: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", label.upper()).strip("-")


def observation_from_point(point: dict, districts: list[dict]) -> CompetitorObservation:
    """Promote one tracked competitor point to an observation
    artefact. Provenance is part of the artefact: a point
    without a source label or an observation date is refused
    here and can never be stored."""
    source = point.get("source")
    if not source or not str(source).strip():
        raise ValueError(
            "a competitor observation cannot be stored without its "
            "source: provenance is part of the artefact"
        )
    as_of = point.get("as_of")
    if not as_of or not str(as_of).strip():
        raise ValueError(
            "a competitor observation cannot be stored without its "
            "observation date: provenance is part of the artefact"
        )
    attributed = season_of_month(point["month"])
    crop_year, season = attributed if attributed else (None, None)
    return CompetitorObservation(
        observation_id=(
            f"OBS-{_slug(point['competitor'])}-{point['region']}-"
            f"{point['product']}-{point['month']}"
        ),
        competitor=point["competitor"],
        region=point["region"],
        district_ids=sorted(
            d["district_id"] for d in districts if d["region"] == point["region"]
        ),
        product=point["product"],
        month=point["month"],
        crop_year=crop_year,
        season=season,
        volume_tonnes=point["volume_tonnes"],
        price=point["price"],
        source=str(source),
        source_class=pack.source_class(str(source)),
        as_of=str(as_of),
    )


def verify_observation(store, observation: dict) -> list[str]:
    """Re-perform a stored observation from its tracked point:
    the point must be in the store and the artefact must equal
    the promotion of it, provenance included."""
    problems: list[str] = []
    if not observation.get("source") or not observation.get("as_of"):
        problems.append("the observation carries no provenance")
        return problems
    point = next(
        (
            p for p in store.competitor_points(
                observation["competitor"], observation["region"],
                observation["product"],
            )
            if p["month"] == observation["month"]
        ),
        None,
    )
    if point is None:
        return ["the tracked competitor point is not in the store"]
    fresh = observation_from_point(point, store.list_districts())
    if fresh.model_dump() != {
        k: observation[k] for k in fresh.model_dump()
    }:
        problems.append("observation does not re-perform from its tracked point")
    return problems


# -- shares ---------------------------------------------------------------------


class MonthShare(BaseModel):
    month: str
    status: str  # pack MONTH_* states
    market_tonnes: float  # the month's recorded consumption, by the spread
    demand_tonnes: float  # the month's R2 demand estimate, by the spread
    region_observed_market_tonnes: float  # tracked competitors + the anchor
    kaveri_tonnes: float  # the residual for the month
    competitors: list[dict]  # per competitor: observation + distributed figure


class SellerShare(BaseModel):
    seller: str
    volume_tonnes: float
    share_of_observed_market_pct: float
    share_of_total_demand_pct: float


class ShareReading(BaseModel):
    basis: str  # pack BASIS_* labels
    months: list[str]
    observed_market_tonnes: float
    demand_tonnes: float
    kaveri: SellerShare
    competitors: list[SellerShare]
    excluded_observations: list[dict]  # stale / after-read-date, named
    stale_note: str  # "headline excludes N stale observations", or ""


class MarketShare(BaseModel):
    share_id: str
    district_id: str
    region: str
    product: str
    crop_year: str
    season: str
    as_of: str  # the read date the share is struck at
    status: str  # pack STATUS_* states
    estimate_id: str
    estimate_status: str
    demand_total_tonnes: float  # the R2 season demand estimate
    consumption_total_tonnes: float  # the recorded season consumption
    allocation: dict  # the structure basis: region, anchor, member estimates
    kaveri_basis: str  # the residual statement, on the artefact's face
    months: list[MonthShare]
    headline: ShareReading | None = None
    full_season: ShareReading | None = None
    headline_note: str  # the stale-exclusion statement, or ""
    provenance: list[dict]  # every observation in scope: id, seller, source, date
    rules_version: str
    fact_fingerprint: str
    supersedes: str | None = None


def _district_region(store, district_id: str) -> str:
    for district in store.list_districts():
        if district["district_id"] == district_id:
            return district["region"]
    raise ValueError(f"unknown district: {district_id}")


def _head_estimate(store, district_id, product, crop_year, season) -> dict:
    head = head_of(
        store.list_estimates(district_id, product, crop_year, season),
        "estimate_id",
    )
    if head is None:
        raise ValueError(
            f"no demand estimate stored for {district_id} {product} "
            f"{crop_year} {season}: compute the season outlook first"
        )
    return head


def _is_stale(observation: dict, read_date: str) -> tuple[bool, int]:
    """(stale, age in days) under the pack: an observation is
    stale when its age at the read date exceeds its source
    class's stated window; a source with no stated window is
    never fresh."""
    age = (
        date.fromisoformat(read_date) - date.fromisoformat(observation["as_of"])
    ).days
    window = pack.freshness_window_days(observation["source"])
    if window is None:
        return True, age
    return age > window, age


def compute_share(
    store, district_id: str, product: str, crop_year: str, season: str,
    as_of: str,
) -> MarketShare:
    """Compute (but do not store) one district-season share at
    a read date, from the stored observations, the district's
    head R2 estimate and its recorded consumption."""
    region = _district_region(store, district_id)
    window = demand_rules.season_price_window(crop_year, season)

    # Kaveri's home-market anchor: the region's R2 demand
    # total (the region districts' head estimates), spread
    # over the season window — the pack's structure basis.
    region_districts = sorted(
        d["district_id"] for d in store.list_districts() if d["region"] == region
    )
    estimates = {
        d: _head_estimate(store, d, product, crop_year, season)
        for d in region_districts
    }
    region_demand_total = _round(
        sum(e["total_tonnes"] for e in estimates.values()), pack.VOLUME_DECIMALS
    )
    own = estimates[district_id]
    region_anchor_spread = _spread(region_demand_total, window)

    consumption_rows = store.consumption_facts(district_id, crop_year, season, product)
    if not consumption_rows:
        raise ValueError(
            f"no recorded consumption for {district_id} {product} "
            f"{crop_year} {season}: the market total cannot be stated"
        )
    consumption_total = _round(
        sum(r["quantity_tonnes"] for r in consumption_rows), pack.VOLUME_DECIMALS
    )
    market_spread = _spread(consumption_total, window)
    demand_spread = _spread(own["total_tonnes"], window)

    observations = [
        o for o in store.list_competitor_observations(region=region, product=product)
        if o["crop_year"] == crop_year and o["season"] == season
    ]
    by_month: dict[str, list[dict]] = {}
    for observation in observations:
        by_month.setdefault(observation["month"], []).append(observation)
    for month_observations in by_month.values():
        month_observations.sort(key=lambda o: o["competitor"])

    months: list[MonthShare] = []
    for month in window:
        month_observations = by_month.get(month, [])
        # The region's observed market for the month: the
        # tracked competitors' whole-region volumes plus
        # Kaveri's home-market anchor. Each competitor's
        # structure share of it distributes the district's
        # recorded market for the month.
        region_observed = _round(
            sum(o["volume_tonnes"] for o in month_observations)
            + region_anchor_spread[month],
            pack.VOLUME_DECIMALS,
        )
        competitors = []
        allocated_total = 0.0
        any_stale = False
        for observation in month_observations:
            stale, age = _is_stale(observation, as_of)
            any_stale = any_stale or stale
            structure_share = _round(
                observation["volume_tonnes"] / region_observed,
                pack.STRUCTURE_DECIMALS,
            ) if region_observed else 0.0
            allocated = _round(
                market_spread[month] * structure_share, pack.VOLUME_DECIMALS
            )
            allocated_total += allocated
            competitors.append({
                "competitor": observation["competitor"],
                "observation_id": observation["observation_id"],
                "region_volume_tonnes": observation["volume_tonnes"],
                "region_structure_share": structure_share,
                "allocated_tonnes": allocated,
                "price": observation["price"],
                "source": observation["source"],
                "as_of": observation["as_of"],
                "age_days": age,
                "stale": stale,
            })
        if month_end(month) > as_of:
            status = pack.MONTH_AFTER_READ_DATE
        elif month_observations and any_stale:
            status = pack.MONTH_STALE
        elif not month_observations:
            status = pack.MONTH_NO_OBSERVATION
        else:
            status = pack.MONTH_FRESH
        months.append(MonthShare(
            month=month,
            status=status,
            market_tonnes=market_spread[month],
            demand_tonnes=demand_spread[month],
            region_observed_market_tonnes=region_observed,
            kaveri_tonnes=_round(
                market_spread[month] - allocated_total, pack.VOLUME_DECIMALS
            ),
            competitors=competitors,
        ))

    def reading(basis: str, chosen: list[MonthShare]) -> ShareReading:
        kaveri_volume = _round(
            sum(m.kaveri_tonnes for m in chosen), pack.VOLUME_DECIMALS
        )
        observed = _round(
            sum(m.market_tonnes for m in chosen), pack.VOLUME_DECIMALS
        )
        demand = _round(
            sum(m.demand_tonnes for m in chosen), pack.VOLUME_DECIMALS
        )

        def seller_share(seller: str, volume: float) -> SellerShare:
            return SellerShare(
                seller=seller,
                volume_tonnes=volume,
                share_of_observed_market_pct=_round(
                    100.0 * volume / observed, pack.PCT_DECIMALS
                ) if observed else 0.0,
                share_of_total_demand_pct=_round(
                    100.0 * volume / demand, pack.PCT_DECIMALS
                ) if demand else 0.0,
            )

        competitor_names = sorted({
            c["competitor"] for m in chosen for c in m.competitors
        })
        competitor_shares = [
            seller_share(
                name,
                _round(
                    sum(
                        c["allocated_tonnes"] for m in chosen
                        for c in m.competitors if c["competitor"] == name
                    ),
                    pack.VOLUME_DECIMALS,
                ),
            )
            for name in competitor_names
        ]
        excluded = []
        if basis == pack.BASIS_HEADLINE:
            for month_row in months:
                if month_row.status in (
                    pack.MONTH_STALE, pack.MONTH_AFTER_READ_DATE
                ):
                    for c in month_row.competitors:
                        excluded.append({
                            "observation_id": c["observation_id"],
                            "competitor": c["competitor"],
                            "month": month_row.month,
                            "as_of": c["as_of"],
                            "age_days": c["age_days"],
                            "reason": (
                                "stale" if month_row.status == pack.MONTH_STALE
                                else "after_read_date"
                            ),
                        })
            excluded.sort(key=lambda e: e["observation_id"])
        stale_count = sum(1 for e in excluded if e["reason"] == "stale")
        return ShareReading(
            basis=basis,
            months=[m.month for m in chosen],
            observed_market_tonnes=observed,
            demand_tonnes=demand,
            kaveri=seller_share(pack.KAVERI_SELLER, kaveri_volume),
            competitors=competitor_shares,
            excluded_observations=excluded,
            stale_note=(
                f"headline excludes {stale_count} stale observations"
                if stale_count else ""
            ),
        )

    headline_months = [m for m in months if m.status in pack.HEADLINE_MONTH_STATES]
    full_months = [m for m in months if m.status != pack.MONTH_AFTER_READ_DATE]
    if not observations:
        status = pack.STATUS_NO_OBSERVATIONS
        headline = None
        full = None
    elif not headline_months:
        status = pack.STATUS_NOT_CURRENT
        headline = None
        full = reading(pack.BASIS_FULL_SEASON, full_months)
    else:
        status = pack.STATUS_CURRENT
        headline = reading(pack.BASIS_HEADLINE, headline_months)
        full = reading(pack.BASIS_FULL_SEASON, full_months)

    fingerprint = _fingerprint({
        "share": [district_id, product, crop_year, season, as_of],
        "rules": pack.RULES_VERSION,
        "estimates": [
            [d, estimates[d]["estimate_id"], estimates[d]["total_tonnes"]]
            for d in region_districts
        ],
        "consumption_total": consumption_total,
        "observations": [
            [o["observation_id"], o["volume_tonnes"], o["as_of"]]
            for o in sorted(observations, key=lambda o: o["observation_id"])
        ],
    })
    return MarketShare(
        share_id=(
            f"SHARE-{district_id}-{product}-{crop_year}-{season}-"
            f"{fingerprint[:10]}"
        ),
        district_id=district_id,
        region=region,
        product=product,
        crop_year=crop_year,
        season=season,
        as_of=as_of,
        status=status,
        estimate_id=own["estimate_id"],
        estimate_status=own["status"],
        demand_total_tonnes=own["total_tonnes"],
        consumption_total_tonnes=consumption_total,
        allocation={
            "region": region,
            "region_district_ids": region_districts,
            "region_demand_total_tonnes": region_demand_total,
            "kaveri_anchor": (
                "the region's R2 demand total, spread over the season "
                "window — Kaveri's home-market anchor in the region's "
                "observed market"
            ),
            "estimate_ids": {d: estimates[d]["estimate_id"] for d in region_districts},
        },
        kaveri_basis=(
            "residual: the district's recorded consumption less the "
            "tracked competitors' structure-distributed volumes — "
            "any untracked seller sits inside the residual"
        ),
        months=months,
        headline=headline,
        full_season=full,
        headline_note=headline.stale_note if headline else "",
        provenance=[
            {
                "observation_id": o["observation_id"],
                "competitor": o["competitor"],
                "source": o["source"],
                "as_of": o["as_of"],
            }
            for o in sorted(observations, key=lambda o: o["observation_id"])
        ],
        rules_version=pack.RULES_VERSION,
        fact_fingerprint=fingerprint,
    )


def verify_share(store, share: dict) -> list[str]:
    """Re-perform a stored share from the store today: the
    computation is a pure function of the stored observations,
    estimates and consumption, so a tampered figure — or one
    whose inputs have moved without a superseding share —
    fails here."""
    problems: list[str] = []
    if share["rules_version"] != pack.RULES_VERSION:
        return [f"share names unknown share pack {share['rules_version']}"]
    fresh = compute_share(
        store, share["district_id"], share["product"], share["crop_year"],
        share["season"], share["as_of"],
    )
    stored = {k: share[k] for k in fresh.model_dump() if k != "supersedes"}
    if fresh.model_dump(exclude={"supersedes"}) != stored:
        problems.append("share does not re-perform from the stored inputs")
    return problems


# -- movements --------------------------------------------------------------------


class ShareMovement(BaseModel):
    movement_id: str
    district_id: str
    region: str
    product: str
    season: str
    from_crop_year: str
    to_crop_year: str
    basis: str  # the readings compared: the pack's full-season basis
    share_ids: dict  # crop_year -> share_id
    rows: list[dict]  # per seller: shares + change, volumes
    biggest_mover: dict  # seller, change, the provenance behind both years
    rules_version: str
    fact_fingerprint: str
    as_of: str
    supersedes: str | None = None


def _reading_rows(share: dict) -> dict[str, dict]:
    reading = share["full_season"]
    rows = {reading["kaveri"]["seller"]: reading["kaveri"]}
    for competitor in reading["competitors"]:
        rows[competitor["seller"]] = competitor
    return rows


def compute_movement(
    store, from_share: dict, to_share: dict, as_of: str
) -> ShareMovement:
    """Compute (but do not store) the movement between two
    crop years' share artefacts for one district x product x
    season. The comparison basis is the full-season reading of
    each — the like-for-like season view — stated on the
    artefact."""
    for label, share in (("from", from_share), ("to", to_share)):
        if share["full_season"] is None:
            raise ValueError(
                f"the {label} year's share ({share['share_id']}) carries no "
                "full-season reading: movement cannot be stated"
            )
        if share["status"] == pack.STATUS_NO_OBSERVATIONS:
            raise ValueError(
                f"the {label} year's share ({share['share_id']}) has no "
                "competitor observations: movement cannot be stated"
            )
    if not (
        from_share["district_id"] == to_share["district_id"]
        and from_share["product"] == to_share["product"]
        and from_share["season"] == to_share["season"]
    ):
        raise ValueError("the two shares are not the same district, product and season")

    from_rows = _reading_rows(from_share)
    to_rows = _reading_rows(to_share)
    sellers = [pack.KAVERI_SELLER] + sorted(
        (set(from_rows) | set(to_rows)) - {pack.KAVERI_SELLER}
    )
    rows = []
    for seller in sellers:
        before = from_rows.get(seller)
        after = to_rows.get(seller)
        rows.append({
            "seller": seller,
            "share_from_pct": before["share_of_observed_market_pct"] if before else None,
            "share_to_pct": after["share_of_observed_market_pct"] if after else None,
            "change_pp": _round(
                (after["share_of_observed_market_pct"] if after else 0.0)
                - (before["share_of_observed_market_pct"] if before else 0.0),
                pack.PCT_DECIMALS,
            ),
            "volume_from_tonnes": before["volume_tonnes"] if before else None,
            "volume_to_tonnes": after["volume_tonnes"] if after else None,
        })
    biggest = max(rows, key=lambda r: abs(r["change_pp"]))

    def provenance_ids(share: dict, seller: str) -> list[str]:
        return sorted(
            p["observation_id"] for p in share["provenance"]
            if p["competitor"] == seller
        )

    fingerprint = _fingerprint({
        "movement": [
            from_share["district_id"], from_share["product"],
            from_share["season"], from_share["crop_year"],
            to_share["crop_year"],
        ],
        "rules": pack.RULES_VERSION,
        "shares": [from_share["share_id"], from_share["fact_fingerprint"],
                   to_share["share_id"], to_share["fact_fingerprint"]],
    })
    return ShareMovement(
        movement_id=(
            f"SHMOVE-{from_share['district_id']}-{from_share['product']}-"
            f"{from_share['season']}-{fingerprint[:10]}"
        ),
        district_id=from_share["district_id"],
        region=from_share["region"],
        product=from_share["product"],
        season=from_share["season"],
        from_crop_year=from_share["crop_year"],
        to_crop_year=to_share["crop_year"],
        basis=pack.BASIS_FULL_SEASON,
        share_ids={
            from_share["crop_year"]: from_share["share_id"],
            to_share["crop_year"]: to_share["share_id"],
        },
        rows=rows,
        biggest_mover={
            "seller": biggest["seller"],
            "change_pp": biggest["change_pp"],
            "from_share_id": from_share["share_id"],
            "to_share_id": to_share["share_id"],
            "observation_ids_from": provenance_ids(from_share, biggest["seller"]),
            "observation_ids_to": provenance_ids(to_share, biggest["seller"]),
        },
        rules_version=pack.RULES_VERSION,
        fact_fingerprint=fingerprint,
        as_of=as_of,
    )


def verify_movement(store, movement: dict) -> list[str]:
    """Re-perform a stored movement from the two share
    artefacts it names: both must be in the store and the
    movement must equal the comparison of their full-season
    readings."""
    problems: list[str] = []
    if movement["rules_version"] != pack.RULES_VERSION:
        return [f"movement names unknown share pack {movement['rules_version']}"]
    from_share = store.get_share(movement["share_ids"][movement["from_crop_year"]])
    to_share = store.get_share(movement["share_ids"][movement["to_crop_year"]])
    if from_share is None or to_share is None:
        return ["a share artefact the movement names is not in the store"]
    fresh = compute_movement(store, from_share, to_share, movement["as_of"])
    stored = {k: movement[k] for k in fresh.model_dump() if k != "supersedes"}
    if fresh.model_dump(exclude={"supersedes"}) != stored:
        problems.append("movement does not re-perform from its share artefacts")
    return problems
