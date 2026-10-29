"""The access rule pack — versioned data for regional
role scopes and the access audit log (R15, roadmap
F21-AS1).

Competitor intelligence is commercially sensitive, and a
regional head's remit is their region. This pack states,
as data with a version, who the desk's readers are, what
each role may see, and how a scope decision is made —
so a personnel or remit change is a new pack version,
never a code edit, and every artefact the access layer
produces names the version it was judged under.

- **Principals are a register, not a login system.**
  The desk's readers are named people with a role and a
  stated remit: a regional reader carries their regions,
  a product reader their products. A name that is not
  in the register reads as a viewer — the narrowest
  role — never as more.
- **Scope is judged per surface.** District lists are
  filtered to the reader's regions. Competitor reads —
  observations and market shares — are judged on both
  the district's region and the product: a regional
  reader sees their region, a product reader their
  products, strategy sees everything, a viewer does not
  read competitor surfaces at all.
- **Out of scope reads as absent.** A competitor
  artefact outside the reader's scope returns exactly
  what a missing artefact returns. The surface never
  confirms that the artefact exists; only the access
  log, which the reader does not read, records that a
  decision was made and what it was.
- **Every guarded decision is logged.** Competitor
  reads and export packs append an insert-only entry
  naming the principal, the surface, the target and
  the decision. Export entries reconcile one-to-one
  with export pack artefacts: a pack without its entry,
  or an entry naming no pack, is a defect the verifier
  names.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# -- roles -------------------------------------------------
ROLE_STRATEGY = "strategy"
ROLE_PRODUCT = "product"
ROLE_REGIONAL = "regional"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_STRATEGY, ROLE_PRODUCT, ROLE_REGIONAL,
         ROLE_VIEWER)

# -- surfaces the guard judges ------------------------------
SURFACE_DISTRICT_LIST = "district_list"
SURFACE_COMPETITOR = "competitor_read"
SURFACE_EXPORT = "export_pack"
SURFACES = (SURFACE_DISTRICT_LIST, SURFACE_COMPETITOR,
            SURFACE_EXPORT)

# -- decisions ----------------------------------------------
DECISION_ALLOWED = "allowed"
DECISION_HIDDEN = "hidden"
DECISION_REFUSED = "refused"
DECISIONS = (DECISION_ALLOWED, DECISION_HIDDEN,
             DECISION_REFUSED)

# -- the principal register ---------------------------------
# The desk's named readers and their remits. Regions are
# the district register's region names; products are the
# tracked product codes. A strategy reader's remit is
# the whole book, stated as empty scope lists judged by
# the role, not by enumeration.
PRINCIPALS = {
    "A. Rao": {"role": ROLE_STRATEGY, "regions": [],
               "products": []},
    "R. Menon": {"role": ROLE_PRODUCT, "regions": [],
                 "products": ["UREA"]},
    "S. Iyer": {"role": ROLE_PRODUCT, "regions": [],
                "products": ["DAP", "NPK_10_26_26"]},
    "K. Bhatt": {"role": ROLE_PRODUCT, "regions": [],
                 "products": ["MOP"]},
    "L. D'Souza": {"role": ROLE_PRODUCT, "regions": [],
                   "products": ["GLYPHOSATE", "CHLORPYRIFOS"]},
    "D. Verma": {"role": ROLE_REGIONAL, "regions": ["north"],
                 "products": []},
    "P. Nair": {"role": ROLE_REGIONAL, "regions": ["south"],
                "products": []},
    "Guest Viewer": {"role": ROLE_VIEWER, "regions": [],
                     "products": []},
}

# What an unregistered name resolves to: the narrowest
# role and no remit, stated here so the default is a
# decision in the pack, not an accident in the code.
UNREGISTERED = {"role": ROLE_VIEWER, "regions": [],
                "products": []}
