# MLB Free Agency Tracker

Tracks the 2026-27 MLB free agent class: who has signed, who is still available, and big names pinned to the top. Comes with a live dashboard that pops up new signings as they happen.

Pure Python standard library: nothing to install.

## Streamlit

Deploy on Streamlit Community Cloud with **main file `fa_tracker.py`** (or `streamlit_app.py`). Locally:

```
streamlit run fa_tracker.py
```

Two tabs:

- **Free Agency**: the live board. Feeds are checked every 30 seconds and the board redraws every 3 seconds; after the app wakes from sleep it reads back ~2 days of news so nothing posted while it slept is missed.
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

Options: `--poll 5` (check every 5 minutes; default is every 30 seconds), `--no-news` (official signings only), `--port 8080`.

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

## Salaries and payrolls

MLB's free data has no salaries, so they live in **`salaries.csv`** (amounts in $ millions):

| column | meaning |
|---|---|
| player, team | name as MLB spells it; team abbreviation (TOR, NYY, ...) |
| status | Guaranteed, Arbitration, Pre-arb, ... (Pre-arb with no salary = league minimum) |
| start_year, years | first season and length of the contract |
| total_m, aav_m | total value and average per year (give either; the other is computed) |
| 2027 ... 2032 | exact salary for a year (optional; otherwise AAV is used for each covered year) |

Add or update one player from the command line:

```
python fa_tracker.py salary "Vladimir Guerrero Jr." --team TOR --start 2026 --years 14 --total 500
python fa_tracker.py salary "Some Player" --team SEA --status Arbitration --by-year 2027=4.5
```

This offseason's free agent signings with terms are included automatically. The app shows each player's 2027 salary, AAV, total and years on **Team Rosters**, a payroll summary per team, and a **Payrolls** tab ranking all 30 teams for 2027-2032. Push `salaries.csv` to update the website.

### Contracts from the news (automatic)

The feed checker also reads MLB Trade Rumors stories for **contract extensions**, **arbitration deals** and other major-league signings, and records them in `salaries.csv` (marked `News:` in the notes column). Names are checked against MLB's player database, and the player's current team must match the headline. Rows you enter by hand are never overwritten. To read back through older news:

```
python fa_tracker.py contracts --pages 20     # ~15 stories per page, about half a day each
```

Payrolls follow each team's current 40-man roster, so traded players' salaries move with them automatically. Streamlit Cloud forgets file changes when it restarts; run the command above locally and push `salaries.csv` to keep what it found.

### Payroll history

`payroll_history.csv` holds final team payrolls for 1988-2026 from [The Baseball Cube](https://www.thebaseballcube.com/content/payroll_year/2026/), used with credit as its FAQ allows (team totals only). Refresh a season after it ends with `python payroll_history.py 2027` (it reads one page every 10 seconds). The Payrolls tab ranks all teams for any season, shows each team's payroll history, and adds the money already committed for 2027-2032.
