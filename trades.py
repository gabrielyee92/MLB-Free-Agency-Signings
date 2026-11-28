"""Trades from MLB's official transaction feed, with simple fit/impact analysis.

For each trade:
  * the players (and cash / considerations) moving each way
  * each player's stats: last season in MLB, or in the minors when he has
    little MLB time
  * fit with the new team: how he compares with the new team's players at his
    position (OPS for hitters, ERA for pitchers)
  * impact on the old team: who is next in line there, salary cleared

These are comparisons of last season's stats, not projections.
"""

import json
from datetime import date

import rosters
from live_dashboard import fetch, find_team, norm

API = "https://statsapi.mlb.com/api/v1"
OFFSEASON_START = "2026-11-01"
MIN_PA, MIN_IP, MIN_IP_SP = 100, 20, 60   # enough MLB playing time to compare
OF = {"LF", "CF", "RF", "OF"}


def _get(path):
    return json.loads(fetch(f"{API}/{path}"))


# ---------- the trades ----------

def recent_trades(since=None):
    """Trades since `since` (default: Jan. 1 of the latest season, so the trade
    deadline is included), newest first, grouped by MLB's transaction id."""
    since = since or f"{rosters.stats_season()}-01-01"
    q = f"transactions?sportId=1&startDate={since}&endDate={date.today().isoformat()}"
    by_id = {}
    for tx in _get(q).get("transactions", []):
        if tx.get("typeCode") != "TR":
            continue
        t = by_id.setdefault(tx["id"], {"id": tx["id"], "date": tx.get("date", ""),
                                        "description": tx.get("description", ""),
                                        "teams": {}, "moves": []})
        frm, to = tx.get("fromTeam") or {}, tx.get("toTeam") or {}
        for team in (frm, to):
            if team.get("id"):
                t["teams"][team["id"]] = team.get("name", "")
        person = tx.get("person")
        if person:
            t["moves"].append({"id": person["id"], "name": person["fullName"],
                               "from_id": frm.get("id"), "from": frm.get("name", ""),
                               "to_id": to.get("id"), "to": to.get("name", "")})
    trades = [t for t in by_id.values() if t["moves"]]
    start, end, _ = rosters.season_dates()
    for t in trades:
        d = date.fromisoformat(t["date"][:10]) if t["date"] else date.today()
        t["period"] = (f"{end.year} regular season" if start <= d <= end
                       else f"{end.year}-{(end.year + 1) % 100:02d} offseason" if d > end
                       else f"{end.year - 1}-{end.year % 100:02d} offseason")
    return sorted(trades, key=lambda t: (t["date"], t["id"]), reverse=True)


def players(ids, season=None):
    """{id: row} with MLB season stats, minor-league stats, position and age."""
    if not ids:
        return {}
    season = season or rosters.stats_season()
    q = (f"people?personIds={','.join(map(str, ids))}&hydrate=currentTeam,stats(type=season,"
         f"season={season},group=[hitting,pitching])")
    out = {}
    for p in _get(q).get("people", []):
        row = rosters._row(p, p.get("primaryPosition", {}).get("abbreviation", ""), "", season)
        row["current_team"] = (p.get("currentTeam") or {}).get("name", "")
        out[p["id"]] = row
    milb = rosters.minor_league_stats(list(out), season)
    for pid, row in out.items():
        row["milb"] = milb.get(pid, {})
    return out


# ---------- classifying a player ----------

def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ip(v):
    """'75.2' innings = 75 and 2/3."""
    x = _f(v)
    if x is None:
        return 0.0
    whole = int(x)
    return whole + round((x - whole) * 10) / 3


def role(r):
    """Position group used for comparisons: C, 1B, 2B, 3B, SS, OF, DH, SP or RP."""
    if r["pos"] in ("P", "SP", "RP") or (r["pos"] == "TWP" and _ip(r["pitching"].get("inningsPitched")) > 30):
        st = r["pitching"] if r["pitching"] else r.get("milb", {}).get("pitching", {})
        g, gs = int(st.get("gamesPlayed") or 0), int(st.get("gamesStarted") or 0)
        return "SP" if g and gs >= g / 2 else "RP"
    return "OF" if r["pos"] in OF else r["pos"]


