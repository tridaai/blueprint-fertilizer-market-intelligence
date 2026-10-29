"""The rollup pack — versioned data for the regional
rollups and territory packs (R14, roadmap F21-DR3).

The composition rules, stated plainly because a rollup is
where quiet invention would do the most damage:

- **A rollup is a sum of named members, and nothing
  else.** The members are the head season outlook's own
  member estimates — the same artefacts the outlook sums
  for its product rollups. The regional rollup groups
  those members by their district's region and sums them
  district → region → national. It never re-estimates,
  never re-derives a figure from raw facts by a second
  method, and never reads an estimate the outlook does
  not name.
- **The identity holds to the tonne at every level.** A
  region's total is the sum of its member lines; the
  national total is the sum of the region totals and of
  the member lines directly — two routes, one answer,
  graded by the verifier.
- **Partial and missing are named, never absorbed.** A
  member estimate struck partial makes its district a
  named partial district in its region and product. A
  tracked district with no member estimate in the
  outlook is named as missing — it contributes nothing,
  and the rollup never prints a silent zero in its
  place. Either condition makes the product's rollup
  partial, and the rollup's own status partial with it.
- **The gap position is carried by reference.** A
  supply gap is struck for the whole tracked market, one
  per product and season — there are no district gap
  figures to sum, and summing the market gap across
  regions would fabricate them. The rollup carries the
  head gap artefact's own figures, named as that
  artefact, and where the gap was struck from this
  rollup's outlook the verifier grades the cross-check:
  the gap's demand figure equals the rollup's national
  total for the product.
- **Territory packs state the rollup's figures.** A
  region's territory pack is rendered from the rollup
  artefact — the region's member lines, its region
  subtotal beside the national total, and the product
  gap positions — so a pack figure that differed from
  the rollup would be a defect the pack verifier names,
  not a second opinion.
"""

from __future__ import annotations

from .map_rules import REGION_ORDER  # noqa: F401  (re-exported: one order)

RULES_VERSION = "2026.10.1"

# -- levels -----------------------------------------------------------------

LEVEL_DISTRICT = "district"
LEVEL_REGION = "region"
LEVEL_NATIONAL = "national"

# -- statuses -----------------------------------------------------------------

STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"

# The gap line's demand basis, stated on the rollup's face:
# whether the head gap was struck from this rollup's own
# outlook (its demand figure is then graded against the
# rollup's national total) or from an earlier outlook
# (carried as reference, its demand figure is that older
# outlook's, and the rollup says so).
GAP_BASIS_THIS_OUTLOOK = "this_outlook"
GAP_BASIS_EARLIER_OUTLOOK = "earlier_outlook"
