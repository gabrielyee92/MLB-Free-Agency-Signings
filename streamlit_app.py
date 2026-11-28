"""Streamlit version of the live free agency dashboard.

Runs automatically when Streamlit runs fa_tracker.py (or this file).

Tabs
  * Free Agency  - signings and who's left, big names first, with pop-ups.
                   A background checker reads MLB's official transactions and
                   MLB Trade Rumors every 30 seconds.
  * Team Rosters - any team's current 40-man roster with last season's stats,
                   plus its free agent additions and losses this offseason.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import contracts
import live_dashboard as ld
import rosters
from fa_tracker import BIG_AAV_M, BIG_TOTAL_M

REFRESH = "3s"           # how often the free agency board redraws
ROSTER_REFRESH = "30s"   # how often the roster tab redraws
ROSTER_CACHE = 30        # seconds before re-downloading a roster
LIVE_TTL = 30            # seconds any live data is cached
PAYROLLS_REFRESH = "30s" # how often the payrolls tab redraws
POLL_MINUTES = 0.5       # how often MLB / news feeds are checked (30 seconds)
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
        kind = e.get("kind", "signing")
        if kind == "trade":
            st.toast(f"**🔄 TRADE (official)**  \n{e['name']}", icon="🔄", duration="long")
        elif kind == "trade_reported":
            st.toast(f"**🔄 TRADE (reported)**  \n{e['name']}"
                     + (f"  \n[MLB Trade Rumors]({e['link']})" if e.get("link") else ""),
                     icon="🔄", duration="long")
        elif e["big"]:
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
        st.caption(f"🔴 LIVE · feeds checked every {POLL_MINUTES * 60:g} seconds · "
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

        moves = latest_moves(players, events, 10)
        if moves:
            st.markdown("**Latest moves:** " + " · ".join(
                f"{'★ ' if m['big'] else ''}{'🔄 ' if m['type'].startswith('Trade') else ''}"
                f"{m['player']}{' → ' + m['to'] if m['to'] else ''}" for m in moves))

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
def cached_team_roster(team_id, mlb_deals):
    return rosters.team_roster(team_id, mlb_deals)


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def cached_player(name):
    return rosters.player(name)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def stats_of(r, group, minors):
    """MLB stats for the MLB roster, minor-league stats for the minors."""
    return (r.get("milb", {}) if minors else r).get(group) or {}


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def last_season_salaries():
    """(season, {player: $M}) for the highest salaries listed by The Baseball Cube."""
    import payroll_history as ph
    top = ph.read_top()
    if not top:
        return None, {}
    season = max(r["year"] for r in top)
    return season, {ld.norm(r["player"]): r["salary"] / 1e6 for r in top if r["year"] == season}


def player_cols(r, c, minors, hand):
    cols = {"Player": r["name"], "Pos": r["pos"], "Age": r["age"], hand[0]: r[hand[1]]}
    if minors:
        cols |= {"Level": r.get("milb", {}).get("level") or "–",
                 "Affiliate": r.get("milb", {}).get("team") or ""}
    y = contracts.PAYROLL_YEAR
    pay = contracts.salary(c, y)
    est = bool(pay) and y not in c["by_year"] and not c["years"]   # pre-arb at league min
    last_y, last = last_season_salaries()
    if last_y:
        cols[f"{last_y} salary"] = money(last.get(ld.norm(r["name"])))
    return cols | {"Status": r["status"],
                   f"{y} salary": (money(pay) + (" (min, est.)" if est else "")) if pay else "–",
                   "AAV": money(c["aav_m"]) if c else "–",
                   "Total": money(c["total_m"]) if c else "–",
                   "Years": contracts.years_text(c)}


def hitter_row(r, c, minors):
    h = stats_of(r, "hitting", minors)
    return player_cols(r, c, minors, ("B", "bats")) | {
        "G": h.get("gamesPlayed"), "PA": h.get("plateAppearances"),
        "AVG": h.get("avg"), "OBP": h.get("obp"), "SLG": h.get("slg"),
        "OPS": h.get("ops"), "HR": h.get("homeRuns"), "RBI": h.get("rbi"),
        "SB": h.get("stolenBases")}


def pitcher_row(r, c, minors):
    p = stats_of(r, "pitching", minors)
    return player_cols(r, c, minors, ("T", "throws")) | {
        "G": p.get("gamesPlayed"), "GS": p.get("gamesStarted"),
        "IP": p.get("inningsPitched"), "W": p.get("wins"), "L": p.get("losses"),
        "ERA": p.get("era"), "WHIP": p.get("whip"), "SO": p.get("strikeOuts"),
        "BB": p.get("baseOnBalls"), "SV": p.get("saves")}


def roster_table(rows, pitchers, minors, new_names, deals):
    make, group, key = ((pitcher_row, "pitching", "inningsPitched") if pitchers
                        else (hitter_row, "hitting", "plateAppearances"))
    rows = sorted(rows, key=lambda r: -(num(stats_of(r, group, minors).get(key)) or -1))
    df = pd.DataFrame([make(r, deals.get(ld.norm(r["name"])), minors) for r in rows])
    if df.empty:
        return df
    df = df.astype(object).where(df.notna(), "")   # Streamlit draws missing values as "None"
    out = styled(df, [ld.norm(r["name"]) in new_names for r in rows], GREEN)
    whole = lambda v: "" if v == "" else f"{int(v)}"
    counts = ("Age", "G", "PA", "HR", "RBI", "SB", "GS", "W", "L", "SO", "BB", "SV")
    return out.format({c: whole for c in counts if c in df})


def roster_section(title, note, rows, minors, new_names, deals):
    with st.container(border=True):
        st.subheader(title)
        st.caption(note)
        for label, pitchers in (("Position players", False), ("Pitchers", True)):
            part = [r for r in rows if (rosters.is_pitcher(r) if pitchers else rosters.is_hitter(r))]
            st.markdown(f"**{label} ({len(part)})**")
            if part:
                st.dataframe(roster_table(part, pitchers, minors, new_names, deals),
                             hide_index=True, width="stretch",
                             height=min(38 + 35 * len(part), 600))


PAYROLL_NOTE = (
    "Payroll = salaries owed to players on the 40-man roster (plus signings not on it yet). "
    "Committed counts only salaries entered in salaries.csv and tracked free agent signings. "
    f"The estimate also counts every player without a salary at the league minimum "
    f"(${contracts.LEAGUE_MIN_M}M, the 2026 figure; the 2027 minimum depends on the next "
    "labor deal).")


def payroll_block(team, rows, deals):
    pay = contracts.payroll([r["name"] for r in rows], deals)
    y = contracts.PAYROLL_YEAR
    with st.container(border=True):
        st.subheader(f"💰 {team['name']} payroll")
        c1, c2, c3 = st.columns(3)
        c1.metric(f"{y} committed", money(pay["by_year"][y]))
        c2.metric(f"Players with a {y} salary", f"{pay['known']} / {pay['players']}")
        c3.metric(f"{y} estimate (blanks at league min)", money(pay["estimate"]))
        st.dataframe(pd.DataFrame([{str(yr): money(v) for yr, v in pay["by_year"].items()}]),
                     hide_index=True, width="stretch")
        st.caption(PAYROLL_NOTE)


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def cached_roster_names(team_id):
    return rosters.roster_names(team_id)


TBC_LINK = "[The Baseball Cube](https://www.thebaseballcube.com/content/payroll_year/{year}/)"
BLUE = "#2a78d6"          # validated categorical slot 1 (single-series charts)


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def payroll_history():
    import payroll_history as ph
    df = pd.DataFrame(ph.read())
    if not df.empty:
        df["payroll_m"] = df["payroll"] / 1e6
    return df


def committed_payrolls(teams, deals, fa):
    """This app's committed future payrolls for every team (partial: only
    salaries in salaries.csv and tracked signings)."""
    rows = []
    for t in teams:
        names = list(cached_roster_names(t["id"]))
        on = {ld.norm(n) for n in names}
        names += [p["name"] for p in fa if p.get("signed") and p.get("new_team") == t["abbr"]
                  and "minor league" not in (p.get("notes") or "").lower()
                  and ld.norm(p["name"]) not in on]
        pay = contracts.payroll(names, deals)
        rows.append({"team": t["name"], "abbr": t["abbr"], "known": pay["known"],
                     "players": pay["players"], "estimate": pay["estimate"],
                     **{yr: pay["by_year"][yr] for yr in contracts.YEARS}})
    return pd.DataFrame(rows)


def league_bars(df, value, label):
    import altair as alt
    return (alt.Chart(df).mark_bar(color=BLUE, cornerRadiusEnd=4, height=14)
            .encode(y=alt.Y("Team:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220)),
                    x=alt.X(f"{value}:Q", title=label),
                    tooltip=["Team:N", alt.Tooltip(f"{value}:Q", title=label, format="$,.1f")])
            .properties(height=30 * len(df)))


def team_trend(df):
    import altair as alt
    base = alt.Chart(df).encode(
        x=alt.X("Season:Q", title=None, axis=alt.Axis(format="d", tickMinStep=1)),
        y=alt.Y("Payroll ($M):Q", title="Payroll ($M)"))
    line = base.mark_line(color=BLUE, strokeWidth=2).encode(
        strokeDash=alt.StrokeDash("Kind:N", legend=None, scale=alt.Scale(
            domain=["Actual", "Committed so far"], range=[[1, 0], [5, 4]])),
        detail="Kind:N")
    dots = base.mark_circle(color=BLUE, size=64).encode(tooltip=[
        alt.Tooltip("Season:Q", format="d"), "Kind:N",
        alt.Tooltip("Payroll ($M):Q", format="$,.1f")])
    return (line + dots).properties(height=320)


def payrolls_tab():
    st.fragment(run_every=PAYROLLS_REFRESH)(payrolls_view)()


def payrolls_view():
    teams = cached_teams()
    deals = contracts.load_contracts()
    fa = ld.load()
    hist = payroll_history()
    with st.spinner("Loading all 30 rosters…"):
        future = committed_payrolls(teams, deals, fa)
    past_years = sorted(hist["year"].unique()) if not hist.empty else []
    last_actual = past_years[-1] if past_years else None

    st.subheader("💰 MLB payrolls: past, present and future")
    st.caption(f"Seasons {past_years[0]}–{last_actual}: final team payrolls from "
               f"{TBC_LINK.format(year=last_actual)} (used with credit, per its FAQ). "
               f"{contracts.YEARS[0]}–{contracts.YEARS[-1]}: money already committed that this "
               f"app knows about (tracked signings, contract news and salaries.csv), so these "
               f"are partial until more contracts are entered." if past_years else PAYROLL_NOTE)

    # ---- one season, all 30 teams ----
    seasons = past_years + contracts.YEARS
    season = st.select_slider("Season", options=seasons,
                              value=last_actual or contracts.PAYROLL_YEAR, key="pay_season")
    if season in past_years:
        d = hist[hist["year"] == season].sort_values("payroll", ascending=False)
        table = pd.DataFrame({
            "Rank": range(1, len(d) + 1), "Team": d["team"].values,
            "Payroll ($M)": d["payroll_m"].round(2).values,
            "W-L": (d["wins"].astype(str) + "-" + d["losses"].astype(str)).values,
            "Top salary": d["top_salary"].values})
        a, b = st.columns([3, 2])
        with a:
            st.markdown(f"**{season} payrolls** · total ${d['payroll_m'].sum():,.0f}M · "
                        f"average ${d['payroll_m'].mean():,.1f}M · source: "
                        f"{TBC_LINK.format(year=season)}")
            st.altair_chart(league_bars(table, "Payroll ($M)", "Payroll ($M)"), width="stretch")
        with b:
            st.dataframe(table.style.format({"Payroll ($M)": "${:,.2f}M"}),
                         hide_index=True, width="stretch", height=38 + 35 * len(table))
    else:
        d = future.sort_values(season, ascending=False)
        table = pd.DataFrame({
            "Team": d["team"].values, "Committed ($M)": d[season].round(2).values,
            "Salaries entered": [f"{k} / {n}" for k, n in zip(d["known"], d["players"])]})
        if season == contracts.PAYROLL_YEAR:
            table[f"Estimate ($M)"] = d["estimate"].round(2).values
        st.warning(f"{season} is a future season: these are only the salaries this app knows "
                   f"about so far, not full payrolls. " + PAYROLL_NOTE)
        a, b = st.columns([3, 2])
        with a:
            st.altair_chart(league_bars(table, "Committed ($M)", f"{season} committed ($M)"),
                            width="stretch")
        with b:
            fmt = {c: "${:,.2f}M" for c in table if "($M)" in c}
            st.dataframe(table.style.format(fmt), hide_index=True, width="stretch",
                         height=38 + 35 * len(table))

    # ---- one team over time ----
    st.divider()
    names = [t["name"] for t in teams]
    team = st.selectbox("Team history", names, key="pay_team",
                        index=names.index("New York Mets") if "New York Mets" in names else 0)
    abbr = next(t["abbr"] for t in teams if t["name"] == team)
    trend = []
    if not hist.empty:
        h = hist[hist["abbr"] == abbr]
        trend += [{"Season": int(r.year), "Payroll ($M)": round(r.payroll_m, 2), "Kind": "Actual",
                   "Team name then": r.team} for r in h.itertuples()]
    row = future[future["abbr"] == abbr]
    if not row.empty:
        trend += [{"Season": yr, "Payroll ($M)": round(float(row.iloc[0][yr]), 2),
                   "Kind": "Committed so far", "Team name then": team} for yr in contracts.YEARS]
    tdf = pd.DataFrame(trend)
    if not tdf.empty:
        st.markdown(f"**{team} payroll by season** · solid = actual payroll, dashed = money "
                    f"committed so far for future seasons (partial)")
        st.altair_chart(team_trend(tdf), width="stretch")
        with st.expander("Table view"):
            st.dataframe(tdf.sort_values("Season", ascending=False)
                         .style.format({"Payroll ($M)": "${:,.2f}M"}),
                         hide_index=True, width="stretch")

    # ---- contracts read from the news ----
    st.divider()
    y = contracts.PAYROLL_YEAR
    news = [c for c in deals.values() if c["notes"].startswith("News")]
    st.subheader(f"📰 Contracts picked up from the news ({len(news)})")
    st.caption("Extensions, arbitration deals and other signings read automatically from "
               "MLB Trade Rumors stories (checked every 30 seconds). Free agent deals are on the "
               "Free Agency tab.")
    if news:
        st.dataframe(pd.DataFrame([{
            "Player": c["player"], "Team": c["team"], "Type": c["status"],
            "Years": contracts.years_text(c), "Total": money(c["total_m"]),
            "AAV": money(c["aav_m"]), f"{y} salary": money(contracts.salary(c, y)),
            "Headline": c["notes"].removeprefix("News: ")} for c in news]),
            hide_index=True, width="stretch")


# ---------- latest moves (signings + trades) ----------

def latest_moves(players, events, n=25):
    """Newest player moves first: signings from the board (with their dates),
    official trades, and trades just reported by MLB Trade Rumors."""
    moves = []
    for p in players:
        if p.get("signed") and p.get("signed_date"):
            notes = p.get("notes") or ""
            moves.append({"date": p["signed_date"], "type": "Signing" + (
                " (reported)" if ld.REPORTED in notes else ""), "player": p["name"],
                "from": p.get("old_team", ""), "to": p.get("new_team", ""),
                "deal": deal(p) if p.get("years") else ("minor league deal" if "minor league"
                                                         in notes.lower() else ""),
                "big": bool(p.get("big"))})
    try:
        official = cached_trades()
    except Exception:
        official = []
    for t in official:
        for mv in t["moves"]:
            moves.append({"date": t["date"][:10], "type": "Trade", "player": mv["name"],
                          "from": ld.find_team(mv["from"]), "to": ld.find_team(mv["to"]),
                          "deal": "", "big": False})
    for e in events:
        if e.get("kind") == "trade_reported":
            moves.append({"date": e["time"][:10], "type": "Trade (reported)", "player": e["name"],
                          "from": "", "to": "", "deal": "", "big": False})
    moves.sort(key=lambda m: (m["date"], m["big"]), reverse=True)
    return moves[:n]


# ---------- Trades tab ----------

TRADES_REFRESH = "30s"


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def cached_trades():
    import trades
    return trades.recent_trades()


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def cached_trade_players(ids):
    import trades
    return trades.players(list(ids))


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def recent_news_titles(pages=4):
    import html as _html
    import xml.etree.ElementTree as ET
    out = []
    for page in range(1, pages + 1):
        url = ld.NEWS_FEED if page == 1 else f"{ld.NEWS_FEED}?paged={page}"
        try:
            for it in ET.fromstring(ld.fetch(url)).iter("item"):
                out.append((_html.unescape(it.findtext("title") or ""), it.findtext("link")))
        except Exception:
            break
    return out


def nickname(team_name):
    return next((n for n in ld.TEAMS if n in team_name), team_name)


def trade_label(t):
    teams = " ⇄ ".join(nickname(n) for n in t["teams"].values())
    names = ", ".join(m["name"] for m in t["moves"])
    return f"{t['date'][5:].replace('-', '/')} · {teams}: {names}"


def trades_tab():
    import payroll_history as ph
    import trades

    @st.fragment(run_every=TRADES_REFRESH)
    def view():
        everything = cached_trades()
        st.subheader("🔄 Trades and latest moves")
        snap = ld.snapshot()
        moves = latest_moves(snap["players"], snap["events"], 25)
        if moves:
            st.markdown("**Latest moves (signings and trades, newest first)**")
            st.dataframe(pd.DataFrame([{"Date": m["date"], "Move": m["type"],
                                        "Player": ("★ " if m["big"] else "") + m["player"],
                                        "From": m["from"], "To": m["to"], "Deal": m["deal"]}
                                       for m in moves]),
                         hide_index=True, width="stretch", height=38 + 35 * min(len(moves), 12))

        reported = [e for e in ld.snapshot()["events"] if e.get("kind") == "trade_reported"]
        if reported:
            st.markdown("**📰 Just reported (may not be official yet)**")
            st.markdown("\n".join(f"- [{e['name']}]({e['link']}) · {local(e['time']):%b %d %I:%M %p} PT"
                                  for e in reversed(reported[-8:])))

        periods = ["All"] + sorted({t.get("period", "Other") for t in everything}, reverse=True)
        period = st.radio("Show", periods, horizontal=True, key="trade_period")
        all_trades = [t for t in everything if period == "All" or t.get("period", "Other") == period]
        st.caption(f"{len(all_trades)} official trades from MLB's transaction feed and trades "
                   "reported by MLB Trade Rumors, both checked every 30 seconds. Fit and "
                   "impact notes compare each player's 2026 stats with the players at his "
                   "position on each team's roster today (OPS for hitters with 100+ PA, ERA for "
                   "starters with 60+ IP, relievers with 20+). They're simple comparisons, "
                   "not projections.")
        if not all_trades:
            st.info("No official trades in this period yet.")
            return
        labels = [trade_label(t) for t in all_trades]
        pick = st.selectbox("Trade", labels, key="trade_pick")
        t = all_trades[labels.index(pick)]

        info = cached_trade_players(tuple(m["id"] for m in t["moves"]))
        hist, top = ph.read(), ph.read_top()
        last_y, last_sal = last_season_salaries()
        deals = contracts.load_contracts()
        y = contracts.PAYROLL_YEAR

        st.markdown(f"**{t['description']}**  ·  {t['date']}")
        story = trades.story_link(t, recent_news_titles())
        if story:
            st.markdown(f"📰 [{story[0]}]({story[1]}) (MLB Trade Rumors)")

        # ---- each team's side ----
        shift = trades.age_shift(t, info)
        cols = st.columns(len(t["teams"]))
        for col, (tid, tname) in zip(cols, t["teams"].items()):
            rec, pay, label = trades.team_context(trades.abbr(tname), hist, top)
            gets = [m["name"] for m in t["moves"] if m["to_id"] == tid]
            gives = [m["name"] for m in t["moves"] if m["from_id"] == tid]
            with col, st.container(border=True):
                st.markdown(f"#### {tname}")
                if rec:
                    st.caption(f"{rec} · {label} · {last_y or ''} payroll {money(pay)}")
                st.markdown("**Gets:** " + (", ".join(gets) or "cash or future considerations"))
                st.markdown("**Gives up:** " + (", ".join(gives) or "cash or future considerations"))
                if tname in shift and abs(shift[tname]) >= 1:
                    st.markdown(f"**Age:** gets {'younger' if shift[tname] < 0 else 'older'} by "
                                f"{abs(shift[tname]):.1f} years on average in this deal")
                money_out = sum(last_sal.get(ld.norm(n), 0) for n in gives)
                money_in = sum(last_sal.get(ld.norm(n), 0) for n in gets)
                if money_out or money_in:
                    st.markdown(f"**{last_y} salary:** {money(money_in) if money_in else '$0'} in, "
                                f"{money(money_out) if money_out else '$0'} out (top earners only)")

        # ---- each player ----
        for m in t["moves"]:
            p = info.get(m["id"])
            if not p:
                continue
            new_rows = cached_team_roster(m["to_id"], ())["rows"]
            old_rows = cached_team_roster(m["from_id"], ())["rows"]
            c = deals.get(ld.norm(p["name"]))
            pay_bits = []
            if last_sal.get(ld.norm(p["name"])):
                pay_bits.append(f"{last_y} salary {money(last_sal[ld.norm(p['name'])])}")
            if c and contracts.salary(c, y):
                pay_bits.append(f"{y} salary {money(contracts.salary(c, y))}")
            with st.container(border=True):
                st.markdown(f"### {p['name']}  ·  {nickname(m['from'])} → {nickname(m['to'])}")
                st.caption(f"{p['pos']} · {trades.ROLE_NAME.get(trades.role(p), trades.role(p))} · "
                           f"age {p['age']} · {trades.stat_text(p)}"
                           + (" · " + " · ".join(pay_bits) if pay_bits else ""))
                if note := trades.moved_on(p, m["to"]):
                    st.info(f"{note} The notes below describe the trade as it looked for "
                            f"today's {nickname(m['to'])} and {nickname(m['from'])} rosters.")
                a, b = st.columns(2)
                with a:
                    st.markdown(f"**How he fits the {nickname(m['to'])}**")
                    st.markdown("\n".join(f"- {x}" for x in trades.fit(p, new_rows, m["to"])))
                with b:
                    st.markdown(f"**What it means for the {nickname(m['from'])}**")
                    st.markdown("\n".join(f"- {x}" for x in trades.impact(p, old_rows, m["from"])))

        with st.expander(f"All {len(all_trades)} trades"):
            st.dataframe(pd.DataFrame([{"Date": x["date"],
                                        "Teams": " ⇄ ".join(nickname(n) for n in x["teams"].values()),
                                        "Players": ", ".join(f"{mv['name']} → {nickname(mv['to'])}"
                                                             for mv in x["moves"])}
                                       for x in all_trades]), hide_index=True, width="stretch")

    view()


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
        new_names = {ld.norm(p["name"]) for p in incoming}
        deals = contracts.load_contracts()

        data = cached_team_roster(team["id"], tuple(sorted(p["name"] for p in incoming)))
        rows = list(data["rows"])
        on_roster = {ld.norm(r["name"]) for r in rows}
        for p in incoming:                          # deals not on the 40-man yet
            if ld.norm(p["name"]) not in on_roster and (r := cached_player(p["name"])):
                rows.append(dict(r, group=rosters.MLB, milb={}, status=(
                    "Reported, not on 40-man yet" if ld.REPORTED in (p["notes"] or "")
                    else "Signed, not on 40-man yet")))
        mlb = [r for r in rows if r["group"] == rosters.MLB]
        minors = [r for r in rows if r["group"] == rosters.MINORS]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("MLB roster", len(mlb))
        c2.metric("Minor leagues (40-man)", len(minors))
        c3.metric("Free agents added", len(incoming))
        c4.metric("Free agents lost / unsigned", len(outgoing))

        payroll_block(team, rows, deals)

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

        last_y, _ = last_season_salaries()
        st.caption("Green rows = signed this offseason. "
                   + (f"{last_y} salary: the ~100 highest {last_y} salaries, from "
                      f"[The Baseball Cube](https://www.thebaseballcube.com/content/payroll_year/{last_y}/). "
                      if last_y else "")
                   + f"{contracts.PAYROLL_YEAR} salary, AAV, total and years: this offseason's "
                   "tracked signings, contracts from the news and salaries.csv. "
                   "– = not known yet.")
        if data["in_season"]:
            mlb_note = f"Today's 26-man active roster plus the injured list · {season} MLB stats"
        else:
            mlb_note = (f"Offseason: there's no 26-man roster until Opening Day. This group is "
                        f"based on the {data['label'][0].lower() + data['label'][1:]} "
                        f"(rosters expand to 28 in September) and the injured list then, minus "
                        f"players who have left, plus newcomers who played mostly in the majors · "
                        f"{season} MLB stats")
        roster_section(f"🏟️ MLB roster ({len(mlb)})", mlb_note, mlb, False, new_names, deals)
        roster_section(f"🌱 Minor leagues — rest of the 40-man ({len(minors)})",
                       f"On the 40-man roster but playing in the minors · {season} minor-league "
                       f"stats, all levels combined · Level = highest level reached",
                       minors, True, new_names, deals)

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
    fa_tab, team_tab, trade_tab, pay_tab = st.tabs(["Free Agency", "Team Rosters", "Trades", "Payrolls"])
    with fa_tab:
        free_agency_tab(q, pos, big_only, hide_minors)
    with team_tab:
        rosters_tab()
    with trade_tab:
        trades_tab()
    with pay_tab:
        payrolls_tab()


if __name__ == "__main__":
    render()
