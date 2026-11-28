"""Player salaries, contracts and team payrolls.

MLB's free data has no salaries, so they come from two places:
  1. salaries.csv - one row per player (fill it from a spreadsheet, or with
     `python fa_tracker.py salary "Name" --team TOR --years 5 --total 100 ...`)
  2. free_agents.json - this offseason's signings that have terms

Columns in salaries.csv (amounts in $ millions):
  player, team, status, start_year, years, total_m, aav_m, 2027 ... 2032, notes
Per-year columns are optional: when a year is blank, the contract's AAV is
used for every year the contract covers.
"""

import csv
from pathlib import Path

from fa_tracker import load
from live_dashboard import norm

FILE = Path(__file__).with_name("salaries.csv")
YEARS = list(range(2027, 2033))
PAYROLL_YEAR = YEARS[0]
# 2026 minimum under the 2022 CBA. That CBA expired Dec. 1, 2026, so the
# 2027 minimum isn't set yet; this is only used for labeled estimates.
LEAGUE_MIN_M = 0.78
FIELDS = (["player", "team", "status", "start_year", "years", "total_m", "aav_m"]
          + [str(y) for y in YEARS] + ["notes"])


def _num(v):
    try:
        return float(v) if str(v).strip() != "" else None
    except ValueError:
        return None


def _int(v):
    n = _num(v)
    return int(n) if n is not None else None


def _finish(c):
    """Fill AAV from total/years and total from AAV*years when one is missing."""
    if c["aav_m"] is None and c["total_m"] and c["years"]:
        c["aav_m"] = c["total_m"] / c["years"]
    if c["total_m"] is None and c["aav_m"] and c["years"]:
        c["total_m"] = c["aav_m"] * c["years"]
    return c


def read_file():
    if not FILE.exists():
        return []
    with FILE.open(encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if (r.get("player") or "").strip()]


def write_file(rows):
    with FILE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def load_contracts():
    """{normalized player name: contract dict} from salaries.csv plus the
    free agency tracker's signings (the file wins when both have a player)."""
    out = {}
    for r in read_file():
        out[norm(r["player"])] = _finish({
            "player": r["player"].strip(), "team": (r.get("team") or "").strip(),
            "status": (r.get("status") or "").strip(),
            "start_year": _int(r.get("start_year")), "years": _int(r.get("years")),
            "total_m": _num(r.get("total_m")), "aav_m": _num(r.get("aav_m")),
            "by_year": {y: _num(r.get(str(y))) for y in YEARS if _num(r.get(str(y))) is not None},
            "notes": (r.get("notes") or "").strip(), "source": "salaries.csv"})
    for p in load():
        if (p.get("signed") and p.get("years") and p.get("total_m")
                and "minor league" not in (p.get("notes") or "").lower()
                and norm(p["name"]) not in out):
            out[norm(p["name"])] = _finish({
                "player": p["name"], "team": p.get("new_team", ""),
                "status": "Free agent signing", "start_year": PAYROLL_YEAR,
                "years": p["years"], "total_m": p["total_m"], "aav_m": None,
                "by_year": {}, "notes": p.get("notes", ""), "source": "free agency tracker"})
    return out


def salary(c, year):
    """What the player is owed in `year`, or None if unknown / not under contract."""
    if not c:
        return None
    if year in c["by_year"]:
        return c["by_year"][year]
    if c["start_year"] and c["years"] and c["aav_m"] is not None \
            and c["start_year"] <= year < c["start_year"] + c["years"]:
        return c["aav_m"]
    if year == PAYROLL_YEAR and c["status"].lower().startswith("pre-arb"):
        return LEAGUE_MIN_M
    return None


def years_text(c):
    if not c or not c["years"]:
        return ""
    if c["start_year"]:
        return f"{c['years']} ({c['start_year']}–{c['start_year'] + c['years'] - 1})"
    return str(c["years"])


def payroll(player_names, contracts):
    """Payroll by year for a list of player names.

    Returns {year: committed $M}, the 2027 count of players with a salary,
    and a 2027 estimate that counts players without one at the league minimum."""
    cs = [contracts.get(norm(n)) for n in player_names]
    by_year = {y: sum(s for c in cs if (s := salary(c, y)) is not None) for y in YEARS}
    known = sum(salary(c, PAYROLL_YEAR) is not None for c in cs)
    estimate = by_year[PAYROLL_YEAR] + (len(cs) - known) * LEAGUE_MIN_M
    return {"by_year": by_year, "known": known, "players": len(cs), "estimate": estimate}
