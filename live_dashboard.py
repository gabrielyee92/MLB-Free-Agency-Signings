"""Live MLB Free Agency Dashboard.

Run:   python live_dashboard.py            (then open http://localhost:8000)
       python live_dashboard.py --poll 2   (check MLB every 2 minutes)

What it does
  * Every few minutes it checks MLB's official transactions feed
    (statsapi.mlb.com) for "Signed as Free Agent" moves. When one matches a
    player still on the board, that player is marked signed automatically.
  * It also watches free_agents.json, so signings you enter yourself with
    `python fa_tracker.py sign ...` (for example, to add contract terms or a
    reported deal that isn't official yet) show up on the dashboard too.
  * The browser page refreshes itself and shows a pop-up for every new
    signing. Big names get a bigger gold banner.

  * It also reads MLB Trade Rumors' news feed for REPORTED deals
    ("Mets, Tarik Skubal Agree To Nine-Year Deal"), pulls the team and
    contract terms out of the story, and tags the player "Reported, not yet
    official" until MLB's feed confirms it. Turn this off with --no-news.

Headlines that are only rumors (interest, talks, nearing a deal) are ignored.
If a reported deal is wrong or missing terms, fix it with fa_tracker.py.
"""

import argparse
import html
import json
import re
import threading
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fa_tracker import DATA_FILE, aav, bigness, is_big, load, save

HERE = Path(__file__).parent
PAGE = HERE / "dashboard.html"
EVENTS_FILE = HERE / "signing_events.json"
API = "https://statsapi.mlb.com/api/v1"
OFFSEASON_START = "2026-11-01"
SIGN_CODES = {"SFA"}  # "Signed as Free Agent"
REPORTED = "Reported, not yet official"

lock = threading.Lock()
state = {"events": [], "seen_tx": [], "seen_news": [], "last_check": None,
         "last_news_check": None, "last_error": None,
         "signed_snapshot": None, "file_mtime": 0}


def norm(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace(".", "").replace("'", "").split())


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "fa-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


_teams = {}


def team_abbr(team):
    if not team:
        return ""
    if not _teams:
        try:
            data = get_json(f"{API}/teams?sportId=1")
            _teams.update({t["id"]: t["abbreviation"] for t in data["teams"]})
        except Exception:
            pass
    return _teams.get(team.get("id"), team.get("name", ""))


# ---------- events ----------

def load_events():
    if EVENTS_FILE.exists():
        saved = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
        state["events"] = saved.get("events", [])
        state["seen_tx"] = saved.get("seen_tx", [])
        state["seen_news"] = saved.get("seen_news", [])


def save_events():
    EVENTS_FILE.write_text(json.dumps(
        {"events": state["events"][-500:], "seen_tx": state["seen_tx"][-5000:],
         "seen_news": state["seen_news"][-2000:]},
        indent=1, ensure_ascii=False), encoding="utf-8")


def add_event(p, source, link=None, headline=None):
    state["events"].append({
        "id": f"{p['name']}|{p.get('new_team')}|{time.time()}",
        "time": datetime.now().isoformat(timespec="seconds"),
        "name": p["name"], "pos": p.get("pos", ""), "team": p.get("new_team", ""),
        "old_team": p.get("old_team", ""), "years": p.get("years"),
        "total_m": p.get("total_m"), "big": bool(is_big(p)),
        "rank": p.get("rank"), "notes": p.get("notes", ""), "source": source,
        "link": link, "headline": headline,
    })


# ---------- watching the JSON file (manual `fa_tracker.py sign`) ----------

def check_file():
    """Turn anything newly signed in free_agents.json into a pop-up event."""
    try:
        mtime = DATA_FILE.stat().st_mtime
    except FileNotFoundError:
        return
    if mtime == state["file_mtime"]:
        return
    state["file_mtime"] = mtime
    players = load()
    signed = {p["name"]: p for p in players if p.get("signed")}
    if state["signed_snapshot"] is not None:
        for name, p in signed.items():
            if name not in state["signed_snapshot"]:
                add_event(p, "manual")
        save_events()
    state["signed_snapshot"] = set(signed)


# ---------- polling MLB ----------

