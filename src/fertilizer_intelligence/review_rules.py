"""The review-queue rule pack — versioned data for the
estimate review & publication queue (R15, roadmap
F21-OW4).

Sign-off is where a draft becomes the company's stated
position, so the queue a reviewer works from states
its terms as data with a version:

- **Membership is a publication state, not a list
  someone keeps.** An outlook or a brief is in the
  queue exactly when no publication act names it at
  the queue's date — the same fold the publication
  gate reads, taken at the queue's as-of. Publish the
  artefact and it leaves the queue; nothing is struck
  off by hand.
- **Every item carries its change against the
  published position.** For an outlook, the diff is
  cell by cell — district by product — listing exactly
  the cells whose estimates superseded, with the old
  and new tonnage. For a brief, the diff is figure by
  figure inside each section. A family with nothing
  published yet diffs against nothing and says so:
  first publication.
- **The reviewer reviews a fingerprint.** Each item
  names the exact artefact fingerprint that a
  publication act would bind. Published must equal
  reviewed byte-identically — that equality is the
  queue's exit gate, graded in tests and evals.
- **The driver summary is three cells deep.** An
  outlook item names its three largest district by
  product cells and every district holding a partial
  estimate, so a reviewer sees the weight and the
  weakness before the detail.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# How many of an outlook's largest cells the driver
# summary names.
DRIVER_SUMMARY_CELLS = 3

# The diff basis when a family has no published head.
BASIS_FIRST_PUBLICATION = "first_publication"
BASIS_PUBLISHED_HEAD = "published_head"
