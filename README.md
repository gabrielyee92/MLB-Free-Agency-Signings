# MLB Free Agency Tracker

Tracks the 2026-27 MLB free agent class: who has signed, who is still available, and big names pinned to the top. Comes with a live dashboard that pops up new signings as they happen.

Pure Python standard library: nothing to install.

## Streamlit

Deploy on Streamlit Community Cloud with **main file `fa_tracker.py`** (or `streamlit_app.py`). Locally:

```
streamlit run fa_tracker.py
```

Two tabs:

- **Free Agency**: the live board. Feeds are checked every minute; after the app wakes from sleep it reads back ~2 days of news so nothing posted while it slept is missed.
- **Team Rosters**: pick any team to see its 40-man roster split into the **MLB roster** (the live 26-man active roster during the season; in the offseason, the active roster from the last day of the regular season plus the injured list) and the **minor leagues** (the rest of the 40-man, with level, affiliate and minor-league stats), using the MLB Stats API, its free agent additions (highlighted, with contract terms) and the free agents it lost or hasn't re-signed. Signings not on the 40-man yet are included with their stats. MLB's data has no salaries, so contracts are shown for this offseason's free agent deals only. Note: Streamlit Cloud doesn't keep file changes, so when the app restarts, signings picked up from the feeds are lost until the next check (official MLB signings come right back; reported-only deals return once MLB makes them official). To make a change permanent, edit `free_agents.json` and push it.

## Live dashboard (local)

Double-click **Start Dashboard.bat**, or run:

```
python fa_tracker.py live
```

It opens http://localhost:8000 in your browser.

- Checks **MLB's official transactions** feed for free agent signings.
- Checks the **MLB Trade Rumors** news feed for *reported* deals, including team and contract terms. These deals are tagged REPORTED until MLB makes them official. Rumors ("interest", "talks", "nearing a deal") are ignored.
- Pop-up for every new signing. Big names get a gold banner and a chime.
- Search, position filter, big-names-only and hide-minor-league-deals toggles.

Options: `--poll 5` (check every 5 minutes; default is every minute), `--no-news` (official signings only), `--port 8080`.

## Command line

```
python fa_tracker.py                      # show the board
python fa_tracker.py show --top 25        # top 25 of each section
python fa_tracker.py show --big-only
python fa_tracker.py sign "Michael King" --team NYY --years 5 --total 130
python fa_tracker.py unsign "Michael King"
python fa_tracker.py add "Some Player" --pos RP --old-team SEA --rank 40
python fa_tracker.py big "Brandon Lowe"   # toggle big-name flag
python fa_tracker.py remove "Some Player"
```

Changes made from the command line show up on the dashboard within a few seconds.

## Big names

A player is a **★ big name** if they are flagged (MLB Trade Rumors' top 25 start flagged), signed for **$100M+ total**, or signed for **$20M+ per year**. Both sections sort big names first, then by ranking, then by contract size.

## Data

`free_agents.json` holds every player. The starting list came from MLB.com's 2026-27 free agent list, MLB Trade Rumors' Top 50, and the CBS Sports tracker (as of Nov. 26, 2026).
