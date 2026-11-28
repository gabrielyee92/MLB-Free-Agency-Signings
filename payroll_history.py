"""Import MLB team payroll totals by season from The Baseball Cube.

    python payroll_history.py               # all seasons 1985 - last season
    python payroll_history.py 2026          # just one season (e.g. to refresh it)

Writes payroll_history.csv (team totals only). The Baseball Cube's FAQ allows
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
FIRST_YEAR = 1985
DELAY_SECONDS = 10

# Old names -> today's franchise
ALIASES = {"Expos": "WSH", "Devil Rays": "TB", "Indians": "CLE", "Colt": "HOU"}


def franchise(team_name):
    for nick, abbr in list(ALIASES.items()) + list(TEAMS.items()):
        if nick in team_name:
            return abbr
    return ""


def fetch_year(year):
    req = urllib.request.Request(SOURCE.format(year=year), headers={"User-Agent": "fa-tracker/1.0"})
    page = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
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
        got = fetch_year(year)
        print(f"{year}: {len(got)} teams", flush=True)
        have += got
        write(have)          # save as we go
    print(f"Saved {FILE.name}: {len(read())} team-seasons")


if __name__ == "__main__":
    last = date.today().year if date.today().month >= 4 else date.today().year - 1
    main([int(a) for a in sys.argv[1:]] or list(range(FIRST_YEAR, last + 1)))
