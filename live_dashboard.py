"""Live MLB Free Agency Dashboard.

    python live_dashboard.py              opens http://localhost:8000
    python live_dashboard.py --poll 5     check every 5 minutes (default 0.5 = 30 seconds)
    python live_dashboard.py --no-news    official signings only

Three ways a signing reaches the board, each with a pop-up:
  * MLB official  - statsapi.mlb.com "Signed as Free Agent" transactions
  * Reported      - MLB Trade Rumors headlines like "Mets, Tarik Skubal Agree
                    To Nine-Year Deal" (team + terms parsed from the story).
                    Tagged "Reported, not yet official" until MLB confirms.
  * Manual        - anything you change with `python fa_tracker.py sign ...`
"""

import argparse
import html
import json
import re
import sys
import threading
import time
import unicodedata
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fa_tracker import DATA_FILE, aav, bigness, is_big, load, save

HERE = Path(__file__).parent
PAGE = HERE / "dashboard.html"
EVENTS_FILE = HERE / "signing_events.json"

MLB_FEED = "https://statsapi.mlb.com/api/v1/transactions?sportId=1&startDate=2026-11-01&endDate={today}"
NEWS_FEED = "https://www.mlbtraderumors.com/feed"
REPORTED = "Reported, not yet official"
MINORS = "Minor league deal"
FILE_CHECK_SECONDS = 3

TEAMS = {  # nickname -> abbreviation (matches headlines and MLB team names)
    "Angels": "LAA", "Astros": "HOU", "Athletics": "ATH", "A's": "ATH",
    "Blue Jays": "TOR", "Braves": "ATL", "Brewers": "MIL", "Cardinals": "STL",
    "Cubs": "CHC", "Diamondbacks": "ARI", "D-backs": "ARI", "Dodgers": "LAD",
    "Giants": "SF", "Guardians": "CLE", "Mariners": "SEA", "Marlins": "MIA",
    "Mets": "NYM", "Nationals": "WSH", "Orioles": "BAL", "Padres": "SD",
    "Phillies": "PHI", "Pirates": "PIT", "Rangers": "TEX", "Rays": "TB",
    "Red Sox": "BOS", "Reds": "CIN", "Rockies": "COL", "Royals": "KC",
    "Tigers": "DET", "Twins": "MIN", "White Sox": "CWS", "Yankees": "NYY",
}
# A headline counts only if it says a deal happened and isn't just a rumor.
DEAL_WORDS = re.compile(r"\b(sign|signs|re-sign|re-signs|agree|agrees|signing)\b", re.I)
RUMOR_WORDS = re.compile(
    r"\b(rumou?rs?|interest|interested|pursu\w*|talks?|discuss\w*|asking|seeking|"
    r"nearing|close to|expected|could|would|might|likely|considering|"
    r"yet to|not|won't|unlikely|extension|option|offer|targets?|eyeing|linked|"
    r"chat|mailbag|poll|predictions?|tracker|recap)\b", re.I)
TERMS_RE = re.compile(r"\b(\w+)[- ]years?,?\s*\$([\d.]+)\s*(MM|M|million|B|billion)", re.I)
NUM_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen".split())}
MINORS_RE = re.compile(r"minor[s -]league|minors contract", re.I)

# Shared across code reloads. Streamlit Cloud re-imports this module after a
# push without restarting the process; keeping the lock and state on `sys`
# means old and new code never run two checkers that overwrite each other.
shared = sys.__dict__.setdefault("_fa_tracker_shared", {})
lock = shared.setdefault("lock", threading.Lock())
state = shared.setdefault("state", {
    "events": [], "seen_tx": [], "seen_news": [], "signed": None, "mtime": 0,
    "checked": {"mlb": None, "news": None}, "errors": {"mlb": None, "news": None}})
NEWS_CATCH_UP_PAGES = 4   # on startup, read ~2 days of news in case we slept


# ---------- helpers ----------

