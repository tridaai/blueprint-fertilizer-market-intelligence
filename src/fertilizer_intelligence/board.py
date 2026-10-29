"""The market morning board (R13, roadmap F21-OW1).

One opening view per role: open alerts, districts
trending short, stale figures, pending brief approvals.
Regional heads run districts, not queries — so the board
is struck for them, from the artefacts, under the board
pack (:mod:`.board_rules`), and it is an artefact like
everything else it reads:

- **Rows re-derive from artefacts.** An alert row exists
  because the alert's fold of acts says open — the
  moment an acknowledgement or closure act lands, the
  next board's open lane no longer holds it, exactly per
  derived state. A short-district row is a map cell whose
  composed gap band is tight or short, derived from the
  same cell composition the map verifier re-performs. A
  stale row names the share artefact whose own readings
  carry stale observations. A pending-brief row exists
  because no publication act names that brief.
- **Ranking is the packs', never recency's.** The board
  pack states the order of every lane; the builder sorts
  by it and the verifier re-derives the same order, so a
  board that quietly re-sorted itself by what is newest
  would fail verification.
- **Verification before storage.** A candidate board is
  re-derived lane for lane by a second route before
  anything is stored; one wrong row refuses the whole
  board and the refusal is recorded. A stored board
  re-verifies the same way, plus a byte-exact re-render
  of its page.
- **The page is static and read-only** — one HTML page
  rendered from the artefact alone, no form, no POST, no
  control verb.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

from . import alert_rules as alert_pack
from . import board_rules as pack
from . import brief as brief_engine
from . import brief_rules as brief_pack
from . import market_map as map_engine
from . import movements as movement_engine
from . import supply_rules as supply_pack
from .dashboard import _CSS, _esc, _fmt
from .demand import head_of


class BoardRefused(RuntimeError):
    """A lane row did not re-derive from its artefacts at
    build time. The whole board is refused; nothing
    partial is stored."""

    def __init__(self, problems: list[str], refusal_id: str | None = None):
        self.problems = problems
        self.refusal_id = refusal_id
        super().__init__("morning board refused: " + "; ".join(problems))


# ---------------------------------------------------------------------------
# Artefacts
# ---------------------------------------------------------------------------


class MorningBoard(BaseModel):
    board_id: str
    fingerprint: str
    role: str
    crop_year: str
    season: str
    as_of: str
    built_by: str
    rules_version: str
    lanes: list[dict]
    html: str
    supersedes: str | None = None


class BoardRefusal(BaseModel):
    refusal_id: str
    fingerprint: str
    role: str
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
# Lane derivation (the builder's route)
# ---------------------------------------------------------------------------


def _alert_row(alert: dict) -> dict:
    figure_name = pack.RULE_FIGURE[alert["rule_id"]]
    return {
        "alert_id": alert["alert_id"],
        "series_kind": alert["series_kind"],
        "item": alert["item"],
        "rule_id": alert["rule_id"],
        "band": alert["band"],
        "period_month": alert["period_month"],
        "figure_name": figure_name,
        "figure_value": alert["figures"].get(figure_name),
    }


def alert_sort_key(row: dict) -> tuple:
    return (
        -alert_pack.BAND_RANK[row["band"]],
        -pack.RULE_RANK[row["rule_id"]],
        -abs(row["figure_value"] or 0.0),
        row["alert_id"],
    )


def derive_open_alerts(store, as_of: str) -> list[dict]:
    """Alerts whose derived state at the board's date is
    open — the fold of their acts recorded on or before
    that date, nothing else. Acknowledged and closed
    alerts are not in this lane, exactly per state."""
    rows = []
    for alert in store.list_alerts():
        acts = [a for a in store.list_alert_acts(alert["alert_id"])
                if a["as_of"] <= as_of]
        if movement_engine.derive_state(acts) == "open":
            rows.append(_alert_row(alert))
    return sorted(rows, key=alert_sort_key)


def short_sort_key(row: dict) -> tuple:
    gap_pct = row["gap_pct_of_demand"]
    return (
        -supply_pack.BAND_RANK[row["district_gap_band"]],
        gap_pct is None,
        gap_pct if gap_pct is not None else 0.0,
        -(row["demand_tonnes"] or 0.0),
        row["district_id"],
        row["product"],
    )


def derive_short_districts(store, crop_year: str, season: str,
                           map_id: str | None,
                           as_of: str | None = None) -> list[dict]:
    """District rows from the map's cell composition:
    every cell whose composed gap band is tight or short,
    ranked by the gap pack's severity order."""
    rows = []
    for cell in map_engine.build_cells(store, crop_year, season, as_of):
        if cell["district_gap_band"] in ("tight", "short"):
            rows.append({
                "district_id": cell["district_id"],
                "district_name": cell["district_name"],
                "product": cell["product"],
                "district_gap_band": cell["district_gap_band"],
                "district_gap_basis": cell["district_gap_basis"],
                "gap_pct_of_demand": cell["gap_pct_of_demand"],
                "demand_tonnes": cell["demand_tonnes"],
                "estimate_id": cell["estimate_id"],
                "gap_id": cell["gap_id"],
                "map_id": map_id,
            })
    return sorted(rows, key=short_sort_key)


