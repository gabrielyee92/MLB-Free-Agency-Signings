"""Pick up contracts from MLB Trade Rumors stories and record them in salaries.csv.

Handles:
  * Extensions        "Mets Extend A.J. Ewing", "Tigers, Troy Melton Agree To Six-Year Extension"
  * Arbitration deals "Royals, Randy Dobnak Avoid Arbitration"
  * Other signings    with major-league terms, for players not on the free agent board
                      (free agents on the board are handled by live_dashboard.check_news)

Every name is checked against MLB's player database, and for extensions and
arbitration deals the player's current team must match the headline. Rows
you entered yourself in salaries.csv are never overwritten; rows this module
wrote are marked "News:" in the notes column.
"""

import html
import json
import re
import urllib.parse

import contracts
from live_dashboard import NUM_WORDS, TEAMS, fetch, find_team, norm

CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"
API = "https://statsapi.mlb.com/api/v1"
NEWS_TAG = "News"

EXTENSION = re.compile(r"\b(extend|extends|extension)\b", re.I)
ARBITRATION = re.compile(r"\bavoids? arbitration\b", re.I)
SIGNING = re.compile(r"\b(sign|signs|re-sign|re-signs|agree|agrees)\b", re.I)
NOT_A_DEAL = re.compile(
    r"\b(rumou?rs?|interest|interested|pursu\w*|talks?|discuss\w*|asking|seeking|nearing|"
    r"close to|expected|could|would|might|likely|considering|yet to|not|haven.t|hasn.t|"
    r"won't|unlikely|mutual|open to|eyeing|linked|targets?|chat|mailbag|poll|"
    r"predictions?|tracker|recap|opener|players avoiding|decline|declines)\b", re.I)
FOREIGN = re.compile(r"\b(KBO|NPB|CPBL|LG Twins|Yomiuri|Hanshin|BayStars|Japan|Korea)\b", re.I)
MINORS = re.compile(r"minor[s -]league|minors contract|minors deal", re.I)

MONEY = r"\$([\d.]+)\s*(MM|M|million|K)\b"
NUMBER = (r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
          r"thirteen|fourteen|fifteen)")
YEARS_WORD = NUMBER + r"-year"


def _amount(num, unit):
    v = float(num)
    return v / 1000 if unit.upper() == "K" else v


def _years(word):
    return int(word) if word.isdigit() else NUM_WORDS.get(word.lower())


def text_of(item):
    raw = item.findtext(CONTENT_NS) or item.findtext("description") or ""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def classify(title):
    if FOREIGN.search(title) or NOT_A_DEAL.search(title) or not find_team(title):
        return None
    if ARBITRATION.search(title):
        return "arbitration"
    if EXTENSION.search(title):
        return "extension"
    if SIGNING.search(title):
        return "signing"
    return None


