"""The brief pack: the versioned rules the weekly brief,
the report packs and the publication gate are built under
(R10, roadmap F21-DR2 + F21-CA1).

Like every pack in this system, the rules are data stated
here, in one place:

- the brief's **sections**, in order, each with the basis
  statement printed on its face — a brief section never
  presents a figure without saying what it was struck from;
- the **season scope rule**: which (crop year, season) a
  week's brief speaks about, under the unique-attribution
  rule the packs share — a month belongs to the season it
  opens (November is rabi's, never kharif's);
- the **alert headline rule**: which of an alert's recorded
  figures the brief headlines;
- the **report pack tables**: the columns each pack file
  carries, stated per pack kind, and the crop-year rule the
  packs cover;
- the **publication kinds**: the artefact kinds a named
  publication act may publish, and the family each act
  belongs to — a family's acts form one supersedes chain,
  and the family's current published artefact is its head
  act's target.
"""

from __future__ import annotations

from datetime import date, timedelta

from .generator import CROP_YEARS

RULES_VERSION = "2026.10.1"

# -- the week -------------------------------------------------------------
# A brief is struck for a stated week: the seven days ending
# on its week-ending date. The brief's as-of is its
# week-ending date unless the desk states another.

WEEK_DAYS = 7


def week_start_for(week_ending: str) -> str:
    """The first day of the brief's week: six days before
    its week-ending date."""
    end = date.fromisoformat(week_ending)
    return (end - timedelta(days=WEEK_DAYS - 1)).isoformat()


# -- the season scope rule -------------------------------------------------
# Season windows follow the demand pack: kharif opens in
# June of the crop year's first calendar year, rabi opens
# that November and runs to the following April. A month
# belongs to the season it opens: November opens rabi, so
# November is rabi's month even though kharif's six-month
# window also reaches it.


def _window(crop_year: str, season: str) -> tuple[str, str]:
    first_year = int(crop_year[:4])
    if season == "kharif":
        return f"{first_year:04d}-06", f"{first_year:04d}-11"
    return f"{first_year:04d}-11", f"{first_year + 1:04d}-04"


def season_windows() -> list[dict]:
    """Every tracked season window, rabi listed before
    kharif inside a crop year so the unique-attribution
    rule (November is rabi's) falls out of the order."""
    out = []
    for crop_year in CROP_YEARS:
        for season in ("rabi", "kharif"):
            start, end = _window(crop_year, season)
            out.append({
                "crop_year": crop_year, "season": season,
                "start": start, "end": end,
            })
    return out


def season_scope_for_month(month: str) -> dict:
    """The (crop year, season) a brief for a week in
    ``month`` speaks about, with the note that states the
    reading on the brief's face:

    - the season whose window contains the month, under
      unique attribution (rabi wins November);
    - before the first tracked window: the upcoming
      season, stated as an opening position;
    - after the last tracked window closes — or in the
      gap month between a rabi close and the next kharif
      opening: the most recently closed season, stated as
      a closing position.
    """
    windows = season_windows()
    for window in windows:
        if window["start"] <= month <= window["end"]:
            return {
                "crop_year": window["crop_year"],
                "season": window["season"],
                "note": (
                    f"the week falls inside the {window['season']} "
                    f"{window['crop_year']} window "
                    f"({window['start']} to {window['end']})"),
            }
    closed = [w for w in windows if w["end"] < month]
    if closed:
        window = max(closed, key=lambda w: w["end"])
        return {
            "crop_year": window["crop_year"],
            "season": window["season"],
            "note": (
                f"the week falls after the {window['season']} "
                f"{window['crop_year']} window closed "
                f"({window['end']}); the brief states that "
                "season's closing position"),
        }
    window = min(windows, key=lambda w: w["start"])
    return {
        "crop_year": window["crop_year"],
        "season": window["season"],
        "note": (
            f"the week falls before the {window['season']} "
            f"{window['crop_year']} window opens "
            f"({window['start']}); the brief states that "
            "season's opening position"),
    }


# -- sections ---------------------------------------------------------------

SECTION_DEMAND = "demand_outlook"
SECTION_PRICES = "price_watch"
SECTION_SUPPLY = "supply_gaps"
SECTION_POLICY = "policy_events"
SECTION_SHARES = "share_movement"
SECTION_PLANNING = "planning"

