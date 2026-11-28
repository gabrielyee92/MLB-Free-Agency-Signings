"""Import MLB team payroll totals by season from The Baseball Cube.

    python payroll_history.py               # all seasons 1985 - last season
    python payroll_history.py 2026          # just one season (e.g. to refresh it)

Writes payroll_history.csv (team totals) and top_salaries.csv (the ~100
highest salaries listed on the newest season's page). The Baseball Cube's FAQ allows
using parts of its data on another site with a reference back to it; the app
credits and links it wherever these numbers appear. Pages are read one at a
time, 10 seconds apart, as its robots.txt asks of crawlers. This runs on your
computer, not on the website.
"""

import csv
import html
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

from live_dashboard import TEAMS

FILE = Path(__file__).with_name("payroll_history.csv")
SOURCE = "https://www.thebaseballcube.com/content/payroll_year/{year}/"
FIELDS = ["year", "team", "abbr", "payroll", "wins", "losses", "top_salary"]
TOP_FILE = Path(__file__).with_name("top_salaries.csv")
TOP_FIELDS = ["year", "rank", "player", "team", "abbr", "salary"]
FIRST_YEAR = 1985
DELAY_SECONDS = 10

# Old names -> today's franchise
ALIASES = {"Expos": "WSH", "Devil Rays": "TB", "Indians": "CLE", "Colt": "HOU"}


def franchise(team_name):
    for nick, abbr in list(ALIASES.items()) + list(TEAMS.items()):
        if nick in team_name:
            return abbr
    return ""


def fetch_page(year):
    req = urllib.request.Request(SOURCE.format(year=year), headers={"User-Agent": "fa-tracker/1.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def _cells(tr):
    return [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
            for c in re.findall(r"<t[hd].*?</t[hd]>", tr, re.S | re.I)]


def top_salaries(page, year):
    """The page's list of the season's highest individual salaries."""
    table = next((t for t in re.findall(r"<table.*?</table>", page, re.S | re.I)
                  if re.search(r">\s*salary\s*<", t, re.I) and "team payroll" not in t.lower()), None)
    out = []
    for tr in re.findall(r"<tr.*?</tr>", table or "", re.S | re.I):
        c = _cells(tr)
        if len(c) == 4 and c[0].isdigit() and c[3].replace(",", "").isdigit():
            out.append({"year": year, "rank": int(c[0]), "player": c[1], "team": c[2],
                        "abbr": franchise(c[2]), "salary": int(c[3].replace(",", ""))})
    return out


def read_top():
    if not TOP_FILE.exists():
        return []
    with TOP_FILE.open(encoding="utf-8", newline="") as f:
        return [dict(r, year=int(r["year"]), rank=int(r["rank"]), salary=int(r["salary"]))
                for r in csv.DictReader(f)]


def fetch_year(year, page=None):
    page = page or fetch_page(year)
    table = next((t for t in re.findall(r"<table.*?</table>", page, re.S | re.I)
                  if "team payroll" in t.lower()), None)
    if not table:
        return []
    rows = []
    for tr in re.findall(r"<tr.*?</tr>", table, re.S | re.I):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[hd].*?</t[hd]>", tr, re.S | re.I)]
        if len(cells) < 13 or not cells[0].isdigit():
            continue
        payroll = cells[5].replace(",", "")
        if not payroll.isdigit():
            continue
        rows.append({"year": int(cells[0]), "team": cells[1], "abbr": franchise(cells[1]),
                     "payroll": int(payroll), "wins": cells[6], "losses": cells[7],
                     "top_salary": re.sub(r"\s*\(\d+\)$", "", cells[12])})
    return rows


def read():
    if not FILE.exists():
        return []
    with FILE.open(encoding="utf-8", newline="") as f:
        return [dict(r, year=int(r["year"]), payroll=int(r["payroll"])) for r in csv.DictReader(f)]


def write(rows):
    rows = sorted(rows, key=lambda r: (r["year"], -r["payroll"]))
    with FILE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def main(years):
    have = [r for r in read() if r["year"] not in years]
    for i, year in enumerate(years):
        if i:
            time.sleep(DELAY_SECONDS)
        page = fetch_page(year)
        got = fetch_year(year, page)
        print(f"{year}: {len(got)} teams", flush=True)
        have += got
        write(have)          # save as we go
        if year == max(years) and (top := top_salaries(page, year)):
            with TOP_FILE.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=TOP_FIELDS)
                w.writeheader()
                w.writerows(top)
            print(f"{year}: {len(top)} top salaries -> {TOP_FILE.name}", flush=True)
    print(f"Saved {FILE.name}: {len(read())} team-seasons")


if __name__ == "__main__":
    last = date.today().year if date.today().month >= 4 else date.today().year - 1
    main([int(a) for a in sys.argv[1:]] or list(range(FIRST_YEAR, last + 1)))
