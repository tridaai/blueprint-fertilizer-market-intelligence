"""The readiness pack — versioned data for the season
readiness plan (R14, roadmap F21-PO3).

A readiness plan is a pre-season checklist for one
region, and its discipline is the point: **every line is
scored from artefacts, never self-declared.** No line is
a form someone fills in; each is a derivation over the
record, re-derived on read by a second route, and the
plan names on its face exactly which lines block it.

The four lines, and what complete means for each:

- **Outlook published.** The season's head outlook
  counts only behind its publication act (the R10 gate):
  the family's head act at the plan's date must name
  this outlook. A draft outlook — however good its
  figures — leaves the region not ready, because the
  plan a region works to is the published one.
- **Supply cover.** Every product with a supply side
  has a struck head gap, and none reads short. A short
  product is named with its gap figures. Products with
  no supply side (the agrochemicals) carry no cover
  line — the plan says which products the line covers.
- **Open risks.** Two named classes, folded at the
  plan's date: price alerts still standing open (the
  morning board's own derivation — acknowledged and
  closed alerts are not open risks), and short gaps
  whose queue item nobody has taken: its fold holds no
  assign act, so its owner is still the queue pack's
  struck default, and no close has retired it. An
  unowned short gap blocks readiness outright — a
  shortage nobody owns is the failure this plan exists
  to catch.
- **Field coverage.** Every district in the region has
  at least one field report for the season whose review
  state at the plan's date is confirmed — a named
  reviewer's act, not an intention. Unreviewed and
  queried reports are evidence in flight; they do not
  cover a district.

Acts are folded at the plan's as-of date throughout —
the fold of acts recorded on or before that date, the
same discipline the map's signal layer uses — so a plan
struck for a date keeps reading as it read at that date
while the record moves on around it. Membership records
(gap heads, the outlook head, the district register) are
the record's current heads, named on the plan.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# -- the lines, in the plan's stated order -----------------------------------

LINE_OUTLOOK = "outlook_published"
LINE_COVER = "supply_cover"
LINE_RISKS = "open_risks"
LINE_FIELD = "field_coverage"

LINE_ORDER = [LINE_OUTLOOK, LINE_COVER, LINE_RISKS, LINE_FIELD]

LINE_TITLES = {
    LINE_OUTLOOK: "Demand outlook published",
    LINE_COVER: "Supply cover by product",
    LINE_RISKS: "Open risks owned",
    LINE_FIELD: "Field coverage",
}

LINE_BASIS = {
    LINE_OUTLOOK: (
        "the head season outlook and the publication acts "
        "folded at the plan's date — an outlook counts "
        "only behind its publication act"),
    LINE_COVER: (
        "the head supply gap per product with a supply "
        "side, struck for the season — a product reading "
        "short, or with no gap struck, leaves the line "
        "incomplete"),
    LINE_RISKS: (
        "alerts standing open at the plan's date (the "
        "board's derivation) and short gaps whose queue "
        "item's fold at that date holds no assign act and "
        "no close — a shortage nobody has taken"),
    LINE_FIELD: (
        "field reports for the season landed by the "
        "plan's date whose review state at that date is "
        "confirmed, per district in the region"),
}

STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE = "incomplete"