SECTION_ORDER = [
    SECTION_DEMAND, SECTION_PRICES, SECTION_SUPPLY,
    SECTION_POLICY, SECTION_SHARES, SECTION_PLANNING,
]

SECTION_TITLES = {
    SECTION_DEMAND: "Demand outlook",
    SECTION_PRICES: "Price watch",
    SECTION_SUPPLY: "Supply gaps",
    SECTION_POLICY: "Policy events",
    SECTION_SHARES: "Competitor & market share",
    SECTION_PLANNING: "Planning state",
}

SECTION_BASIS = {
    SECTION_DEMAND: (
        "the head season outlook for the brief's season "
        "scope, struck at the week's end — the outlook's "
        "own status rides on its figures"),
    SECTION_PRICES: (
        "alerts fired on movements of the latest tracked "
        "price month at the week's end; acknowledgement "
        "state is a live read on the alert, never a brief "
        "figure"),
    SECTION_SUPPLY: (
        "the head supply gap per supply-side product for "
        "the brief's season scope, struck at the week's "
        "end; a head that moved against its predecessor "
        "carries the changed badge"),
    SECTION_POLICY: (
        "registered events — real, never hypothetical — "
        "whose effective window covers the week's month, "
        "with their stated effects as recorded"),
    SECTION_SHARES: (
        "per district and tracked product: the head "
        "share movement between the tracked crop years "
        "and Kaveri's headline share of the observed "
        "market at the week's end, stale exclusions "
        "badged and named"),
    SECTION_PLANNING: (
        "the current adoption per planning comparison — "
        "which fork the plan follows, or the base view; "
        "unadopted comparisons carry no figure"),
}

# -- alert headlines ---------------------------------------------------------
# An alert records its figures as fired; the brief headlines
# the first of these the alert carries.

ALERT_HEADLINE_KEYS = ["mom_pct", "baseline_pct", "cumulative_pct"]

# -- report packs --------------------------------------------------------------
# A pack covers the latest tracked crop year. A product
# pack states both seasons; a region pack states the
# season in scope at the pack's as-of (the season rule
# above).

PACK_PRODUCT = "product"
PACK_REGION = "region"
# The territory pack (R14) is rendered from the regional
# rollup artefact: its tables state the rollup's figures
# for one region — the region's member lines, its region
# subtotals beside the national totals, and the product
# gap positions the rollup carries by reference.
PACK_TERRITORY = "territory"
PACK_KINDS = [PACK_PRODUCT, PACK_REGION, PACK_TERRITORY]

PACK_TABLES = {
    PACK_PRODUCT: {
        "demand": ["district_id", "district_name", "crop_year",
                   "season", "estimate_id", "status",
                   "total_tonnes", "as_of"],
        "supply": ["product", "crop_year", "season", "gap_id",
                   "band", "gap_tonnes", "programme_cover_pct",
                   "slipped_tonnes", "as_of"],
        "prices": ["series_kind", "item", "month", "movement_id",
                   "mom_pct", "baseline_pct", "open_alerts", "band"],
    },
    PACK_REGION: {
        "demand": ["district_id", "district_name", "product",
                   "estimate_id", "status", "total_tonnes",
                   "as_of"],
        "shares": ["district_id", "district_name", "product",
                   "share_id", "status",
                   "kaveri_headline_pct", "headline_note", "as_of"],
    },
    PACK_TERRITORY: {
        "rollup": ["product", "level", "region", "rollup_id",
                   "total_tonnes", "estimate_count",
                   "partial_count", "status"],
        "districts": ["product", "district_id", "district_name",
                      "region", "estimate_id", "status",
                      "total_tonnes"],
        "gaps": ["product", "gap_id", "band", "gap_tonnes",
                 "gap_pct_of_demand", "programme_cover_pct",
                 "demand_tonnes", "demand_basis"],
    },
}

APPENDIX_NAME = "appendix.md"
MANIFEST_NAME = "manifest.json"

# -- publication ---------------------------------------------------------------
# The artefact kinds a publication act may publish, and the
# family key each published artefact belongs to. Acts in
# one family form a single supersedes chain.

KIND_BRIEF = "weekly_brief"
KIND_OUTLOOK = "season_outlook"
PUBLICATION_KINDS = [KIND_BRIEF, KIND_OUTLOOK]

BADGE_PUBLISHED = "Published"
BADGE_DRAFT = "Draft — not published"