def _stale_reading(share: dict) -> dict | None:
    """One share artefact's stale position, read off its
    own readings: the stale observations its headline
    excludes (or, with no headline, its full-season
    reading carries) and its stale months. None when the
    artefact carries nothing stale."""
    reading = share.get("headline") or share.get("full_season")
    if reading is None:
        return None
    stale_observations = sum(
        1 for e in reading["excluded_observations"]
        if e["reason"] == "stale")
    stale_months = 0
    months = {m["month"]: m for m in share.get("months", [])}
    for month in reading["months"]:
        row = months.get(month)
        if row is not None and row["status"] == "stale":
            stale_months += 1
    if not stale_observations and not stale_months:
        return None
    return {
        "share_id": share["share_id"],
        "district_id": share["district_id"],
        "product": share["product"],
        "stale_observations": stale_observations,
        "stale_months": stale_months,
        "headline_note": share["headline_note"],
    }


def stale_sort_key(row: dict) -> tuple:
    return (
        -row["stale_observations"],
        -row["stale_months"],
        row["district_id"],
        row["product"],
    )


def derive_stale_figures(store, crop_year: str, season: str) -> list[dict]:
    """The current share artefact per district and
    product — the latest read date's head — carrying
    stale evidence on its face."""
    grouped: dict[tuple, list[dict]] = {}
    for share in store.list_shares(crop_year=crop_year, season=season):
        grouped.setdefault(
            (share["district_id"], share["product"]), []).append(share)
    rows = []
    for group in grouped.values():
        latest_date = max(s["as_of"] for s in group)
        head = head_of(
            [s for s in group if s["as_of"] == latest_date], "share_id")
        if head is None:
            continue
        row = _stale_reading(head)
        if row is not None:
            rows.append(row)
    return sorted(rows, key=stale_sort_key)


def brief_severity(brief: dict) -> tuple[str, dict]:
    """A brief's severity, read off the figures its own
    sections carry: the heaviest class present under the
    board pack, with the counts that produced it."""
    counts = {"short_gaps": 0, "tight_gaps": 0,
              "alert_band_alerts": 0, "watch_band_alerts": 0}
    for section in brief["sections"]:
        if section["key"] == brief_pack.SECTION_SUPPLY:
            for figure in section["figures"]:
                if figure["unit"] == "band" and figure["value"] == "short":
                    counts["short_gaps"] += 1
                elif figure["unit"] == "band" and figure["value"] == "tight":
                    counts["tight_gaps"] += 1
        elif section["key"] == brief_pack.SECTION_PRICES:
            for figure in section["figures"]:
                if "alert" in figure["badges"]:
                    counts["alert_band_alerts"] += 1
                elif "watch" in figure["badges"]:
                    counts["watch_band_alerts"] += 1
    if counts["short_gaps"]:
        name = "short_gap"
    elif counts["alert_band_alerts"]:
        name = "alert_band_alert"
    elif counts["tight_gaps"]:
        name = "tight_gap"
    elif counts["watch_band_alerts"]:
        name = "watch_band_alert"
    else:
        name = "none"
    return name, counts


