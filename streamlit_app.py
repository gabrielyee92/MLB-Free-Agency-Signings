"""Streamlit version of the live free agency dashboard.

Runs automatically when Streamlit runs fa_tracker.py (or this file).
The same background checker as the local dashboard watches MLB's official
transactions and MLB Trade Rumors for reported deals; the board refreshes
itself every few seconds and pops up new signings.
"""

import threading
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import live_dashboard as ld
from fa_tracker import BIG_AAV_M, BIG_TOTAL_M

REFRESH = "10s"          # how often the board redraws
POLL_MINUTES = 5         # how often MLB / news feeds are checked
BANNER_MINUTES = 30      # how long a big-name banner stays up
GOLD = "background-color: rgba(242, 193, 78, 0.22)"
SOURCE = {"MLB official": "Official (MLB)", "Reported": "Reported (MLB Trade Rumors)",
          "manual": "Added manually"}


@st.cache_resource
def start_checker():
    """One background checker per server, shared by every visitor."""
    ld.load_events()
    ld.check_file()
    t = threading.Thread(target=ld.background, args=(POLL_MINUTES, True), daemon=True)
    t.start()
    return t


def money(m):
    return f"${m:,.2f}".rstrip("0").rstrip(".") + "M" if m and m == m else "–"


def deal(e):
    return f"{e['years']} yr / {money(e['total_m'])}" if e.get("years") and e.get("total_m") \
        else "terms not yet reported"


def table(players, cols):
    df = pd.DataFrame([{"★": "★" if p["big"] else "", **{k: f(p) for k, f in cols.items()}}
                       for p in players])
    if df.empty:
        return df
    big = [p["big"] for p in players]
    styler = df.style.apply(lambda row: [GOLD if big[row.name] else ""] * len(row), axis=1)
    whole = lambda v: "–" if pd.isna(v) else f"{int(v)}"
    fmt = {"Total": money, "AAV": money, "Yrs": whole, "Rank": whole}
    return styler.format({c: f for c, f in fmt.items() if c in df})


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
        · {datetime.fromisoformat(e['time']):%b %d, %I:%M %p}</span></div>""",
        unsafe_allow_html=True)


def render():
    st.set_page_config(page_title="MLB Free Agency Tracker", page_icon="⚾", layout="wide")
    start_checker()

    with st.sidebar:
        st.header("Filters")
        q = st.text_input("Search player or team").strip().lower()
        with ld.lock:
            positions = sorted({p["pos"] for p in ld.load()})
        pos = st.selectbox("Position", ["All"] + positions)
        big_only = st.toggle("★ Big names only")
        hide_minors = st.toggle("Hide minor-league deals", value=True)
        st.divider()
        if st.button("Check MLB + news now", width="stretch"):
            with ld.lock:
                ld.run_checks(True)
        st.caption(f"★ = big name: MLB Trade Rumors top 25, ${BIG_TOTAL_M}M+ total, "
                   f"or ${BIG_AAV_M}M+ per year. Feeds are checked every "
                   f"{POLL_MINUTES} minutes.")

    def keep(p):
        return ((not q or q in f"{p['name']} {p['old_team']} {p['new_team']}".lower())
                and (pos == "All" or p["pos"] == pos) and (p["big"] or not big_only))

    @st.fragment(run_every=REFRESH)
    def board():
        with ld.lock:
            data = ld.snapshot()
        players, events = data["players"], data["events"]
        pop_ups(events)

        st.title("⚾ MLB Free Agency Tracker")
        status = []
        if data["last_check"]:
            status.append(f"MLB checked {datetime.fromisoformat(data['last_check']):%I:%M %p}")
        if data["last_news_check"]:
            status.append(f"news {datetime.fromisoformat(data['last_news_check']):%I:%M %p}")
        st.caption("🔴 LIVE · " + (" · ".join(status) or "checking feeds…"))
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
            st.dataframe(table(shown_signed, SIGNED_COLS), hide_index=True,
                         width="stretch", height=620)
        with b:
            st.subheader(f"Still available ({len(shown_left)})")
            st.dataframe(table(shown_left, AVAIL_COLS), hide_index=True,
                         width="stretch", height=620)

    board()


if __name__ == "__main__":
    render()
