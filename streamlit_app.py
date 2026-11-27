"""Streamlit version of the live free agency dashboard.

Runs automatically when Streamlit runs fa_tracker.py (or this file).

Tabs
  * Free Agency  - signings and who's left, big names first, with pop-ups.
                   A background checker reads MLB's official transactions and
                   MLB Trade Rumors every minute.
  * Team Rosters - any team's current 40-man roster with last season's stats,
                   plus its free agent additions and losses this offseason.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import live_dashboard as ld
import rosters
from fa_tracker import BIG_AAV_M, BIG_TOTAL_M

REFRESH = "5s"           # how often the free agency board redraws
ROSTER_REFRESH = "60s"   # how often the roster tab redraws
ROSTER_CACHE = 300       # seconds before re-downloading a roster
POLL_MINUTES = 1         # how often MLB / news feeds are checked
BANNER_MINUTES = 30      # how long a big-name banner stays up
TZ = ZoneInfo("America/Los_Angeles")
GOLD = "background-color: rgba(242, 193, 78, 0.22)"
GREEN = "background-color: rgba(63, 185, 80, 0.18)"
SOURCE = {"MLB official": "Official (MLB)", "Reported": "Reported (MLB Trade Rumors)",
          "manual": "Added manually"}


# ---------- shared helpers ----------

def local(ts):
    """Server timestamp -> Pacific time text."""
    return datetime.fromisoformat(ts).astimezone(TZ)


def money(m):
    return f"${m:,.2f}".rstrip("0").rstrip(".") + "M" if m and m == m else "–"


def deal(p):
    yrs, total = p.get("years"), p.get("total_m")
    return f"{yrs} yr / {money(total)}" if yrs and total else "terms not yet reported"


def styled(df, highlight, color):
    """Color the rows where highlight[i] is True."""
    if df.empty:
        return df
    return df.style.apply(lambda row: [color if highlight[row.name] else ""] * len(row), axis=1)


# ---------- Free Agency tab ----------

def fa_table(players, cols):
    df = pd.DataFrame([{"★": "★" if p["big"] else "", **{k: f(p) for k, f in cols.items()}}
                       for p in players])
    if df.empty:
        return df
    whole = lambda v: "–" if pd.isna(v) else f"{int(v)}"
    fmt = {"Total": money, "AAV": money, "Yrs": whole, "Rank": whole}
    return styled(df, [p["big"] for p in players], GOLD).format(
        {c: f for c, f in fmt.items() if c in df})


SIGNED_COLS = {
    "Player": lambda p: p["name"], "Pos": lambda p: p["pos"],
    "From": lambda p: p["old_team"], "To": lambda p: p["new_team"],
    "Yrs": lambda p: p["years"], "Total": lambda p: p["total_m"],
    "AAV": lambda p: p["aav_m"], "Date": lambda p: p["signed_date"] or "",
    "Notes": lambda p: p["notes"],
}
AVAIL_COLS = {
    "Rank": lambda p: p["rank"], "Player": lambda p: p["name"], "Pos": lambda p: p["pos"],
    "2026 Team": lambda p: p["old_team"], "Notes": lambda p: p["notes"],
}


def pop_ups(events):
    """Toast every signing this visitor hasn't seen yet (not on first load)."""
    seen = st.session_state.setdefault("seen", None)
    ids = {e["id"] for e in events}
    if seen is None:
        st.session_state.seen = ids
        return
    for e in events:
        if e["id"] in seen:
            continue
        if e["big"]:
            st.toast(f"**★ BIG NAME: {e['name']} → {e['team']}**  \n{deal(e)}", icon="⭐",
                     duration="long")
            st.balloons()
        else:
            st.toast(f"**{e['name']} → {e['team']}**  \n{e['pos']} · {deal(e)}", icon="✍️")
    st.session_state.seen = seen | ids


def big_banner(events):
    cutoff = datetime.now() - timedelta(minutes=BANNER_MINUTES)
    recent = [e for e in events if e["big"] and datetime.fromisoformat(e["time"]) > cutoff]
    if not recent:
        return
    e = recent[-1]
    st.markdown(
        f"""<div style="border:2px solid #f2c14e;background:rgba(242,193,78,.12);
        border-radius:12px;padding:14px 20px;margin-bottom:8px">
        <span style="color:#c8971a;font-weight:800;letter-spacing:2px;font-size:12px">
        ★ BIG NAME SIGNING</span><br>
        <span style="font-size:28px;font-weight:800">{e['name']}</span>
        <span style="font-size:18px"> · {e['pos']} · {e['old_team'] + ' → ' if e['old_team'] else ''}
        {e['team']} · {deal(e)}</span><br>
        <span style="opacity:.7;font-size:13px">{SOURCE.get(e['source'], e['source'])}
        · {local(e['time']):%b %d, %I:%M %p} PT</span></div>""",
        unsafe_allow_html=True)


