"""MLB Free Agency Tracker.

Keeps a list of free agents in free_agents.json and shows:
  1. SIGNINGS        - big names first, then everyone else by contract value
  2. STILL AVAILABLE - who is left, big names first

A player is a BIG NAME if you flag them (--big) OR their deal is
$100M+ total or $20M+ per year.

Usage examples:
  python fa_tracker.py                                  # show the board
  python fa_tracker.py live                             # live dashboard in your browser
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
    # write to a temp file, then swap it in, so readers never see half a file
    tmp = DATA_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(players, f, indent=1, ensure_ascii=False)
    tmp.replace(DATA_FILE)


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


SIGNED_COLS = [("Player", 22, "name"), ("Pos", 5, "pos"), ("From", 6, "old_team"),
               ("To", 6, "new_team"), ("Yrs", -4, lambda p: p.get("years") or "-"),
               ("Total", -11, lambda p: money(p.get("total_m"))),
               ("AAV", -10, lambda p: money(aav(p))),
               ("  Date", 13, lambda p: "  " + (p.get("signed_date") or "")),
               ("Notes", 0, "notes")]
AVAIL_COLS = [("Rank", 6, lambda p: p.get("rank") or "-"), ("Player", 22, "name"),
              ("Pos", 5, "pos"), ("2026 Team", 10, "old_team"), ("Notes", 0, "notes")]


def print_section(title, rows, cols, empty):
    print(f"\n=== {title} ({len(rows)}) " + "=" * (60 - len(title)))
    if not rows:
        print(f"  {empty}")
        return
    fmt = lambda v, w: f"{str(v):>{-w}}" if w < 0 else f"{str(v):<{w}}"
    print("     " + "".join(fmt(h, w) for h, w, _ in cols))
    for p in rows:
        cells = (get(p) if callable(get) else p.get(get) or "" for _, _, get in cols)
        print(f"  {'★' if is_big(p) else ' '}  "
              + "".join(fmt(v, w) for v, (_, w, _) in zip(cells, cols)))


def show(players, big_only=False, top=None):
    def pick(signed):
        rows = sorted((p for p in players if bool(p.get("signed")) == signed
                       and (is_big(p) or not big_only)), key=bigness)
        return rows[:top] if top else rows

    done = sum(1 for p in players if p.get("signed"))
    print(f"\nMLB FREE AGENCY TRACKER  -  {done}/{len(players)} signed   "
          f"(★ = big name: flagged, ${BIG_TOTAL_M}M+ total, or ${BIG_AAV_M}M+ AAV)")
    print_section("SIGNINGS", pick(True), SIGNED_COLS, "(none yet)")
    print_section("STILL AVAILABLE", pick(False), AVAIL_COLS, "(everyone has signed!)")
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
    # drop notes that only describe the deal
    p["notes"] = "; ".join(n for n in p.get("notes", "").split("; ")
                           if n not in ("", "Minor league deal", "Reported, not yet official"))
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

    sub.add_parser("live", add_help=False,
                   help="start the live dashboard (same options as live_dashboard.py)")

    a, extra = ap.parse_known_args()
    if a.cmd == "live":
        import live_dashboard
        return live_dashboard.main(extra)
    if extra:
        ap.error("unrecognized arguments: " + " ".join(extra))
    players = load()
    {"add": cmd_add, "sign": cmd_sign, "unsign": cmd_unsign,
     "big": cmd_big, "remove": cmd_remove}.get(a.cmd, lambda *_: None)(players, a)
    if a.cmd in (None, "show"):
        show(players, getattr(a, "big_only", False), getattr(a, "top", None))


def running_in_streamlit():
    try:
        from streamlit import runtime
        return runtime.exists()
    except ImportError:
        return False


if __name__ == "__main__":
    if running_in_streamlit():
        # `streamlit run fa_tracker.py` (e.g. Streamlit Community Cloud)
        import streamlit_app
        streamlit_app.render()
    else:
        # Windows consoles sometimes can't print ★ by default
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
        main()
