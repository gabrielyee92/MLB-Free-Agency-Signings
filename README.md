# MLB Free Agency Tracker

Tracks the 2026-27 MLB free agent class: who has signed, who is still available, and big names pinned to the top. Comes with a live dashboard that pops up new signings as they happen.

Pure Python standard library: nothing to install.

## Live dashboard

```
python live_dashboard.py
```

Then open http://localhost:8000.

- Checks **MLB's official transactions** feed for free agent signings.
- Checks the **MLB Trade Rumors** news feed for *reported* deals, including team and contract terms. These deals are tagged REPORTED until MLB makes them official. Rumors ("interest", "talks", "nearing a deal") are ignored.
- Pop-up for every new signing. Big names get a gold banner and a chime.
- Search, position filter, big-names-only and hide-minor-league-deals toggles.

Options: `--poll 2` (check every 2 minutes), `--no-news` (official signings only), `--port 8080`.

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