def is_pitcher_role(rl):
    return rl in ("SP", "RP")


def mlb_line(r):
    """(value, sample, text) for the MLB comparison stat, or None if too little MLB time."""
    if is_pitcher_role(role(r)):
        st = r["pitching"]
        ip = _ip(st.get("inningsPitched"))
        need = MIN_IP_SP if role(r) == "SP" else MIN_IP
        if ip >= need and _f(st.get("era")) is not None:
            return (_f(st["era"]), ip, f"{st['era']} ERA in {st['inningsPitched']} IP")
        return None
    st = r["hitting"]
    pa = int(st.get("plateAppearances") or 0)
    if pa >= MIN_PA and _f(st.get("ops")) is not None:
        return (_f(st["ops"]), pa, f"{st['ops']} OPS in {pa} PA")
    return None


def stat_text(r):
    """Short stat line: MLB if he played enough, else minors with level."""
    line = mlb_line(r)
    if line:
        return line[2] + " (MLB)"
    m = r.get("milb", {})
    if is_pitcher_role(role(r)):
        st = m.get("pitching") or {}
        if st.get("era"):
            return f"{st['era']} ERA in {st.get('inningsPitched', '?')} IP ({m.get('level') or 'minors'})"
        st = r["pitching"]
        if st.get("era"):
            return f"{st['era']} ERA in {st.get('inningsPitched', '?')} IP (MLB, small sample)"
    else:
        st = m.get("hitting") or {}
        if st.get("ops"):
            return f"{st['ops']} OPS in {st.get('plateAppearances', '?')} PA ({m.get('level') or 'minors'})"
        st = r["hitting"]
        if st.get("ops"):
            return f"{st['ops']} OPS in {st.get('plateAppearances', '?')} PA (MLB, small sample)"
    return f"no {rosters.stats_season()} stats"


# ---------- fit and impact ----------

def _peers(team_rows, rl, exclude_id):
    """MLB-roster players on a team in the same role, best first, with enough MLB time."""
    peers = []
    for r in team_rows:
        if r["id"] == exclude_id or r.get("group") != rosters.MLB or role(r) != rl:
            continue
        line = mlb_line(r)
        if line:
            peers.append((r, line))
    pitch = is_pitcher_role(rl)
    return sorted(peers, key=lambda x: x[1][0] if pitch else -x[1][0])


ROLE_NAME = {"SP": "starting pitcher", "RP": "reliever", "OF": "outfielder", "DH": "DH",
             "C": "catcher", "1B": "first baseman", "2B": "second baseman",
             "3B": "third baseman", "SS": "shortstop"}
PLURAL = {"OF": "outfielders", "DH": "DHs", "C": "catchers", "1B": "first basemen",
          "2B": "second basemen", "3B": "third basemen", "SS": "shortstops",
          "SP": "starting pitchers", "RP": "relievers"}