def pending_sort_key(row: dict) -> tuple:
    return (-row["severity"],)


def derive_pending_briefs(store) -> list[dict]:
    """Briefs no publication act names — still drafts,
    still waiting for a decision. Ranked by the severity
    of what they carry; the week ending breaks ties
    between equals, and nothing else about recency plays
    any part."""
    acts = store.list_publication_acts()
    rows = []
    for brief in store.list_weekly_briefs():
        state = brief_engine.publication_state(
            acts, brief_pack.KIND_BRIEF, brief["brief_id"])
        if state["status"] != "draft":
            continue
        name, counts = brief_severity(brief)
        rows.append({
            "brief_id": brief["brief_id"],
            "week_start": brief["week_start"],
            "week_ending": brief["week_ending"],
            "severity": pack.BRIEF_SEVERITY[name],
            "severity_class": name,
            **counts,
        })
    rows.sort(key=lambda r: (r["week_ending"], r["brief_id"]), reverse=True)
    rows.sort(key=pending_sort_key)
    return rows


def build_board(store, role: str, crop_year: str, season: str,
                as_of: str, built_by: str,
                map_id: str | None = None) -> MorningBoard:
    """Build (do not store) the candidate board for one
    role and season scope."""
    if role not in pack.ROLE_LANES:
        raise ValueError(
            f"unknown board role: {role!r} — the board pack names "
            f"{sorted(pack.ROLE_LANES)}")
    derivations = {
        pack.LANE_OPEN_ALERTS: lambda: derive_open_alerts(store, as_of),
        pack.LANE_SHORT_DISTRICTS: lambda: derive_short_districts(
            store, crop_year, season, map_id, as_of),
        pack.LANE_STALE_FIGURES: lambda: derive_stale_figures(
            store, crop_year, season),
        pack.LANE_PENDING_BRIEFS: lambda: derive_pending_briefs(store),
    }
    lanes = [
        {"lane": lane, "title": pack.LANE_TITLES[lane],
         "rows": derivations[lane]()}
        for lane in pack.ROLE_LANES[role]
    ]
    fingerprint = _fingerprint({
        "role": role, "scope": [crop_year, season],
        "pack": pack.RULES_VERSION, "lanes": lanes,
    })
    draft = MorningBoard(
        board_id=f"BRD-{role}-{fingerprint[:10]}",
        fingerprint=fingerprint, role=role,
        crop_year=crop_year, season=season, as_of=as_of,
        built_by=built_by, rules_version=pack.RULES_VERSION,
        lanes=lanes, html="",
    )
    return draft.model_copy(
        update={"html": render_board_html(draft.model_dump())})


def build_refusal(role: str, crop_year: str, season: str, as_of: str,
                  built_by: str, problems: list[str]) -> BoardRefusal:
    fingerprint = _fingerprint({
        "role": role, "scope": [crop_year, season], "as_of": as_of,
        "built_by": built_by, "problems": problems,
        "pack": pack.RULES_VERSION,
    })
    return BoardRefusal(
        refusal_id=f"BRX-{fingerprint[:10]}", fingerprint=fingerprint,
        role=role, crop_year=crop_year, season=season, as_of=as_of,
        built_by=built_by, rules_version=pack.RULES_VERSION,
        problems=problems,
    )


# ---------------------------------------------------------------------------
# Re-performance: the verifier's second route
# ---------------------------------------------------------------------------


