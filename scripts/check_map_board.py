"""Map & board checker: re-perform every figure the
market surfaces show.

Stands the service up on a throwaway SQLite store, builds
the district map for both seasons, one morning board per
role, and the gap action queue — then re-performs
everything those surfaces show, from the artefacts, by
the verifiers' second routes:

- every map cell and layer value re-performs, and each
  map page re-renders byte for byte;
- every board lane re-derives row for row, in order, and
  each board page re-renders byte for byte;
- the queue's membership is exactly the non-comfortable
  gap heads, and every item's fold re-derives;
- no page carries a form, a POST or any control verb —
  the surfaces are read-only by construction.

Exits 0 when every check passes, 1 otherwise.

Usage: uv run python scripts/check_map_board.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPO = Path(__file__).resolve().parents[1]

FORBIDDEN = ("<form", "method=", "post ", "type=\"submit\"")


def main() -> int:
    from fertilizer_intelligence import board_rules
    from fertilizer_intelligence.config import Settings
    from fertilizer_intelligence.service import MarketService

    tmp = Path(tempfile.mkdtemp(prefix="fert-mapcheck-"))
    settings = Settings(
        database_url=None,
        sqlite_path=tmp / "fert.db",
        migrations_dir=REPO / "migrations",
        model_profile="offline",
        log_level="WARNING",
    )
    service = MarketService(settings)
    problems: list[str] = []

    maps = []
    for season in ("kharif", "rabi"):
        maps.append(service.market_map(
            "2025-26", season, "check desk", "2026-03-01"))
    for map_row in maps:
        result = service.verify_map(map_row["map_id"])
        if not result["verified"]:
            problems.extend(
                f"map {map_row['map_id']}: {p}"
                for p in result["problems"])
        for token in FORBIDDEN:
            if token in map_row["html"].lower():
                problems.append(
                    f"map {map_row['map_id']}: page carries a "
                    f"forbidden control marker {token!r}")
        partial = [c for c in map_row["cells"]
                   if c["data_state"] == "partial"]
        for cell in partial:
            marker = f"{cell['product']}/{cell['district_id']}"
            if "partial data" not in map_row["html"]:
                problems.append(f"map: partial cell {marker} is not "
                                "badged on the page")

    boards = []
    for role in board_rules.ROLES:
        boards.append(service.morning_board(
            role, "2025-26", "kharif", "check desk", "2026-03-01"))
    for board in boards:
        result = service.verify_board(board["board_id"])
        if not result["verified"]:
            problems.extend(
                f"board {board['board_id']}: {p}"
                for p in result["problems"])
        for token in FORBIDDEN:
            if token in board["html"].lower():
                problems.append(
                    f"board {board['board_id']}: page carries a "
                    f"forbidden control marker {token!r}")

    queue = service.gap_queue("2026-03-01")
    result = service.verify_queue("2026-03-01")
    if not result["verified"]:
        problems.extend(f"queue: {p}" for p in result["problems"])
    if not queue:
        problems.append("queue: no items — the planted short gaps "
                        "should put items on the queue")

    if problems:
        print("MAP/BOARD CHECK: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"MAP/BOARD CHECK: PASS "
          f"({len(maps)} maps, {len(boards)} boards, "
          f"{len(queue)} queue items re-performed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
