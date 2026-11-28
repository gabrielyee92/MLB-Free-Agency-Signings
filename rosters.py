"""Team rosters and player stats from the MLB Stats API (statsapi.mlb.com).

MLB's API has rosters and stats but no salary data, so contracts come from
free_agents.json: the deals tracked for this offseason's free agents.
"""

import json
import urllib.parse
from datetime import date

from live_dashboard import fetch, find_team, norm

API = "https://statsapi.mlb.com/api/v1"


def stats_season(today=None):
    """Most recent season with stats: last year until the new season starts."""
    today = today or date.today()
    return today.year if today.month >= 4 else today.year - 1


def get(path):
    return json.loads(fetch(f"{API}/{path}"))


def teams():
    """All 30 teams, sorted by name, with the abbreviations this app uses."""
    out = [{"id": t["id"], "name": t["name"], "abbr": find_team(t["name"]) or t["abbreviation"]}
           for t in get("teams?sportId=1")["teams"]]
    return sorted(out, key=lambda t: t["name"])


def _stats(person):
    return {s["group"]["displayName"]: s["splits"][0]["stat"]
            for s in person.get("stats", []) if s.get("splits")}


def _row(person, pos, status, season):
    st = _stats(person)
    return {"id": person["id"], "name": person["fullName"], "pos": pos,
            "age": person.get("currentAge"), "status": status,
            "bats": person.get("batSide", {}).get("code", ""),
            "throws": person.get("pitchHand", {}).get("code", ""),
            "hitting": st.get("hitting", {}), "pitching": st.get("pitching", {})}


def roster(team_id, season=None):
    """The team's current 40-man roster with each player's season stats."""
    season = season or stats_season()
    q = (f"teams/{team_id}/roster?rosterType=40Man&hydrate=person(stats("
         f"type=season,season={season},group=[hitting,pitching]))")
    return [_row(r["person"], r["position"]["abbreviation"], r["status"]["description"], season)
            for r in get(q)["roster"]]


# ---------- MLB roster vs. minor leagues ----------

MLB, MINORS = "MLB", "Minors"
JOINED = "Joined 40-man after the season"
LEVELS = ["AAA", "AA", "A+", "A", "ROK", "DSL"]   # highest first


def season_dates(today=None):
    """(regular season start, end) for the season that matters today, and
    whether today falls inside it."""
    today = today or date.today()
    for year in (today.year, today.year - 1):
        s = get(f"seasons/{year}?sportId=1")["seasons"][0]
        start = date.fromisoformat(s["regularSeasonStartDate"])
        end = date.fromisoformat(s["regularSeasonEndDate"])
        if today >= start:
            return start, end, today <= end
    return start, end, False


def _ids(team_id, roster_type, on):
    q = f"teams/{team_id}/roster?rosterType={roster_type}&date={on.isoformat()}"
    return {r["person"]["id"]: r["status"]["description"] for r in get(q)["roster"]}


def _level_rank(split):
    abbr = split.get("sport", {}).get("abbreviation")
    return LEVELS.index(abbr) if abbr in LEVELS else len(LEVELS)


def _games(stats):
    return max(int(stats.get(g, {}).get("gamesPlayed") or 0) for g in ("hitting", "pitching"))


def minor_league_stats(ids, season=None):
    """{player id: {"level", "team", "hitting", "pitching"}} from every
    minor-league level the player played at this season."""
    if not ids:
        return {}
    season = season or stats_season()
    q = (f"people?personIds={','.join(map(str, ids))}&hydrate=stats(type=season,"
         f"season={season},group=[hitting,pitching],leagueListId=milb_all)")
    out = {}
    for p in get(q).get("people", []):
        info = {"level": "", "team": "", "hitting": {}, "pitching": {}}
        for s in p.get("stats", []):
            splits = s.get("splits", [])
            by_level = [sp for sp in splits if sp.get("team")]
            totals = [sp for sp in splits if not sp.get("team")]
            if not splits:
                continue
            # season totals across levels when there are several, else the one level
            info[s["group"]["displayName"]] = (totals or by_level)[0]["stat"]
            # highest level reached; the latest team at that level
            rank = lambda i: (-_level_rank(by_level[i]), i)
            top = by_level[max(range(len(by_level)), key=rank)] if by_level else None
            if top and not info["level"]:
                info["level"] = top.get("sport", {}).get("abbreviation", "")
                info["team"] = top["team"].get("name", "")
        out[p["id"]] = info
    return out


def team_roster(team_id, mlb_deals=()):
    """The 40-man roster split into the MLB roster and the minor leagues.

    In season the MLB group is today's active (26-man) roster. In the
    offseason there is no active roster, so it's the active roster from the
    last day of the regular season (plus players on the injured list then).
    Players added to the 40-man since then (trades, claims, prospects
    protected from the Rule 5 draft, signings) go wherever they played more
    games this season; names in `mlb_deals` (free agents signed to
    major-league deals) always count as MLB."""
    start, end, in_season = season_dates()
    on = date.today() if in_season else end
    active = _ids(team_id, "active", on)
    then = {} if in_season else _ids(team_id, "40Man", on)
    rows = roster(team_id)
    milb = minor_league_stats([r["id"] for r in rows if r["id"] not in active])
    deals = {norm(n) for n in mlb_deals}
    for r in rows:
        r["milb"] = milb.get(r["id"], {})
        if r["id"] in active:
            r["group"] = MLB
        elif in_season:
            r["group"] = MLB if "Injured" in r["status"] else MINORS
        elif r["id"] in then:
            r["group"] = MLB if "Injured" in then[r["id"]] else MINORS
            if "Injured" in then[r["id"]]:
                r["status"] = f"{then[r['id']]} at season end"
        else:
            mlb_g, milb_g = _games(r), _games(r["milb"])
            r["group"] = MLB if norm(r["name"]) in deals or (mlb_g and mlb_g >= milb_g) else MINORS
            r["status"] = JOINED
    label = (f"Active roster today" if in_season
             else f"Active roster on the last day of the {end.year} regular season ({end:%b %d})")
    return {"rows": rows, "in_season": in_season, "label": label, "active_size": len(active)}


def player(name, season=None):
    """Look up one MLB player by name (for signings not on a roster yet)."""
    season = season or stats_season()
    q = (f"people/search?names={urllib.parse.quote(name)}&sportIds=1&hydrate=stats("
         f"type=season,season={season},group=[hitting,pitching])")
    people = [p for p in get(q).get("people", []) if norm(p["fullName"]) == norm(name)]
    if not people:
        return None
    p = people[0]
    return _row(p, p.get("primaryPosition", {}).get("abbreviation", ""), "", season)


def is_pitcher(r):
    return r["pos"] in ("P", "SP", "RP", "TWP")


def is_hitter(r):
    return not is_pitcher(r) or r["pos"] == "TWP"