def _expected_lanes(store, board_dict: dict) -> list[dict]:
    """Re-derive the board's lanes from the store's rows
    by a separate pass — states folded inline, cells read
    through the map verifier's own route, share heads
    picked by scan — and compare against the stored
    lanes as ordered lists."""
    role = board_dict["role"]
    crop_year, season = board_dict["crop_year"], board_dict["season"]
    expected: dict[str, list[dict]] = {}

    open_rows = []
    for alert in store.list_alerts():
        state = "open"
        for act in store.list_alert_acts(alert["alert_id"]):
            if act["as_of"] > board_dict["as_of"]:
                continue
            if act["act"] == "acknowledge":
                state = "acknowledged"
            elif act["act"] == "close":
                state = "closed"
        if state == "open":
            open_rows.append(_alert_row(alert))
    expected[pack.LANE_OPEN_ALERTS] = sorted(open_rows, key=alert_sort_key)

    map_head = head_of(
        store.list_market_maps(crop_year, season), "map_id")
    short_rows = []
    for cell in map_engine._expected_cells(
            store, crop_year, season, board_dict["as_of"]):
        if cell["district_gap_band"] in ("tight", "short"):
            short_rows.append({
                "district_id": cell["district_id"],
                "district_name": cell["district_name"],
                "product": cell["product"],
                "district_gap_band": cell["district_gap_band"],
                "district_gap_basis": cell["district_gap_basis"],
                "gap_pct_of_demand": cell["gap_pct_of_demand"],
                "demand_tonnes": cell["demand_tonnes"],
                "estimate_id": cell["estimate_id"],
                "gap_id": cell["gap_id"],
                "map_id": map_head["map_id"] if map_head else None,
            })
    expected[pack.LANE_SHORT_DISTRICTS] = sorted(
        short_rows, key=short_sort_key)

    stale_rows = []
    grouped: dict[tuple, list[dict]] = {}
    for share in store.list_shares(crop_year=crop_year, season=season):
        grouped.setdefault(
            (share["district_id"], share["product"]), []).append(share)
    for group in grouped.values():
        latest_date = max(s["as_of"] for s in group)
        head = head_of(
            [s for s in group if s["as_of"] == latest_date], "share_id")
        if head is None:
            continue
        row = _stale_reading(head)
        if row is not None:
            stale_rows.append(row)
    expected[pack.LANE_STALE_FIGURES] = sorted(
        stale_rows, key=stale_sort_key)

    acts = store.list_publication_acts()
    pending_rows = []
    for brief in store.list_weekly_briefs():
        state = brief_engine.publication_state(
            acts, brief_pack.KIND_BRIEF, brief["brief_id"])
        if state["status"] != "draft":
            continue
        name, counts = brief_severity(brief)
        pending_rows.append({
            "brief_id": brief["brief_id"],
            "week_start": brief["week_start"],
            "week_ending": brief["week_ending"],
            "severity": pack.BRIEF_SEVERITY[name],
            "severity_class": name,
            **counts,
        })
    pending_rows.sort(
        key=lambda r: (r["week_ending"], r["brief_id"]), reverse=True)
    pending_rows.sort(key=pending_sort_key)
    expected[pack.LANE_PENDING_BRIEFS] = pending_rows

    return [
        {"lane": lane, "title": pack.LANE_TITLES[lane],
         "rows": expected[lane]}
        for lane in pack.ROLE_LANES[role]
    ]


