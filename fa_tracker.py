"""MLB Free Agency Tracker.

Keeps a list of free agents in free_agents.json and shows:
  1. SIGNINGS        - big names first, then everyone else by contract value
  2. STILL AVAILABLE - who is left, big names first

A player is a BIG NAME if you flag them (--big) OR their deal is
$100M+ total or $20M+ per year.

Usage examples:
  python fa_tracker.py                                  # show the board
  python fa_tracker.py add "Michael King" --pos SP --old-team SD --big
  python fa_tracker.py sign "Michael King" --team NYY --years 5 --total 130
  python fa_tracker.py unsign "Michael King"            # undo a signing
  python fa_tracker.py big "Brandon Lowe"               # toggle big-name flag
  python fa_tracker.py remove "Brandon Lowe"
  python fa_tracker.py show --big-only                  # only the headliners
  python fa_tracker.py show --top 25                    # top 25 of each section

Ranks come from MLB Trade Rumors' Top 50; ranks 1-25 start flagged as big names.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

DATA_FILE = Path(__file__).with_name("free_agents.json")

BIG_TOTAL_M = 100   # $100M+ total contract => big name
BIG_AAV_M = 20      # $20M+ per year        => big name


# ---------- storage ----------

def load():
    if not DATA_FILE.exists():
        return []
    with DATA_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def save(players):
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(players, f, indent=1, ensure_ascii=False)


def find(players, name):
    name_l = name.lower().strip()
    exact = [p for p in players if p["name"].lower() == name_l]
    if exact:
        return exact[0]
    partial = [p for p in players if name_l in p["name"].lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        sys.exit(f"'{name}' matches several players: "
                 + ", ".join(p["name"] for p in partial))
    sys.exit(f"No player named '{name}'. Add them first with: add \"{name}\"")


# ---------- big-name logic ----------

def aav(p):
    if p.get("total_m") and p.get("years"):
        return p["total_m"] / p["years"]
    return 0


def is_big(p):
    return (p.get("big_name")
            or (p.get("total_m") or 0) >= BIG_TOTAL_M
            or aav(p) >= BIG_AAV_M)


def bigness(p):
    """Sort key: big names first, then by ranking, then by contract size,
    then major-league deals ahead of minor-league deals, then A-Z."""
    return (not is_big(p), p.get("rank") or 999, -(p.get("total_m") or 0),
            "minor league" in p.get("notes", "").lower(), p["name"])


# ---------- display ----------

def money(m):
    return f"${m:,.1f}M".replace(".0M", "M") if m else "-"


def print_signings(players, big_only, top=None):
    signed = [p for p in players if p.get("signed")]
    if big_only:
        signed = [p for p in signed if is_big(p)]
    signed.sort(key=bigness)
    if top:
        signed = signed[:top]

    print(f"\n=== SIGNINGS ({len(signed)}) " + "=" * 50)
    if not signed:
        print("  (none yet)")
        return
    print(f"  {'':3}{'Player':<22}{'Pos':<5}{'From':<6}{'To':<6}"
          f"{'Yrs':>4}{'Total':>11}{'AAV':>10}  {'Date':<11}Notes")
    for p in signed:
        star = "★" if is_big(p) else " "
        print(f"  {star}  {p['name']:<22}{p.get('pos',''):<5}"
              f"{p.get('old_team',''):<6}{p.get('new_team',''):<6}"
              f"{p.get('years') or '-':>4}{money(p.get('total_m')):>11}"
              f"{money(aav(p)):>10}  {p.get('signed_date') or '':<11}"
              f"{p.get('notes','')}")


def print_available(players, big_only, top=None):
    left = [p for p in players if not p.get("signed")]
    if big_only:
        left = [p for p in left if is_big(p)]
    left.sort(key=bigness)
    if top:
        left = left[:top]

    print(f"\n=== STILL AVAILABLE ({len(left)}) " + "=" * 43)
    if not left:
        print("  (everyone has signed!)")
        return
    print(f"  {'':3}{'Rank':<6}{'Player':<22}{'Pos':<5}{'2026 Team':<10}Notes")
    for p in left:
        star = "★" if is_big(p) else " "
        rank = p.get("rank") or "-"
        print(f"  {star}  {str(rank):<6}{p['name']:<22}{p.get('pos',''):<5}"
              f"{p.get('old_team',''):<10}{p.get('notes','')}")


def show(players, big_only=False, top=None):
    total = len(players)
    done = sum(1 for p in players if p.get("signed"))
    print(f"\nMLB FREE AGENCY TRACKER  -  {done}/{total} signed   "
          f"(★ = big name: flagged, ${BIG_TOTAL_M}M+ total, or ${BIG_AAV_M}M+ AAV)")
    print_signings(players, big_only, top)
    print_available(players, big_only, top)
    print()


# ---------- commands ----------

def cmd_add(players, a):
    if any(p["name"].lower() == a.name.lower() for p in players):
        sys.exit(f"{a.name} is already on the list.")
    players.append({
        "name": a.name, "pos": a.pos or "", "old_team": a.old_team or "",
        "rank": a.rank, "big_name": a.big, "signed": False,
        "new_team": "", "years": None, "total_m": None,
        "signed_date": None, "notes": a.notes or "",
    })
    save(players)
    print(f"Added {a.name}.")


def cmd_sign(players, a):
    p = find(players, a.name)
    p.update(signed=True, new_team=a.team, years=a.years, total_m=a.total,
             signed_date=a.date or date.today().isoformat())
    if a.notes is not None:
        p["notes"] = a.notes
    save(players)
    tag = "  ★ BIG NAME SIGNING ★" if is_big(p) else ""
    deal = f"{a.years} yr / {money(a.total)}" if a.years and a.total else "terms TBD"
    print(f"{p['name']} -> {a.team} ({deal}){tag}")


def cmd_unsign(players, a):
    p = find(players, a.name)
    p.update(signed=False, new_team="", years=None, total_m=None, signed_date=None)
    save(players)
    print(f"{p['name']} is back on the market.")


def cmd_big(players, a):
    p = find(players, a.name)
    p["big_name"] = not p.get("big_name")
    save(players)
    print(f"{p['name']} big-name flag: {'ON' if p['big_name'] else 'OFF'}")


def cmd_remove(players, a):
    p = find(players, a.name)
    players.remove(p)
    save(players)
    print(f"Removed {p['name']}.")


def main():
    ap = argparse.ArgumentParser(description="Track MLB free agency signings.")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("show", help="show the board (default)")
    s.add_argument("--big-only", action="store_true")
    s.add_argument("--top", type=int, help="only show the top N in each section")

    s = sub.add_parser("add", help="add a free agent")
    s.add_argument("name")
    s.add_argument("--pos")
    s.add_argument("--old-team")
    s.add_argument("--rank", type=int, help="your ranking (1 = best)")
    s.add_argument("--big", action="store_true", help="flag as a big name")
    s.add_argument("--notes")

    s = sub.add_parser("sign", help="record a signing")
    s.add_argument("name")
    s.add_argument("--team", required=True)
    s.add_argument("--years", type=int)
    s.add_argument("--total", type=float, help="total value in $ millions")
    s.add_argument("--date", help="YYYY-MM-DD (default today)")
    s.add_argument("--notes")

    for c in ("unsign", "big", "remove"):
        sub.add_parser(c).add_argument("name")

    a = ap.parse_args()
    players = load()
    {"add": cmd_add, "sign": cmd_sign, "unsign": cmd_unsign,
     "big": cmd_big, "remove": cmd_remove}.get(a.cmd, lambda *_: None)(players, a)
    if a.cmd in (None, "show"):
        show(players, getattr(a, "big_only", False), getattr(a, "top", None))


if __name__ == "__main__":
    # Windows consoles sometimes can't print ★ by default
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    main()