def check_mlb():
    url = (f"{API}/transactions?sportId=1&startDate={OFFSEASON_START}"
           f"&endDate={date.today().isoformat()}")
    try:
        txs = get_json(url).get("transactions", [])
    except Exception as e:
        state["last_error"] = f"{type(e).__name__}: {e}"
        return
    state["last_error"] = None
    state["last_check"] = datetime.now().isoformat(timespec="seconds")

    players = load()
    by_name = {norm(p["name"]): p for p in players}
    seen = set(state["seen_tx"])
    changed = False
    for tx in txs:
        tid = tx.get("id")
        if tid in seen or tx.get("typeCode") not in SIGN_CODES:
            continue
        seen.add(tid)
        state["seen_tx"].append(tid)
        p = by_name.get(norm(tx.get("person", {}).get("fullName", "")))
        if p and REPORTED in p.get("notes", ""):
            # a reported deal just became official: confirm team, drop the tag
            p["new_team"] = team_abbr(tx.get("toTeam")) or p.get("new_team")
            p["notes"] = "; ".join(x for x in p["notes"].split("; ") if x != REPORTED)
            changed = True
            continue
        if not p or p.get("signed"):
            continue  # not one of our free agents, or already marked signed
        desc = tx.get("description", "")
        p.update(signed=True, new_team=team_abbr(tx.get("toTeam")),
                 signed_date=tx.get("date") or date.today().isoformat())
        if "minor league" in desc.lower() and "minor league" not in p.get("notes", "").lower():
            p["notes"] = "; ".join(x for x in [p.get("notes"), "Minor league deal"] if x)
        add_event(p, "MLB official")
        changed = True
    if changed:
        save(players)
        state["file_mtime"] = DATA_FILE.stat().st_mtime
        state["signed_snapshot"] = {p["name"] for p in players if p.get("signed")}
    save_events()


# ---------- polling news for REPORTED deals ----------

NEWS_FEED = "https://www.mlbtraderumors.com/feed"

TEAMS = {  # nickname as used in headlines -> abbreviation
    "Angels": "LAA", "Astros": "HOU", "Athletics": "ATH", "A's": "ATH",
    "Blue Jays": "TOR", "Braves": "ATL", "Brewers": "MIL", "Cardinals": "STL",
    "Cubs": "CHC", "Diamondbacks": "ARI", "D-backs": "ARI", "Dodgers": "LAD",
    "Giants": "SF", "Guardians": "CLE", "Mariners": "SEA", "Marlins": "MIA",
    "Mets": "NYM", "Nationals": "WSH", "Orioles": "BAL", "Padres": "SD",
    "Phillies": "PHI", "Pirates": "PIT", "Rangers": "TEX", "Rays": "TB",
    "Red Sox": "BOS", "Reds": "CIN", "Rockies": "COL", "Royals": "KC",
    "Tigers": "DET", "Twins": "MIN", "White Sox": "CWS", "Yankees": "NYY",
}
# headline must say a deal happened...
DEAL_WORDS = re.compile(r"\b(sign|signs|re-sign|re-signs|agree|agrees|signing|to sign)\b", re.I)
# ...and must not just be a rumor about one
RUMOR_WORDS = re.compile(
    r"\b(rumou?rs?|interest|interested|pursu\w*|talks?|discuss\w*|asking|seeking|"
    r"nearing|close to|expected|could|would|might|likely|considering|"
    r"yet to|not|won't|unlikely|extension|option|offer|targets?|eyeing|linked|"
    r"chat|mailbag|poll|predictions?|tracker|recap)\b", re.I)
NUM_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen".split())}
TERMS_RE = re.compile(
    r"\b(\w+)[- ]years?,?\s*\$([\d.]+)\s*(MM|M|million|B|billion)", re.I)


def parse_terms(text):
    m = TERMS_RE.search(text)
    if not m:
        return None, None
    yrs_word, amount, unit = m.groups()
    yrs = int(yrs_word) if yrs_word.isdigit() else NUM_WORDS.get(yrs_word.lower())
    total = float(amount) * (1000 if unit.lower().startswith("b") else 1)
    return yrs, total


def find_team(title):
    hits = [(title.find(n), abbr) for n, abbr in TEAMS.items() if n in title]
    hits = [h for h in hits if h[0] >= 0]
    return min(hits)[1] if hits else ""