def free_agency_tab(q, pos, big_only, hide_minors):
    def keep(p):
        return ((not q or q in f"{p['name']} {p['old_team']} {p['new_team']}".lower())
                and (pos == "All" or p["pos"] == pos) and (p["big"] or not big_only))

    @st.fragment(run_every=REFRESH)
    def board():
        data = ld.snapshot()          # no lock: never waits on a slow feed check
        players, events = data["players"], data["events"]
        pop_ups(events)

        status = []
        if data["last_check"]:
            status.append(f"MLB checked {local(data['last_check']):%I:%M:%S %p}")
        if data["last_news_check"]:
            status.append(f"news {local(data['last_news_check']):%I:%M:%S %p} PT")
        st.caption(f"🔴 LIVE · feeds checked every minute · "
                   + (" · ".join(status) or "checking feeds…"))
        if data["last_error"]:
            st.warning(f"Feed check problem: {data['last_error']}")

        big_banner(events)

        signed = [p for p in players if p["signed"]]
        left = [p for p in players if not p["signed"]]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Signed", len(signed))
        c2.metric("Still available", len(left))
        c3.metric("★ Big names signed", sum(p["big"] for p in signed))
        c4.metric("★ Big names left", sum(p["big"] for p in left))
        st.progress(len(signed) / max(len(players), 1))

        if events:
            st.markdown("**Latest:** " + " · ".join(
                f"{'★ ' if e['big'] else ''}{e['name']} → {e['team']}"
                for e in reversed(events[-10:])))

        shown_signed = [p for p in signed if keep(p) and not (
            hide_minors and "minor league" in (p["notes"] or "").lower())]
        shown_left = [p for p in left if keep(p)]
        a, b = st.columns([3, 2])
        with a:
            st.subheader(f"Signings ({len(shown_signed)})")
            st.dataframe(fa_table(shown_signed, SIGNED_COLS), hide_index=True,
                         width="stretch", height=620)
        with b:
            st.subheader(f"Still available ({len(shown_left)})")
            st.dataframe(fa_table(shown_left, AVAIL_COLS), hide_index=True,
                         width="stretch", height=620)

    board()


# ---------- Team Rosters tab ----------

@st.cache_data(ttl=86400, show_spinner=False)
def cached_teams():
    return rosters.teams()


@st.cache_data(ttl=ROSTER_CACHE, show_spinner="Loading roster…")
def cached_roster(team_id):
    return rosters.roster(team_id)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_player(name):
    return rosters.player(name)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def hitter_row(r, contract):
    h = r["hitting"]
    return {"Player": r["name"], "Pos": r["pos"], "Age": r["age"], "B": r["bats"],
            "Status": r["status"], "Contract": contract,
            "G": h.get("gamesPlayed"), "PA": h.get("plateAppearances"),
            "AVG": h.get("avg"), "OBP": h.get("obp"), "SLG": h.get("slg"),
            "OPS": h.get("ops"), "HR": h.get("homeRuns"), "RBI": h.get("rbi"),
            "SB": h.get("stolenBases")}


def pitcher_row(r, contract):
    p = r["pitching"]
    return {"Player": r["name"], "Age": r["age"], "T": r["throws"],
            "Status": r["status"], "Contract": contract,
            "G": p.get("gamesPlayed"), "GS": p.get("gamesStarted"),
            "IP": p.get("inningsPitched"), "W": p.get("wins"), "L": p.get("losses"),
            "ERA": p.get("era"), "WHIP": p.get("whip"), "SO": p.get("strikeOuts"),
            "BB": p.get("baseOnBalls"), "SV": p.get("saves")}


def roster_table(rows, make_row, sort_key, new_names, contracts):
    rows = sorted(rows, key=lambda r: -(num(sort_key(r)) or -1))
    df = pd.DataFrame([make_row(r, contracts.get(ld.norm(r["name"]), "")) for r in rows])
    out = styled(df, [ld.norm(r["name"]) in new_names for r in rows], GREEN)
    if df.empty:
        return out
    whole = lambda v: "" if pd.isna(v) else f"{int(v)}"
    counts = ("Age", "G", "PA", "HR", "RBI", "SB", "GS", "W", "L", "SO", "BB", "SV")
    return out.format({c: whole for c in counts if c in df}, na_rep="")


