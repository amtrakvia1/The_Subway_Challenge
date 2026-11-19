# Instructions for coding agents (Codex, Claude, etc.)

Goal: find a route through all 472 NYC subway stations that beats the Guinness record of 22:14:10 (Kate Jones, 2023)
under realistic delays. Matthew Ahn did 469 stations in 21:28:14 in 2016 (start Rockaway Park 02:02, finish
Flushing-Main St), so a ~21:30 plan that survives real delays is the target. Do NOT force a Flushing finish: since
2025-26, Flushing-bound 7 trains skip 52 St and 69 St, so those must be covered Manhattan-bound.

Read `README.md` (the model) and `docs/HANDOFF.md` (everything tried so far and what it showed) before changing code.

## Setup (Linux, g++ with OpenMP, Python 3.10+ with numpy and pandas; ~4 GB RAM, ~3 GB disk)

    pip install numpy pandas
    ./run_search.sh 0.1 2 120     # 6-minute smoke test: builds network + tables (~2 min), runs 2 short searches

## Main job: long search

    ./run_search.sh <hours> [jobs=nproc] [secs_per_job=1800]

* Runs until the deadline, one solver per job, each 30 min by default. Stop any time (Ctrl-C); rerun to continue.
* Results: `out/search/leaderboard.csv` sorted by `median` = median finish time over 30 simulated days with delays
  fitted to real MTA data (same 30 days for every route, so routes compare fairly). `on_time` = if every train is on
  schedule. `beat_record_days` = how many of the 30 days finish under 22:14:10.
* Best 20 routes: `out/search/top/*.txt`, each with a readable itinerary `*.md` and `*.json` next to the run in
  `out/search/runs/`.
* Each job also returns up to 16 distinct near-best routes (`rNNNNNN_p_K.txt`); all are scored. Routes the solver
  rates exactly equal differ by up to ~1 h in median, so this pool is where most robustness gains come from.
* At the end the top 20 are rescored on 150 simulated days: `out/search/final.csv` (first 30 days are the same as the
  leaderboard's). Prefer it over the leaderboard when medians are within a few minutes. Takes ~3 min after the deadline.
* Log: `out/search/log.txt`.

If the environment limits task length, run in chunks (e.g. `./run_search.sh 1` repeatedly); results accumulate.

## What to report back

The first 10 lines of `out/search/leaderboard.csv`, the best route's itinerary (`out/search/runs/<file>.md`),
and how many jobs ran. Commit `out/search/leaderboard.csv` and `out/search/top/` if asked to save results.

## Rules

* The travel rules exist in three places that must agree: `src/tables.cpp`, `src/sim.cpp`, `tests/pycsa.py`.
  Never change one without the others; check with `python3 tests/test_consistency.py <solution.txt>` (needs tab/s0).
* Do not "improve" scores by loosening assumptions (transfer times in `src/config.py`, the delay model in
  `perturb()` in `src/sim.cpp`) without saying so explicitly; those are calibrated (see HANDOFF).
* Large generated files (tab/, data/, bin/, out/search/runs/) are not committed.

## Good next improvements (see HANDOFF for detail)

1. If many routes finish with similar medians, raise `--samples` in `src/search_driver.py` to separate them.
2. Re-anneal the top 5 for longer from themselves (`elite` jobs do this already; a dedicated pass may help).
3. Build from the MTA "supplemented" GTFS for a specific attempt date to avoid planned work.