def name_from_title(title, kind):
    """Pull the player's name out of the common MLBTR headline shapes."""
    t = title.replace("’", "'")
    patterns = [
        r"^[^,]+, (?P<n>.+?) (?:Agree|Avoid|Sign|Finalize|Complete)",  # "Tigers, Troy Melton Agree To ..."
        r"\b(?:Extend|Re-Sign|Sign) (?P<n>.+?)(?: To | Through | On | For |$)",  # "Mets Extend A.J. Ewing"
        r"^(?P<n>.+?) (?:Signs|Re-Signs|Agrees)\b",                     # "Name Signs With Team"
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            name = m.group("n").strip()
            name = re.sub(r"^(?:RHP|LHP|C|1B|2B|3B|SS|OF|INF|UTIL|Right-Hander|Left-Hander)\s+", "", name)
            if "," in name or " And " in name or " & " in name:
                return None          # several players in one headline
            if any(nick in name for nick in TEAMS):
                return None          # pattern grabbed a team, not a player
            return name
    return None


def lookup(name):
    """(MLB full name, current team name) if exactly that player exists."""
    q = f"{API}/people/search?names={urllib.parse.quote(name)}&sportIds=1&hydrate=currentTeam"
    people = [p for p in json.loads(fetch(q)).get("people", []) if norm(p["fullName"]) == norm(name)]
    if len(people) != 1:
        return None, None
    p = people[0]
    return p["fullName"], p.get("currentTeam", {}).get("name", "")


def parse_contract(text, kind):
    """{'years', 'total_m', 'by_year'} from the story text (what it can find)."""
    out = {"years": None, "total_m": None, "by_year": {}}
    if kind == "arbitration":
        # a one-year salary stated up front ("agreed to a $1.35MM salary for next year");
        # later paragraphs often mention older contracts, so read only the opening
        m = re.search(MONEY, text[:400])
        if m:
            amount = _amount(m.group(1), m.group(2))
            out.update(years=1, total_m=amount, by_year={contracts.PAYROLL_YEAR: amount})
        return out
    # The player's own deal is described up top; later paragraphs compare it to
    # other players' contracts, so only the opening is read.
    lead = text[:1500]
    m = re.search(YEARS_WORD + r"\s+(?:contract|deal|extension|pact)", lead, re.I)
    if m:                                                                 # "eight-year contract extension"
        out["years"] = _years(m.group(1))
    m = re.search(MONEY + r"\s+(?:in\s+)?guarantee", lead, re.I)         # "$95MM in guaranteed money"
    if m:
        out["total_m"] = _amount(m.group(1), m.group(2))
    else:
        m = re.search(YEARS_WORD + r"[^$.]{0,40}?" + MONEY, lead, re.I)   # "six-year, $46.5MM"
        if m:
            out["total_m"] = _amount(m.group(2), m.group(3))
            out["years"] = out["years"] or _years(m.group(1))
    out["by_year"] = salary_breakdown(text[:2000])
    return out


def salary_breakdown(text):
    """Year-by-year salaries when a story spells them out, e.g. "a $1M salary in 2027 ...
    $1MM in 2028, then go up to $4.5MM, $7.5MM, $11MM, and $18MM through 2032"."""
    years = {}
    for m in re.finditer(MONEY + r"(?:\s+salary)?\s+in\s+(20\d\d)", text):
        years[int(m.group(3))] = _amount(m.group(1), m.group(2))
    for m in re.finditer(r"((?:\$[\d.]+\s*(?:MM|M|million|K)\b,?\s*(?:and\s+)?){2,})through (20\d\d)", text):
        amounts = [_amount(a, u) for a, u in re.findall(MONEY, m.group(1))]
        last = int(m.group(2))
        for i, a in enumerate(reversed(amounts)):
            years.setdefault(last - i, a)
    return {y: v for y, v in years.items() if y in contracts.YEARS}


def start_year(text):
    """First season of the deal when the story says so ("covering the 2028 through 2032
    seasons"), otherwise next season."""
    m = re.search(r"(?:covering|covers) (?:the )?(20\d\d)(?:-| through | to )", text)
    if m and int(m.group(1)) >= contracts.PAYROLL_YEAR:
        return int(m.group(1))
    return contracts.PAYROLL_YEAR


def backfill(pages=20):
    """Read `pages` pages of MLB Trade Rumors (~15 stories each, about half a day)
    and record every contract found. Returns what was recorded."""
    import time
    import xml.etree.ElementTree as ET
    from live_dashboard import NEWS_FEED, load
    board = {norm(p["name"]) for p in load()}
    found = []
    for page in range(1, pages + 1):
        url = NEWS_FEED if page == 1 else f"{NEWS_FEED}?paged={page}"
        for item in reversed(list(ET.fromstring(fetch(url)).iter("item"))):
            title = html.unescape(item.findtext("title") or "")
            if r := handle(item, title, board):
                found.append(r)
        time.sleep(0.5)          # be gentle with the site
    return found


def handle(item, title, skip_names=()):
    """Record a contract from one story. Returns a short description, or None."""
    kind = classify(title)
    if not kind:
        return None
    name = name_from_title(title, kind)
    if not name or norm(name) in skip_names:
        return None
    text = text_of(item)
    if kind == "signing" and MINORS.search(title + " " + text[:400]):
        return None
    terms = parse_contract(text, kind)
    if not terms["total_m"] and not terms["by_year"]:
        return None                       # nothing worth recording
    full, current = lookup(name)
    if not full:
        return None
    team = find_team(title)
    if kind != "signing" and find_team(current or "") != team:
        return None                       # e.g. a KBO "Twins" story about a former MLB player
    rows = contracts.read_file()
    row = next((r for r in rows if norm(r["player"]) == norm(full)), None)
    if row and not (row.get("notes") or "").startswith(NEWS_TAG):
        return None                       # never overwrite a row entered by hand
    if row is None:
        row = {"player": full}
        rows.append(row)
    status = {"extension": "Guaranteed (extension)", "arbitration": "Arbitration",
              "signing": "Guaranteed"}[kind]
    row.update({"team": team, "status": status,
                "start_year": start_year(text) if kind != "arbitration" else contracts.PAYROLL_YEAR,
                "years": terms["years"] or "", "total_m": terms["total_m"] or "", "aav_m": "",
                "notes": f"{NEWS_TAG}: {title}"})
    for y in contracts.YEARS:
        row[str(y)] = terms["by_year"].get(y, "") if terms["by_year"] else row.get(str(y), "")
    contracts.write_file(rows)
    deal = (f"{terms['years']} yr / ${terms['total_m']:g}M" if terms["years"] and terms["total_m"]
            else f"${terms['total_m']:g}M" if terms["total_m"] else "")
    return f"{full} ({team}) {kind}: {deal}"
