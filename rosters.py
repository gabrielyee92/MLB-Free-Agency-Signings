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
