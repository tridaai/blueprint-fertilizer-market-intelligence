"""Season-close estimate scoring (R12).

Once a season has closed and its actuals are on record
(R11), the demand engine's struck estimates are graded
against them — per district × product × season cell, in
code, from the stored artefacts alone. Nothing here
re-estimates: a score reads the head estimate artefact
and the actual row it is graded against, and derives
error, bias and a driver attribution under the versioned
pack in :mod:`.scoring_rules`.

The attribution answers the question a planner actually
asks of a missed season — *which part of the estimate was
most wrong?* The pack's stated method attributes the
total signed error across the estimate's own contribution
lines in proportion to each line's signed share of the
estimate total, so the attributed errors sum back to the
total error and a driver that never moved the estimate
can never be blamed for its miss.

Discipline, matching the repo's other artefact families:

- Score runs are **insert-only, content-addressed
  artefacts**: re-scoring an unchanged record returns the
  stored run; re-scoring a moved record stores a new run.
- **Independent re-performance**: :func:`verify_score_run`
  rebuilds every cell by a second route — line deltas
  re-derived from the contribution lines' recorded
  ``value_after`` chain instead of their stated deltas,
  the total taken from the chain's end instead of the
  estimate's stated total — and compares field for field.
  One mismatch refuses a candidate run wholesale: the
  refusal is recorded as its own artefact and no score
  from the run is stored.
- **Unmatched cells are named, never dropped**: an actual
  with no struck estimate and a head estimate with no
  actual are both reported on the run's face, extending
  the actuals report's discipline (R11) to both
  directions of the join.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

from . import ingest_rules as ingest_pack
from . import scoring_rules as pack
from .demand import head_of


def _fingerprint(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


class ScoringRefused(RuntimeError):
    """A score run failed re-performance and was refused
    wholesale — the refusal artefact is on record and
    nothing of the run is stored."""

    def __init__(self, problems: list[str], refusal_id: str | None = None):
        self.problems = problems
        self.refusal_id = refusal_id
        super().__init__("score run refused: " + "; ".join(problems))


# ---------------------------------------------------------------------------
# Artefacts
# ---------------------------------------------------------------------------


class AttributionLine(BaseModel):
    line_no: int
    driver: str
    status: str  # applied / missing / not_applicable, as recorded
    delta_tonnes: float
    share: float | None
    attributed_error_tonnes: float | None


class ScoreCell(BaseModel):
    district_id: str
    product: str
    actual_kind: str
    estimate_id: str
    estimate_status: str  # complete / partial, as struck
    estimate_tonnes: float
    actual_tonnes: float
    error_tonnes: float
    abs_error_tonnes: float
    error_pct: float | None
    zero_actual: bool
    attribution: str  # the pack method, or not_attributable
    lines: list[AttributionLine]
    most_wrong_line_no: int | None
    most_wrong_driver: str | None
    most_wrong_attributed_error_tonnes: float | None
    actual_source: str
    actual_as_of: str


class SeasonScoreRun(BaseModel):
    score_id: str
    fingerprint: str
    crop_year: str
    season: str
    as_of: str
    scored_by: str
    rules_version: str
    attribution_method: str
    actual_batches: list[str]
    cells: list[ScoreCell]
    scored_count: int
    bias_tonnes: float | None
    mean_abs_error_pct: float | None
    unmatched_actuals: list[str]
    unmatched_estimates: list[dict]


class ScoreRefusal(BaseModel):
    refusal_id: str
    fingerprint: str
    crop_year: str
    season: str
    as_of: str
    scored_by: str
    rules_version: str
    problems: list[str]


# ---------------------------------------------------------------------------
# The join: head estimates and actual rows for one season
# ---------------------------------------------------------------------------


def _head_estimates(store, crop_year: str, season: str) -> dict:
    groups: dict[tuple, list[dict]] = {}
    for estimate in store.list_estimates(crop_year=crop_year,
                                         season=season):
        groups.setdefault(
            (estimate["district_id"], estimate["product"]), []
        ).append(estimate)
    heads = {}
    for natural, rows in groups.items():
        head = head_of(rows, "estimate_id")
        if head is not None:
            heads[natural] = head
    return heads


def _actual_batches(store, crop_year: str, season: str) -> list[str]:
    """The connector batches that delivered this season's
    actual rows, resolved from the batches' own recorded
    inserted rows — a score names the batch it grades."""
    batch_ids = []
    for batch in store.list_ingest_batches(
            fact_class=ingest_pack.SEASON_ACTUALS):
        inserted = (batch.get("inserted_rows") or {}).get(
            ingest_pack.SEASON_ACTUALS) or []
        if any(row.get("crop_year") == crop_year
               and row.get("season") == season for row in inserted):
            batch_ids.append(batch["batch_id"])
    return sorted(batch_ids)


def _unmatched_actual_label(actual: dict) -> str:
    return ingest_pack.key_label(ingest_pack.SEASON_ACTUALS, {
        "district_id": actual["district_id"],
        "crop_year": actual["crop_year"],
        "season": actual["season"],
        "product": actual["product"],
        "actual_kind": actual["actual_kind"],
    })


# ---------------------------------------------------------------------------
# Cell construction — one builder, two delta routes
# ---------------------------------------------------------------------------


def _line_deltas(contributions: list[dict], route: str) -> list[float]:
    """Route 1 reads each line's stated delta. Route 2
    re-derives the deltas from the recorded value-after
    chain: the base line's delta is its value after, and
    every later line's delta is the step to its own value
    after. The two routes agree on an untampered artefact
    and disagree on a tampered one."""
    if route == "stated":
        return [line["delta_tonnes"] for line in contributions]
    deltas = []
    previous = 0.0
    for line in contributions:
        deltas.append(round(line["value_after_tonnes"] - previous, 3))
        previous = line["value_after_tonnes"]
    return deltas


def _build_cell(estimate: dict, actual: dict,
                contributions: list[dict], route: str) -> ScoreCell:
    deltas = _line_deltas(contributions, route)
    if route == "stated":
        total = estimate["total_tonnes"]
    else:
        total = contributions[-1]["value_after_tonnes"] \
            if contributions else estimate["total_tonnes"]
    actual_tonnes = actual["quantity_tonnes"]
    error = round(actual_tonnes - total, 3)
    zero_actual = actual_tonnes == 0
    error_pct = None if zero_actual else round(
        error / actual_tonnes * 100.0, pack.PCT_DECIMALS)
    lines: list[AttributionLine] = []
    most_wrong: AttributionLine | None = None
    if total == 0:
        attribution = "not_attributable"
        for line, delta in zip(contributions, deltas):
            lines.append(AttributionLine(
                line_no=line["line_no"], driver=line["driver"],
                status=line["status"], delta_tonnes=delta,
                share=None, attributed_error_tonnes=None))
    else:
        attribution = pack.ATTRIBUTION_METHOD
        for line, delta in zip(contributions, deltas):
            share = delta / total
            attributed = round(error * share, 3)
            entry = AttributionLine(
                line_no=line["line_no"], driver=line["driver"],
                status=line["status"], delta_tonnes=delta,
                share=share, attributed_error_tonnes=attributed)
            lines.append(entry)
            if most_wrong is None or (
                abs(attributed)
                > abs(most_wrong.attributed_error_tonnes)
            ):
                most_wrong = entry
    return ScoreCell(
        district_id=estimate["district_id"],
        product=estimate["product"],
        actual_kind=actual["actual_kind"],
        estimate_id=estimate["estimate_id"],
        estimate_status=estimate["status"],
        estimate_tonnes=total,
        actual_tonnes=actual_tonnes,
        error_tonnes=error,
        abs_error_tonnes=abs(error),
        error_pct=error_pct,
        zero_actual=zero_actual,
        attribution=attribution,
        lines=lines,
        most_wrong_line_no=most_wrong.line_no if most_wrong else None,
        most_wrong_driver=most_wrong.driver if most_wrong else None,
        most_wrong_attributed_error_tonnes=(
            most_wrong.attributed_error_tonnes if most_wrong else None),
        actual_source=actual["source"],
        actual_as_of=actual["as_of"],
    )


def _build_cells(store, crop_year: str, season: str,
                 route: str) -> tuple[list[ScoreCell], list[str],
                                      list[dict]]:
    heads = _head_estimates(store, crop_year, season)
    actuals = store.season_actuals(crop_year=crop_year, season=season)
    cells: list[ScoreCell] = []
    unmatched_actuals: list[str] = []
    matched_keys: set[tuple] = set()
    for actual in actuals:
        natural = (actual["district_id"], actual["product"])
        estimate = heads.get(natural)
        if estimate is None:
            unmatched_actuals.append(_unmatched_actual_label(actual))
            continue
        matched_keys.add(natural)
        contributions = store.estimate_contributions(
            estimate["estimate_id"])
        cells.append(_build_cell(estimate, actual, contributions,
                                 route))
    unmatched_estimates = []
    for natural, estimate in sorted(heads.items()):
        if natural not in matched_keys:
            district_id, product = natural
            unmatched_estimates.append({
                "estimate_id": estimate["estimate_id"],
                "district_id": district_id,
                "product": product,
                "label": (f"{district_id}/{crop_year}/{season}/"
                          f"{product}"),
            })
    cells.sort(key=lambda c: (c.district_id, c.product,
                              c.actual_kind))
    return cells, sorted(unmatched_actuals), unmatched_estimates


def _summary(cells: list[ScoreCell]) -> tuple[float | None,
                                             float | None]:
    if not cells:
        return None, None
    bias = round(sum(c.error_tonnes for c in cells) / len(cells), 3)
    pcts = [abs(c.error_pct) for c in cells if c.error_pct is not None]
    mean_abs_pct = round(sum(pcts) / len(pcts), pack.PCT_DECIMALS) \
        if pcts else None
    return bias, mean_abs_pct


def _content(crop_year: str, season: str, as_of: str,
             scored_by: str, batches: list[str],
             cells: list[ScoreCell], unmatched_actuals: list[str],
             unmatched_estimates: list[dict]) -> dict:
    bias, mean_abs_pct = _summary(cells)
    return {
        "crop_year": crop_year, "season": season, "as_of": as_of,
        "scored_by": scored_by, "rules_version": pack.SCORING_VERSION,
        "attribution_method": pack.ATTRIBUTION_METHOD,
        "actual_batches": batches,
        "cells": [c.model_dump() for c in cells],
        "scored_count": len(cells),
        "bias_tonnes": bias, "mean_abs_error_pct": mean_abs_pct,
        "unmatched_actuals": unmatched_actuals,
        "unmatched_estimates": unmatched_estimates,
    }


def build_score_run(store, crop_year: str, season: str, as_of: str,
                    scored_by: str) -> SeasonScoreRun:
    """Assemble the candidate score run for a closed season
    by the stated-delta route. Storage and the refusal
    discipline live in the service, as with the brief."""
    cells, unmatched_actuals, unmatched_estimates = _build_cells(
        store, crop_year, season, route="stated")
    batches = _actual_batches(store, crop_year, season)
    content = _content(crop_year, season, as_of, scored_by, batches,
                       cells, unmatched_actuals, unmatched_estimates)
    fingerprint = _fingerprint(content)
    return SeasonScoreRun(
        score_id=f"SCR-{fingerprint[:10]}", fingerprint=fingerprint,
        **content)


def build_refusal(crop_year: str, season: str, as_of: str,
                  scored_by: str, problems: list[str]) -> ScoreRefusal:
    fingerprint = _fingerprint({
        "crop_year": crop_year, "season": season, "as_of": as_of,
        "scored_by": scored_by, "rules_version": pack.SCORING_VERSION,
        "problems": problems,
    })
    return ScoreRefusal(
        refusal_id=f"SCX-{fingerprint[:10]}", fingerprint=fingerprint,
        crop_year=crop_year, season=season, as_of=as_of,
        scored_by=scored_by, rules_version=pack.SCORING_VERSION,
        problems=problems)


# ---------------------------------------------------------------------------
# Re-performance: the verifier
# ---------------------------------------------------------------------------


def verify_score_run(store, run: dict) -> list[str]:
    """Rebuild the run's cells by the value-after route and
    compare field for field, then re-derive the unmatched
    sets, the summary and the content fingerprint. An
    empty list means the stored run re-performs."""
    problems: list[str] = []
    cells, unmatched_actuals, unmatched_estimates = _build_cells(
        store, run["crop_year"], run["season"], route="value_after")
    rebuilt = [c.model_dump() for c in cells]
    stated = run["cells"]
    if len(rebuilt) != len(stated):
        problems.append(
            f"scored cell count: stored {len(stated)} vs "
            f"re-performed {len(rebuilt)}")
    for want, got in zip(rebuilt, stated):
        label = (f"{got.get('district_id')}/{got.get('product')}/"
                 f"{got.get('actual_kind')}")
        for field in ("estimate_id", "estimate_tonnes",
                      "actual_tonnes", "error_tonnes",
                      "abs_error_tonnes", "error_pct", "zero_actual",
                      "attribution", "most_wrong_line_no",
                      "most_wrong_driver",
                      "most_wrong_attributed_error_tonnes"):
            if want[field] != got.get(field):
                problems.append(
                    f"cell {label}: {field} stored "
                    f"{got.get(field)!r} vs re-performed "
                    f"{want[field]!r}")
        want_lines = {(l["line_no"]): l for l in want["lines"]}
        for line in got.get("lines", []):
            want_line = want_lines.get(line["line_no"])
            if want_line is None:
                problems.append(
                    f"cell {label}: line {line['line_no']} has no "
                    f"re-performed counterpart")
                continue
            for field in ("driver", "status", "delta_tonnes",
                          "share", "attributed_error_tonnes"):
                w, g = want_line[field], line.get(field)
                if isinstance(w, float) and isinstance(g, (int, float)):
                    if abs(w - g) > pack.ATTRIBUTION_TOL:
                        problems.append(
                            f"cell {label} line {line['line_no']}: "
                            f"{field} stored {g!r} vs re-performed "
                            f"{w!r}")
                elif w != g:
                    problems.append(
                        f"cell {label} line {line['line_no']}: "
                        f"{field} stored {g!r} vs re-performed {w!r}")
        attributed_sum = sum(
            l["attributed_error_tonnes"] for l in got.get("lines", [])
            if l.get("attributed_error_tonnes") is not None)
        if got.get("attribution") == pack.ATTRIBUTION_METHOD and abs(
                attributed_sum - got["error_tonnes"]
        ) > pack.ATTRIBUTION_TOL:
            problems.append(
                f"cell {label}: attributed errors sum to "
                f"{attributed_sum} against a total error of "
                f"{got['error_tonnes']}")
    if unmatched_actuals != run["unmatched_actuals"]:
        problems.append("unmatched actuals do not re-perform")
    if unmatched_estimates != run["unmatched_estimates"]:
        problems.append("unmatched estimates do not re-perform")
    bias, mean_abs_pct = _summary(
        [ScoreCell(**c) for c in rebuilt])
    if bias != run["bias_tonnes"] or \
            mean_abs_pct != run["mean_abs_error_pct"]:
        problems.append("run summary does not re-perform")
    content = _content(
        run["crop_year"], run["season"], run["as_of"],
        run["scored_by"], run["actual_batches"],
        [ScoreCell(**c) for c in stated],
        run["unmatched_actuals"], run["unmatched_estimates"])
    if _fingerprint(content) != run["fingerprint"]:
        problems.append("run fingerprint does not re-perform")
    return problems
