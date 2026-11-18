# NYC Subway all-stations record planner

Goal: beat 22:14:10 (Kate Jones, 17-18 April 2023) for riding a stopping train through every NYC subway station.

## What is here

| Piece | File | Status |
|---|---|---|
| GTFS -> compressed network (475 stops -> ~160 "atoms") | `src/build_network.py`, `src/config.py` | working |
| Lookup tables, every scheduled connection made | `src/tables.cpp` | working, tested |
| Lookup tables with a required margin on every train change | `src/tables.cpp` (slack argument) | working |
| Lookup tables, expected time with missed-connection risk | `src/tables_risk.cpp` | experimental: correct per leg, but NOT usable for chaining legs yet (see HANDOFF task 4e) |
| Route optimizer (simulated annealing with reheat cycles) | `src/solve.cpp` | working |
| Direct simulator: itinerary, miss cost per train, Monte Carlo, re-plan | `src/sim.cpp` | working, tested against tables |
| Itinerary + risk report | `src/report.py` | working |
| Phone run sheet (HTML) | `src/make_page.py` | working |
| Monte Carlo robustness | `src/mc.py` | working; delay model is a placeholder |
| Download and replay real past days (subwaydata.nyc) | `src/fetch_history.py`, `src/hist.py`, `src/ingest_subwaydata.py`, `src/replay.py` | working on real files |
| Live re-router | `src/live.py` | skeleton, NOT yet run against the live MTA feed |

## Quick start (long search, e.g. on Codex or a laptop overnight)

```
pip install numpy pandas
./run_search.sh 8            # builds everything from gtfs_subway.zip, then searches for 8 hours
```
Leaderboard: `out/search/leaderboard.csv`. See `AGENTS.md` for the full instructions an agent should follow.

## Quick start (manual)

```
unzip gtfs_subway.zip -d gtfs            # from https://www.mta.info/developers  ("Regular" subway GTFS)
make all GTFS=gtfs SECS=1500             # ~1 h on 2 cores: network, tables, 4 anneals, reports, tests
python3 src/make_page.py out/route_safe.json out/run_sheet.html
```

Needs: g++ with OpenMP, Python 3.10+, numpy, pandas. About 3 GB RAM and 3 GB disk (each table set is 1.1 GB).

## The model in one page

* **Stations.** 472: every GTFS parent station except Staten Island Railway, with 145 St, W 4 St and Queensboro Plaza
  (two GTFS ids each, one per level) merged via `STATION_ALIAS` in `config.py`.
* **"Visited"** means you are on a train that stops there (boarding or alighting counts).
* **Time grid.** GTFS subway times are all multiples of 30 s, so everything runs on 30 s ticks. The weekday timetable is
  treated as cyclic (a weekday follows a weekday), so a run may start at any hour and cross midnight.
* **Atoms.** The physical track graph is cut at decision points ("portals"): terminals, junctions, express stops,
  transfer complexes, and stations within `WALK_PORTAL_CROW_MI` of another line. A chain of stations between two
  portals is an atom: you ride it end to end on trains that stop everywhere. Roosevelt Av -> Forest Hills is one atom.
  Portals that sit between other portals are covered by "hop"/"point" groups (ride any one hop touching them).
* **Route** = an order of atoms, a direction for each, and a start time. Between atoms you "deadhead" by the fastest
  combination of any trains (express included), in-station transfers and street runs.
* **Transfers.** Different platform, same station: `XFER_SAME_STATION` (60 s). Between stations of a complex:
  half the GTFS `min_transfer_time`, at least 60 s. Same platform (e.g. local <-> express): 0 s.
* **Runs.** Crow-fly distance x 1.25, at 10:00/mi for the first mile, 12:00 for the second, 15:00 after, plus 45 s
  for stairs and turnstiles. No run longer than 1.6 crow-fly miles, no run across the East River / Jamaica Bay,
  and no two runs back to back. **Every run the final route uses must be checked on a real map** (see HANDOFF).
* **Two table sets.** `tab/s0` assumes every scheduled connection is made ("fast"). `tab/k4` requires 2 spare minutes
  on every change of trains ("safe"). On the day you still take whatever comes first, so a safe route usually runs
  ahead of its own plan. `mc.py` and the per-train "miss cost" in the report are how the two are compared.
* **Optimizer.** Stage 0 solves a time-independent version (typical leg times, riding straight through costs no wait),
  which gets the geography right in seconds. Stage 1 searches on the real timetable; with `ACCEPT=rrt` it accepts any move
  within a threshold of the best so far (the threshold is what the T arguments mean then), which copes with
  missed-train cliffs far better than Metropolis here. Options served only part-time are dropped.

## Outputs

* `out/best_fast.txt`, `out/best_safe.txt`: start tick, cost, then directed-atom ids in riding order.
* `out/route_*.md` / `.json`: every ride, run and transfer with clock times, margin, and "miss cost"
  (how much later the run finishes if that one train is missed and the order is kept).
* `out/run_sheet.html`: the same for a phone, with tap-to-check-off and ahead/behind plan.

See `docs/HANDOFF.md` for what to do next and what is not finished.