def norm(name):
    """Accent-, case- and punctuation-insensitive form of a name."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace(".", "").replace("'", "").split())


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "fa-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def find_team(text):
    """Abbreviation of the first team nickname that appears in text."""
    hits = [(text.find(n), abbr) for n, abbr in TEAMS.items() if n in text]
    return min(hits)[1] if hits else ""


def parse_terms(text):
    """'a five-year, $135MM deal' -> (5, 135.0)"""
    m = TERMS_RE.search(text)
    if not m:
        return None, None
    yrs, amount, unit = m.groups()
    yrs = int(yrs) if yrs.isdigit() else NUM_WORDS.get(yrs.lower())
    return yrs, float(amount) * (1000 if unit.lower().startswith("b") else 1)


def add_note(p, note):
    notes = [n for n in p.get("notes", "").split("; ") if n]
    if note not in notes:
        p["notes"] = "; ".join(notes + [note])


def drop_note(p, note):
    p["notes"] = "; ".join(n for n in p.get("notes", "").split("; ") if n and n != note)


# ---------- events (what the page pops up) ----------

def load_events():
    if EVENTS_FILE.exists():
        saved = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
        for k in ("events", "seen_tx", "seen_news"):
            state[k] = saved.get(k, [])


def save_events():
    EVENTS_FILE.write_text(json.dumps(
        {"events": state["events"][-500:], "seen_tx": state["seen_tx"][-5000:],
         "seen_news": state["seen_news"][-2000:]}, indent=1, ensure_ascii=False),
        encoding="utf-8")


def add_event(p, source, link=None):
    state["events"].append({
        "id": f"{p['name']}|{p.get('new_team')}|{time.time()}",
        "time": datetime.now().isoformat(timespec="seconds"),
        "name": p["name"], "pos": p.get("pos", ""), "team": p.get("new_team", ""),
        "old_team": p.get("old_team", ""), "years": p.get("years"),
        "total_m": p.get("total_m"), "big": bool(is_big(p)), "rank": p.get("rank"),
        "source": source, "link": link,
    })


def record_signing(p, source, team, signed_date=None, years=None, total=None,
                   minors=False, link=None):
    p.update(signed=True, new_team=team, years=years, total_m=total,
             signed_date=signed_date or date.today().isoformat())
    if minors:
        add_note(p, MINORS)
    if source == "Reported":
        add_note(p, REPORTED)
    add_event(p, source, link)


def commit(players, changed):
    """Save only the players we changed on top of the latest file (so nothing
    written in the meantime is lost), and remember the result so the file
    watcher doesn't announce it twice."""
    mine = {p["name"]: p for p in players if p["name"] in changed}
    fresh = [mine.get(p["name"], p) for p in load()]
    save(fresh)
    state["mtime"] = DATA_FILE.stat().st_mtime
    state["signed"] = {p["name"] for p in fresh if p.get("signed")}


# ---------- sources ----------

def check_file():
    """Pop up anything newly signed by hand (fa_tracker.py sign ...)."""
    try:
        mtime = DATA_FILE.stat().st_mtime
    except FileNotFoundError:
        return
    if mtime == state["mtime"]:
        return
    state["mtime"] = mtime
    players = load()
    signed = {p["name"] for p in players if p.get("signed")}
    if state["signed"] is not None:
        for p in players:
            if p["name"] in signed - state["signed"]:
                add_event(p, "manual")
        save_events()
    state["signed"] = signed


def check_mlb():
    txs = json.loads(fetch(MLB_FEED.format(today=date.today())))["transactions"]
    players = load()
    by_name = {norm(p["name"]): p for p in players}
    seen, changed = set(state["seen_tx"]), set()
    for tx in txs:
        if tx.get("id") in seen or tx.get("typeCode") != "SFA":
            continue
        state["seen_tx"].append(tx["id"])
        p = by_name.get(norm(tx.get("person", {}).get("fullName", "")))
        if not p:
            continue
        team = find_team(tx.get("toTeam", {}).get("name", ""))
        if REPORTED in p.get("notes", ""):        # reported deal is now official
            drop_note(p, REPORTED)
            p["new_team"] = team or p["new_team"]
            changed.add(p["name"])
        elif not p.get("signed"):
            record_signing(p, "MLB official", team, tx.get("date"),
                           minors=bool(MINORS_RE.search(tx.get("description", ""))))
            changed.add(p["name"])
    if changed:
        commit(players, changed)
    # official trades: one pop-up per trade (all parts share an id)
    trades = {}
    for tx in txs:
        if tx.get("typeCode") == "TR" and tx.get("id") not in seen:
            trades.setdefault(tx["id"], []).append(tx)
    for tid, parts in trades.items():
        state["seen_tx"].append(tid)
        if parts[0].get("date", "") >= (date.today() - timedelta(days=2)).isoformat():
            add_trade_event(f"trade|{tid}", "trade", trade_text(parts), parts[0].get("date"))