def verify_board(store, board_dict: dict) -> list[str]:
    """Re-derive a stored (or candidate) board lane for
    lane and compare the rows exactly, in order; recompute
    the fingerprint; re-render the page byte for byte."""
    problems: list[str] = []
    if board_dict["rules_version"] != pack.RULES_VERSION:
        return [f"board names unknown rule pack {board_dict['rules_version']}"]
    if board_dict["role"] not in pack.ROLE_LANES:
        return [f"board names unknown role {board_dict['role']!r}"]
    expected = _expected_lanes(store, board_dict)
    mine = {lane["lane"]: lane for lane in board_dict["lanes"]}
    theirs = {lane["lane"]: lane for lane in expected}
    if set(mine) != set(theirs):
        problems.append(
            f"lane set differs: stored {sorted(mine)}, "
            f"re-derived {sorted(theirs)}")
    for lane in sorted(set(mine) & set(theirs)):
        if mine[lane] != theirs[lane]:
            problems.append(
                f"lane {lane}: rows do not re-derive "
                f"(stored {len(mine[lane]['rows'])}, "
                f"re-derived {len(theirs[lane]['rows'])})")
    fingerprint = _fingerprint({
        "role": board_dict["role"],
        "scope": [board_dict["crop_year"], board_dict["season"]],
        "pack": pack.RULES_VERSION, "lanes": board_dict["lanes"],
    })
    if fingerprint != board_dict["fingerprint"]:
        problems.append("board fingerprint does not re-perform from its lanes")
    if render_board_html(board_dict) != board_dict["html"]:
        problems.append("board page does not re-render byte for byte")
    return problems


# ---------------------------------------------------------------------------
# The page — static, read-only, rendered from the artefact alone
# ---------------------------------------------------------------------------