def rosters_tab():
    @st.fragment(run_every=ROSTER_REFRESH)
    def view():
        teams = cached_teams()
        names = [t["name"] for t in teams]
        team = teams[names.index(st.session_state.get("team", names[0]))]
        st.selectbox("Team", names, key="team")

        fa = ld.snapshot()["players"]
        season = rosters.stats_season()
        incoming = [p for p in fa if p["signed"] and p["new_team"] == team["abbr"]
                    and "minor league" not in (p["notes"] or "").lower()]
        outgoing = [p for p in fa if p["old_team"] == team["abbr"]
                    and p["new_team"] != team["abbr"]]
        contracts = {ld.norm(p["name"]): deal(p) for p in incoming}
        new_names = set(contracts)

        roster = cached_roster(team["id"])
        on_roster = {ld.norm(r["name"]) for r in roster}
        for p in incoming:                          # deals not on the 40-man yet
            if ld.norm(p["name"]) not in on_roster and (r := cached_player(p["name"])):
                r = dict(r, status="Reported, not on 40-man yet"
                         if ld.REPORTED in (p["notes"] or "") else "Signed, not on 40-man yet")
                roster = roster + [r]

        c1, c2, c3 = st.columns(3)
        c1.metric("40-man roster", len([r for r in roster if r["status"] and "not on" not in r["status"]]))
        c2.metric("Free agents added", len(incoming))
        c3.metric("Free agents lost / unsigned", len(outgoing))

        with st.expander(f"{team['name']} free agency moves", expanded=bool(incoming or outgoing)):
            a, b = st.columns(2)
            with a:
                st.markdown("**Added**")
                st.dataframe(pd.DataFrame([{"Player": p["name"], "Pos": p["pos"], "From": p["old_team"],
                                            "Deal": deal(p), "Notes": p["notes"]} for p in incoming]),
                             hide_index=True, width="stretch")
            with b:
                st.markdown("**Lost or still unsigned**")
                st.dataframe(pd.DataFrame([{"Player": p["name"], "Pos": p["pos"],
                                            "Now": p["new_team"] or "Unsigned",
                                            "Deal": deal(p) if p["signed"] else ""} for p in outgoing]),
                             hide_index=True, width="stretch")

        st.caption(f"{season} season stats from MLB. Green rows = signed this offseason. "
                   "Contracts are shown for this offseason's free agent signings only; "
                   "MLB's data doesn't include salaries.")
        st.subheader("Position players")
        st.dataframe(roster_table([r for r in roster if rosters.is_hitter(r)], hitter_row,
                                  lambda r: r["hitting"].get("plateAppearances"),
                                  new_names, contracts),
                     hide_index=True, width="stretch", height=560)
        st.subheader("Pitchers")
        st.dataframe(roster_table([r for r in roster if rosters.is_pitcher(r)], pitcher_row,
                                  lambda r: r["pitching"].get("inningsPitched"),
                                  new_names, contracts),
                     hide_index=True, width="stretch", height=640)

    view()


# ---------- page ----------

def render():
    st.set_page_config(page_title="MLB Free Agency Tracker", page_icon="⚾", layout="wide")
    ld.ensure_checker(POLL_MINUTES, news=True)

    with st.sidebar:
        st.header("Free agency filters")
        q = st.text_input("Search player or team").strip().lower()
        positions = sorted({p["pos"] for p in ld.load()})
        pos = st.selectbox("Position", ["All"] + positions)
        big_only = st.toggle("★ Big names only")
        hide_minors = st.toggle("Hide minor-league deals", value=True)
        st.divider()
        if st.button("Check MLB + news now", width="stretch"):
            with ld.lock:
                ld.run_checks(True)
        st.caption(f"★ = big name: MLB Trade Rumors top 25, ${BIG_TOTAL_M}M+ total, "
                   f"or ${BIG_AAV_M}M+ per year.")

    st.title("⚾ MLB Free Agency Tracker")
    fa_tab, team_tab = st.tabs(["Free Agency", "Team Rosters"])
    with fa_tab:
        free_agency_tab(q, pos, big_only, hide_minors)
    with team_tab:
        rosters_tab()


if __name__ == "__main__":
    render()