# ---------- trades ----------

TRADE_WORDS = re.compile(r"\b(trade|trades|traded|acquire|acquires|acquired)\b", re.I)
NOT_A_TRADE = re.compile(
    r"\b(willing|open to|shopping|explor\w*|listening|could|would|might|may|chance|"
    r"interest|interested|rumou?rs?|talks?|discuss\w*|market|candidates?|chips?|"
    r"deadline|opener|chat|mailbag|poll|recap|nearing|close to|expected|likely|"
    r"considering|pursu\w*|targets?|eyeing|linked|haven.t|hasn.t|not)\b", re.I)


def trade_text(parts):
    """'Henry Davis PIT→ARI · Tim Tawa ARI→PIT' (or cash/considerations)."""
    bits = []
    for tx in parts:
        who = (tx.get("person") or {}).get("fullName")
        if who:
            frm = find_team((tx.get("fromTeam") or {}).get("name", "")) or "?"
            to = find_team((tx.get("toTeam") or {}).get("name", "")) or "?"
            bits.append(f"{who} {frm}→{to}")
    return " · ".join(bits) or parts[0].get("description", "Trade")


def add_trade_event(eid, kind, text, when=None, link=None):
    if any(e["id"] == eid for e in state["events"]):
        return
    state["events"].append({
        "id": eid, "kind": kind, "time": datetime.now().isoformat(timespec="seconds"),
        "date": when, "name": text, "team": "", "pos": "", "old_team": "", "big": False,
        "years": None, "total_m": None, "rank": None, "source": kind, "link": link})


def check_news(pages=1):
    items = []
    for page in range(1, pages + 1):
        url = NEWS_FEED if page == 1 else f"{NEWS_FEED}?paged={page}"
        items += list(ET.fromstring(fetch(url)).iter("item"))
    import news_contracts                 # imported here: it imports this module
    players = load()
    board = {norm(p["name"]) for p in players}
    unsigned = {}
    for p in players:
        if not p.get("signed"):
            unsigned.setdefault(norm(p["name"]), []).append(p)
    seen, changed = set(state["seen_news"]), set()
    for item in reversed(items):  # oldest first, like they happened
        guid = item.findtext("guid") or item.findtext("link")
        if guid in seen:
            continue
        state["seen_news"].append(guid)
        title = html.unescape(item.findtext("title") or "")
        # reported trades (before MLB makes them official); only fresh ones pop up
        if (TRADE_WORDS.search(title) and not NOT_A_TRADE.search(title)
                and find_team(title)):
            try:
                fresh = parsedate_to_datetime(item.findtext("pubDate")).date() >= \
                    date.today() - timedelta(days=2)
            except (TypeError, ValueError):
                fresh = True
            if fresh:
                add_trade_event(f"tradenews|{guid}", "trade_reported", title,
                                link=item.findtext("link"))
        # extensions, arbitration deals and other contracts -> salaries.csv
        try:
            recorded = news_contracts.handle(item, title, skip_names=board)
        except Exception as e:  # one odd story shouldn't stop the feed check
            recorded = None
            state["errors"]["news"] = f"Contract parse ({title[:40]}): {type(e).__name__}: {e}"
        if recorded:
            state.setdefault("contract_news", []).append({
                "time": datetime.now().isoformat(timespec="seconds"),
                "text": recorded, "link": item.findtext("link")})
        team = find_team(title)
        if not team or not DEAL_WORDS.search(title) or RUMOR_WORDS.search(title):
            continue
        t = norm(title)
        # names in the headline; skip names two free agents share
        matches = [ps[0] for n, ps in unsigned.items()
                   if len(ps) == 1 and re.search(rf"\b{re.escape(n)}\b", t)]
        if not matches:
            continue
        text = news_contracts.text_of(item)            # full story, not just the summary
        terms = news_contracts.parse_contract(text, "signing") if len(matches) == 1 else {}
        years, total = terms.get("years"), terms.get("total_m")
        for p in matches:
            record_signing(p, "Reported", team, years=years, total=total,
                           minors=bool(MINORS_RE.search(title + " " + text[:400])),
                           link=item.findtext("link"))
            unsigned.pop(norm(p["name"]), None)
            changed.add(p["name"])
    if changed:
        commit(players, changed)