def _alert_table(rows: list[dict]) -> str:
    if not rows:
        return '<p class="muted">No open alerts.</p>'
    out = ["<table><thead><tr><th>Series</th><th>Rule</th><th>Band</th>"
           "<th>Period</th><th>Move</th><th>Alert</th></tr></thead><tbody>"]
    for row in rows:
        out.append(
            f"<tr><td>{_esc(row['series_kind'])} {_esc(row['item'])}</td>"
            f"<td>{_esc(row['rule_id'])}</td>"
            f"<td><span class=\"chip {row['band']}\">{_esc(row['band'])}"
            f"</span></td><td>{_esc(row['period_month'])}</td>"
            f"<td>{_esc(row['figure_name'])} "
            f"{_fmt(row['figure_value'])}%</td>"
            f"<td class=\"lineage\">{_esc(row['alert_id'])}</td></tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _short_table(rows: list[dict]) -> str:
    if not rows:
        return '<p class="muted">No district is trending short.</p>'
    out = ["<table><thead><tr><th>District</th><th>Product</th>"
           "<th>Gap band</th><th>Gap % of demand</th><th>Demand (t)</th>"
           "<th>Artefacts</th></tr></thead><tbody>"]
    for row in rows:
        out.append(
            f"<tr><td>{_esc(row['district_name'])}</td>"
            f"<td>{_esc(row['product'])}</td>"
            f"<td><span class=\"chip {row['district_gap_band']}\">"
            f"{_esc(row['district_gap_band'])}</span></td>"
            f"<td>{_fmt(row['gap_pct_of_demand'])}</td>"
            f"<td>{_fmt(row['demand_tonnes'])}</td>"
            f"<td class=\"lineage\">estimate "
            f"{_esc(row['estimate_id'] or '—')} · gap "
            f"{_esc(row['gap_id'] or '—')}</td></tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _stale_table(rows: list[dict]) -> str:
    if not rows:
        return '<p class="muted">No figure on record is stale.</p>'
    out = ["<table><thead><tr><th>District</th><th>Product</th>"
           "<th>Stale observations</th><th>Stale months</th><th>Note</th>"
           "<th>Share</th></tr></thead><tbody>"]
    for row in rows:
        out.append(
            f"<tr><td>{_esc(row['district_id'])}</td>"
            f"<td>{_esc(row['product'])}</td>"
            f"<td>{row['stale_observations']}</td>"
            f"<td>{row['stale_months']}</td>"
            f"<td>{_esc(row['headline_note'])}</td>"
            f"<td class=\"lineage\">{_esc(row['share_id'])}</td></tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _pending_table(rows: list[dict]) -> str:
    if not rows:
        return '<p class="muted">No brief is waiting for approval.</p>'
    out = ["<table><thead><tr><th>Week ending</th><th>Brief</th>"
           "<th>Severity</th><th>Carries</th></tr></thead><tbody>"]
    for row in rows:
        carries = (
            f"{row['short_gaps']} short gap(s), "
            f"{row['tight_gaps']} tight gap(s), "
            f"{row['alert_band_alerts']} alert-band alert(s), "
            f"{row['watch_band_alerts']} watch-band alert(s)")
        out.append(
            f"<tr><td>{_esc(row['week_ending'])}</td>"
            f"<td class=\"lineage\">{_esc(row['brief_id'])}</td>"
            f"<td>{_esc(row['severity_class'])}</td>"
            f"<td>{_esc(carries)}</td></tr>")
    out.append("</tbody></table>")
    return "".join(out)


_LANE_TABLES = {
    pack.LANE_OPEN_ALERTS: _alert_table,
    pack.LANE_SHORT_DISTRICTS: _short_table,
    pack.LANE_STALE_FIGURES: _stale_table,
    pack.LANE_PENDING_BRIEFS: _pending_table,
}

_LANE_NOTES = {
    pack.LANE_OPEN_ALERTS: (
        "Open means the fold of the alert's acts says open. "
        "Acknowledged and closed alerts leave this lane exactly "
        "per their derived state."),
    pack.LANE_SHORT_DISTRICTS: (
        "Districts whose composed gap band — the map's reading, "
        "re-performed from the same cells — is tight or short, "
        "worst first."),
    pack.LANE_STALE_FIGURES: (
        "Share artefacts whose own readings carry stale "
        "competitor observations, named on the artefact itself."),
    pack.LANE_PENDING_BRIEFS: (
        "Weekly briefs no publication act names yet, ranked by "
        "the severity of what they carry — never by recency."),
}


def render_board_html(board_dict: dict) -> str:
    """The board's page — a pure function of the artefact,
    so a stored page re-renders byte for byte."""
    out = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>Morning board — {_esc(board_dict['role'])} — "
        "Kaveri Agro Inputs</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        "<header>",
        '<p class="lineage">Kaveri Agro Inputs · market intelligence</p>',
        f"<h1>Morning board — {_esc(board_dict['role'])}</h1>",
        f'<p class="muted">{_esc(board_dict["season"])} '
        f'{_esc(board_dict["crop_year"])} · as of '
        f'{_esc(board_dict["as_of"])} · built by '
        f'{_esc(board_dict["built_by"])} · board '
        f'{board_dict["board_id"]} · board pack '
        f'{board_dict["rules_version"]}. Every row re-derives '
        "from its artefacts; lanes are ranked by the packs that "
        "own their subject matter, not by recency.</p>",
        "</header>",
        "<main>",
    ]
    for lane in board_dict["lanes"]:
        out.append('<section class="panel">')
        out.append(f"<h2>{_esc(lane['title'])}</h2>")
        out.append(_LANE_TABLES[lane["lane"]](lane["rows"]))
        out.append(f'<p class="note">{_esc(_LANE_NOTES[lane["lane"]])}</p>')
        out.append("</section>")
    out += [
        "</main>",
        "<footer>",
        "<div>",
        '<div class="footer-brand">'
        '<img src="https://trida.ai/logos-rounded/trida-rounded.png" '
        'alt="Trida AI"><strong>Trida AI</strong></div>',
        '<p class="muted">Rows on this page are artefact rows '
        "re-derived before serving. The board selects and ranks; "
        "it does not compute a figure of its own.</p>",
        "</div>",
        '<div><a href="https://trida.ai/">Visit Trida AI →</a>'
        '<a href="https://github.com/tridaai">View all blueprints →</a>'
        "</div>",
        "</footer>",
        "</body>",
        "</html>",
    ]
    return "\n".join(out)