def strip_html(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def check_news():
    try:
        req = urllib.request.Request(NEWS_FEED, headers={"User-Agent": "fa-tracker/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            root = ET.fromstring(r.read())
    except Exception as e:
        state["last_error"] = f"News feed: {type(e).__name__}: {e}"
        return
    state["last_news_check"] = datetime.now().isoformat(timespec="seconds")

    players = load()
    unsigned = [(norm(p["name"]), p) for p in players if not p.get("signed")]
    seen = set(state["seen_news"])
    changed = False
    for item in root.iter("item"):
        guid = item.findtext("guid") or item.findtext("link")
        if guid in seen:
            continue
        seen.add(guid)
        state["seen_news"].append(guid)
        title = html.unescape(item.findtext("title") or "")
        if not DEAL_WORDS.search(title) or RUMOR_WORDS.search(title):
            continue
        t_norm = norm(title)
        hit_names = [n for n, p in unsigned if re.search(rf"\b{re.escape(n)}\b", t_norm)]
        # skip names shared by two free agents (e.g. two "Luis Garcia"s)
        matches = [p for n, p in unsigned if n in hit_names and hit_names.count(n) == 1]
        team = find_team(title)
        if not matches or not team:
            continue
        desc = strip_html(item.findtext("description"))
        # contract terms only when the headline is about one player
        yrs, total = parse_terms(desc) if len(matches) == 1 else (None, None)
        minors = re.search(r"minor[s -]league|minors contract", title + " " + desc, re.I)
        for p in matches:
            notes = [p.get("notes")] if p.get("notes") else []
            if minors:
                notes.append("Minor league deal")
            notes.append(REPORTED)
            p.update(signed=True, new_team=team, years=yrs, total_m=total,
                     signed_date=date.today().isoformat(), notes="; ".join(notes))
            add_event(p, "Reported", link=item.findtext("link"), headline=title)
        unsigned = [(n, q) for n, q in unsigned if q not in matches]
        changed = True
    if changed:
        save(players)
        state["file_mtime"] = DATA_FILE.stat().st_mtime
        state["signed_snapshot"] = {p["name"] for p in players if p.get("signed")}
    save_events()


def poller(minutes, news):
    while True:
        with lock:
            check_mlb()
            if news:
                check_news()
        time.sleep(minutes * 60)


def file_watcher():
    while True:
        with lock:
            check_file()
        time.sleep(3)


# ---------- web server ----------

def snapshot():
    players = sorted(load(), key=bigness)
    for p in players:
        p["big"] = bool(is_big(p))
        p["aav_m"] = round(aav(p), 2) if aav(p) else None
    return {"players": players, "events": state["events"][-100:],
            "last_check": state["last_check"], "last_error": state["last_error"],
            "last_news_check": state["last_news_check"]}


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path.startswith("/api/state"):
            with lock:
                body = json.dumps(snapshot(), ensure_ascii=False).encode("utf-8")
            self._send(body, "application/json; charset=utf-8")
        else:
            self._send(b"not found", "text/plain", 404)

    def do_POST(self):
        if self.path == "/api/refresh":
            with lock:
                check_mlb()
                if self.server.news:
                    check_news()
            self._send(b'{"ok":true}', "application/json")
        else:
            self._send(b"not found", "text/plain", 404)

    def log_message(self, *args):
        pass  # keep the console quiet


def main():
    ap = argparse.ArgumentParser(description="Live MLB free agency dashboard")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--poll", type=float, default=5, help="minutes between checks")
    ap.add_argument("--no-news", action="store_true",
                    help="official MLB signings only; skip reported deals")
    a = ap.parse_args()

    load_events()
    check_file()
    news = not a.no_news
    threading.Thread(target=poller, args=(a.poll, news), daemon=True).start()
    threading.Thread(target=file_watcher, daemon=True).start()

    what = "MLB transactions + reported deals" if news else "MLB transactions"
    print(f"Live dashboard: http://localhost:{a.port}   (checking {what} every {a.poll:g} min)")
    print("Press Ctrl+C to stop.")
    server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    server.news = news
    server.serve_forever()


if __name__ == "__main__":
    main()