def run_checks(news, catch_up=False):
    checks = [("mlb", check_mlb)]
    if news:
        checks.append(("news", lambda: check_news(NEWS_CATCH_UP_PAGES if catch_up else 1)))
    for name, check in checks:
        try:
            check()
            state["checked"][name] = datetime.now().isoformat(timespec="seconds")
            state["errors"][name] = None
        except Exception as e:
            state["errors"][name] = f"{type(e).__name__}: {e}"
    save_events()


def background(poll_minutes, news, stop=None):
    """Check the data file every few seconds and the feeds every poll_minutes.
    Exits when `stop` is set (a newer checker has taken over)."""
    stop = stop or threading.Event()
    next_feed_check, first = 0, True
    while not stop.is_set():
        try:
            with lock:
                if stop.is_set():
                    break
                check_file()
                if time.time() >= next_feed_check:
                    next_feed_check = time.time() + poll_minutes * 60
                    run_checks(news, catch_up=first)
                    first = False
        except Exception as e:  # never let one bad check stop the loop
            state["errors"]["mlb"] = f"Checker: {type(e).__name__}: {e}"
        stop.wait(FILE_CHECK_SECONDS)


def ensure_checker(poll_minutes, news):
    """Start the one background checker for this process, replacing an older
    one left behind by a code reload. Safe to call on every page load."""
    me = sys.modules[__name__]
    with shared.setdefault("start_lock", threading.Lock()):
        t = shared.get("thread")
        if t and t.is_alive() and shared.get("module") is me:
            return
        if t:
            shared["stop"].set()        # old code's checker: finish and exit
        if not shared.get("loaded"):
            load_events()
            check_file()
            shared["loaded"] = True
        stop = threading.Event()
        t = threading.Thread(target=background, args=(poll_minutes, news, stop),
                             daemon=True, name="fa-checker")
        shared.update(thread=t, stop=stop, module=me)
        t.start()


# ---------- web server ----------

def snapshot():
    players = sorted(load(), key=bigness)
    for p in players:
        p["big"] = bool(is_big(p))
        p["aav_m"] = round(aav(p), 2) or None
    errors = [f"{k.upper()}: {v}" for k, v in state["errors"].items() if v]
    return {"players": players, "events": state["events"][-100:],
            "last_check": state["checked"]["mlb"],
            "last_news_check": state["checked"]["news"],
            "last_error": "; ".join(errors) or None}


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
        if self.path != "/api/refresh":
            return self._send(b"not found", "text/plain", 404)
        with lock:
            run_checks(self.server.news)
        self._send(b'{"ok":true}', "application/json")

    def log_message(self, *args):
        pass  # keep the console quiet


def main(argv=None):
    ap = argparse.ArgumentParser(description="Live MLB free agency dashboard")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--poll", type=float, default=0.5, help="minutes between feed checks")
    ap.add_argument("--no-news", action="store_true", help="official MLB signings only")
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    a = ap.parse_args(argv)

    news = not a.no_news
    ensure_checker(a.poll, news)

    server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    server.news = news
    url = f"http://localhost:{a.port}"
    what = "MLB transactions + reported deals" if news else "MLB transactions"
    print(f"Live dashboard: {url}   (checking {what} every {a.poll:g} min)")
    print("Press Ctrl+C to stop.")
    if not a.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