def fit(player, new_team_rows, team_name):
    """Bullet points on how the player fits his new team."""
    rl = role(player)
    what = ROLE_NAME.get(rl, rl)
    peers = _peers(new_team_rows, rl, player["id"])
    line = mlb_line(player)
    pitch = is_pitcher_role(rl)
    better = (lambda a, b: a < b) if pitch else (lambda a, b: a > b)
    out = []
    if not line:
        m = player.get("milb", {})
        lvl = m.get("level") or "the minors"
        out.append(f"Little {rosters.stats_season()} MLB time, so he likely starts as depth or a "
                   f"prospect ({stat_text(player)}).")
        if peers:
            names = ", ".join(f"{r['name']} ({l[2].split(' in ')[0]})" for r, l in peers[:3])
            out.append(f"{team_name} {PLURAL.get(rl, what)} ahead of him: {names}.")
        else:
            out.append(f"{team_name} has no {what} with real MLB playing time, so there's an "
                       f"opening if he earns it (last played at {lvl}).")
        return out
    if not peers:
        out.append(f"Fills a hole: {team_name} had no other {what} with "
                   f"{(MIN_IP_SP if rl == 'SP' else MIN_IP) if pitch else MIN_PA}+ {'IP' if pitch else 'PA'} on its MLB roster.")
        return out
    rank = 1 + sum(1 for _, l in peers if better(l[0], line[0]))
    top, top_line = peers[0]
    if rank == 1:
        out.append(f"Projects as {team_name}'s best {what}: his {line[2]} beats "
                   f"{top['name']} ({top_line[2]}).")
    else:
        out.append(f"Would rank #{rank} of {len(peers) + 1} {PLURAL.get(rl, what)} on {team_name} by "
                   f"{'ERA' if pitch else 'OPS'}; {top['name']} leads ({top_line[2]}).")
    if rl == "SP":
        out.append("Rotation role: " + ("likely a front-half starter." if rank <= 2 else
                                       "middle of the rotation." if rank <= 4 else
                                       "competing for the back of the rotation or long relief."))
    elif rl == "RP":
        out.append("Bullpen role: " + ("high-leverage option." if rank <= 3 else "middle relief / depth."))
    else:
        out.append("Lineup role: " + ("everyday starter." if rank == 1 else
                                     "platoon or part-time starter." if rank <= 2 else
                                     "bench depth."))
    return out


def impact(player, old_team_rows, team_name):
    """Bullet points on what losing the player means for his old team."""
    rl = role(player)
    what = ROLE_NAME.get(rl, rl)
    peers = _peers(old_team_rows, rl, player["id"])
    line = mlb_line(player)
    out = []
    if line:
        pitch = is_pitcher_role(rl)
        better = (lambda a, b: a < b) if pitch else (lambda a, b: a > b)
        rank = 1 + sum(1 for _, l in peers if better(l[0], line[0]))
        out.append(f"Loses its #{rank} {what} by {'ERA' if pitch else 'OPS'} ({line[2]}).")
    else:
        out.append(f"Gives up a player with little MLB time ({stat_text(player)}): mostly a "
                   f"prospect or depth cost.")
    if peers:
        nxt, nl = peers[0]
        out.append(f"Next in line: {nxt['name']} ({nl[2]}).")
    else:
        out.append(f"No other {what} with real MLB playing time left on the MLB roster: "
                   f"a spot to fill.")
    return out


def team_context(abbr, history_rows, top_salaries):
    """(record text, payroll $M, label) for a team's last season."""
    rows = [r for r in history_rows if r["abbr"] == abbr]
    if not rows:
        return "", None, ""
    last = max(rows, key=lambda r: r["year"])
    w, l = int(last["wins"] or 0), int(last["losses"] or 0)
    pct = w / (w + l) if w + l else 0
    label = "contender" if pct >= .540 else "rebuilding" if pct <= .460 else "middle of the pack"
    return f"{w}-{l} in {last['year']}", last["payroll"] / 1e6, label


def age_shift(trade, info):
    """{team name: average age in minus average age out} for each team."""
    out = {}
    for tid, name in trade["teams"].items():
        ins = [info[m["id"]]["age"] for m in trade["moves"] if m["to_id"] == tid and info.get(m["id"])]
        outs = [info[m["id"]]["age"] for m in trade["moves"] if m["from_id"] == tid and info.get(m["id"])]
        if ins and outs:
            out[name] = sum(ins) / len(ins) - sum(outs) / len(outs)
    return out


def abbr(team_name):
    return find_team(team_name)


def story_link(trade, news_items):
    """MLB Trade Rumors story whose headline names a player in the trade."""
    last_names = [m["name"].split()[-1] for m in trade["moves"]]
    for title, link in news_items:
        if any(n in title for n in last_names) and any(
                w in title for w in ("Trade", "Acquire", "Deal", "Swap")):
            return title, link
    return None


def moved_on(player, to_team):
    """Note when a traded player is no longer with the team that got him."""
    now = player.get("current_team") or ""
    if not now or find_team(now) == find_team(to_team):
        return ""
    if find_team(now):
        return f"Has since moved on: now with the {now}."
    return f"Has since left the {to_team} (now {now})."
