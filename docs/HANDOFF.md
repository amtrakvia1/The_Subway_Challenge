# Handoff: what is done, what is not, what to do next

Written for whoever (person or model) continues this. Read `README.md` first for the model.

## State of things

Verified:
* `tables.cpp`, `sim.cpp` and a pure-Python reference (`tests/pycsa.py`) agree exactly (`make test`).
* `tables_risk.cpp` at risk 0 is byte-identical to `tables.cpp` (`make test-risk`).
* Every route produced is checked to stop at all 475 stations from its concrete train-by-train itinerary.
* Mid-run re-planning (`replan.py`) reproduces the planned finish when you are on time.

Now working on real files: `fetch_history.py`, `hist.py`, `ingest_subwaydata.py`, `replay.py` (35 days downloaded into `hist/`).

NOT verified:
* `live.py` against the live GTFS-realtime feeds.
* All run (street) distances: they are crow-fly x 1.25. See task 2.

Placeholders that drive the results:
* Miss curve `Q0` in `tables_risk.cpp` (experimental, not used for the delivered routes).
* Delay model in `perturb()` in `sim.cpp` (used by `mc.py`).
* Transfer times in `config.py` (60 s same station, half of GTFS between complex stations, 0 s same platform).

The GTFS used for the first results is the Mar-May 2026 weekday schedule from a GitHub mirror. It contains a
long-term change (Flushing-bound 7 skips 52 St and 69 St). Rebuild with the current file before trusting clock times.

## Results so far (user's Nov 2026 - May 2027 weekday GTFS, 472 stations, 45 s per run for stairs)

* Best safe route (`out/best_safe.txt`, 2 min margin on every change): 22:44 if every train is on time; starts 03:40 at
  Rockaway Park. Results differ by 30+ minutes between seeds.
* **Run times are not padded overall.** Over 4 real weekdays, median real departure-to-departure time per hop is 0.998 of
  scheduled in the daytime (1.005 overnight); the 40th percentile is about 4% faster; SD per hop about 30 s. The padding
  is concentrated in holds before terminals (e.g. Sutphin Blvd -> Parsons Blvd: 510 s scheduled, 92 s real).
* **Real days are dominated by planned work, not delays.** Replaying fixed-order routes on 20 real weekdays
  (12 Oct - 12 Nov 2026) gave 30+ hours every day. Each day some segment had no stopping service in the planned direction
  for hours: midday (about 10:00-15:00) on the 7 east of Junction Blvd and the F between Church Av and W 8 St; late night
  on the 6 south of Hunts Point, 4 at 138 St-Grand Concourse, 3 north of 135 St; the Lefferts branch had no trains at
  all on 9-12 Nov. The overnight Rockaway shuttle also looks different from the schedule (may be a feed gap: unverified).
  A fixed-order rider waits for the work to end; a real rider would re-plan.

What follows from that (new top priorities, ahead of the list below):
  A. Build the route from the timetable of the actual attempt date. The MTA publishes a "supplemented" GTFS with planned
     work for the coming days; `build_network.py` needs to select services by date (calendar_dates) instead of the single
     `Weekday` service id.
  B. Make `replay.py` fair: either re-plan when a segment is blocked (call the `replan` engine inside the replay), or
     build the network from each real day (`hist.py` already loads them) and solve on it as a hindsight bound.
  C. Check whether the overnight Rockaway shuttle gap is real or missing feed data.

## Tasks, in priority order

1. **Rebuild on the current GTFS.** `make all GTFS=<dir>`. Check the printed counts: 475 stations, ~160 groups.
   If `build_network.py` asserts, a new service pattern broke the chain logic; print the offending station.

2. **Validate every run in the chosen route on a map.** `out/route_safe.md` lists each RUN with assumed street miles.
   Replace bad ones: add a `WALK_OVERRIDE = {('A', 'B'): seconds}` dict to `config.py`, apply it in
   `build_network.py` where `walk[(i, j)]` is set, rebuild tables, re-solve. Also add station-pair bans for runs that are
   not physically reasonable (bridges without walkways, highways). Known examples to check first: anything across the
   Harlem River, 138 St-Grand Concourse <-> Harlem-148 St, Wakefield-241 St <-> Eastchester-Dyre Av.

3. **Per-station transfer overrides.** Same idea: `XFER_OVERRIDE` for cross-platform transfers that are really 15-30 s
   and for long ones (Times Sq <-> 42 St-PABT, Court Sq, 14 St 6 Av/7 Av) that half-of-GTFS underestimates.
   Terminal turnbacks: if the arriving train itself goes back out, the 60 s `XFER_SAME_STATION` is conservative.

4. **Calibrate from history (the big one).** Download 6-8 weeks of weekdays from subwaydata.nyc.
   a. `ingest_subwaydata.py` -> one `.tt` per day; `replay.py` gives "this route would have beaten the record on X of N
      days". This is the real robustness number; use it to choose between candidate routes.
   b. Run-time distributions: for each (from_stop, to_stop, hour) take actual departure->arrival seconds. Write the
      median (or 40th percentile) back as the connection run time instead of the padded GTFS value (rebuild `conn.bin`
      with realistic times, keeping scheduled departure times at the trip origin and for headway >= 10 min).
   c. Miss curve: for scheduled connections of margin m between trains A and B at a station, measure how often
      actual_arrival(A) + transfer > actual_departure(B). Replace `Q0` in `tables_risk.cpp`, ideally one curve for
      rush hour, one for midday, one for overnight.
   d. Headway-based periods: when headway <= 6 min the clock time of a given train is noise. Replace those trains in
      `conn.bin` by evenly spaced "typical" trains or, better, compute the risk tables with a wait drawn from the
      observed headway distribution. Keep the literal schedule when headway >= 10 min (overnight, shuttles, Rockaways).

   e. Risk tables: `tables_risk.cpp` computes expected leg times with a miss model, but chaining expected (non-schedule)
      times through the tables breaks "stay on the same train" at leg boundaries and inflates totals by hours.
      Fix: have it output two numbers per entry, the nominal (all connections made) duration and the expected extra
      delay; advance the clock by the nominal value and add the penalties to the objective in `solve.cpp`.

5. **Live tool.** The engine exists: `replan.py` (re-orders everything left from where you stand, 10-15 s on a laptop).
   Still to build: (i) wrap `replan.py` in a tiny web server (Flask) on a laptop or small VM so the phone page can
   call it; (ii) `live.py`: finish and test the GTFS-realtime merge, then use the live timetable for the next 30-45 min
   and the risk tables beyond that; (iii) trip matching between feed and schedule to avoid duplicate trains.
   Artifact pages cannot fetch other hosts, so the phone page itself cannot read MTA feeds; that is why Plan B
   itineraries are pre-computed and embedded instead (`planb.py`).

6. **Better optimization.** Results vary by seed by more than an hour; the landscape is rugged.
   Cheap wins: run 8-16 seeds overnight (`SECS=3600`), keep the best three, re-anneal each on `tab/r1`.
   Ideas: (a) or-opt with exhaustive best-insertion; (b) a population / path-relinking layer over the anneal;
   (c) lower `WALK_PORTAL_CROW_MI` to 0.2 to shrink the search, or raise to 0.4 for more options;
   (d) optimize directly on replayed historical days once task 4 exists (sample 5 days, minimize the 80th percentile).

7. **Smaller things.** Buses are allowed between stations under Guinness rules and are not modelled. The 475 vs 472
   station question: find which three GTFS stops the MTA merges and decide whether skipping any saves time (probably not).
   Saturday/Sunday timetables are not supported in the cyclic model (a Monday 1 AM start uses Sunday-night trains).

## File formats

* `out/*.txt` solution: line 1 `start_tick cost_ticks` (30 s ticks), then one directed-atom id per line.
* `data/net.json`: `stations[i]`, `datoms[id] = {atom, dir, stations[], start_p, end_p}`, `groups[]`.
  Platform id = `2 * station_index + (0 for N, 1 for S)`.
* `tab/X_D.bin` uint16 `[n_end_platforms][n_start_platforms][2880]`, `tab/X_A.bin` uint16 `[n_datoms][2880]`.
* `.tt` timetable: int32 rows `[dep_platform, arr_platform, dep_sec, arr_sec, trip_instance, route_code]`.

## Prompt to paste for the next model

> You are continuing an NYC subway all-stations record planner. Unpack the tarball, read README.md and
> docs/HANDOFF.md fully, then run `make build && make network GTFS=<dir> && make tables && make test` to confirm the
> three implementations still agree. Do not change the travel rules in one of tables.cpp / sim.cpp / tests/pycsa.py
> without changing all three and re-running the tests. Then work through the HANDOFF task list in order, starting
> with task 1 (current GTFS) and task 4 (subwaydata.nyc calibration). After any change that affects routes, re-run
> `make solve report` and report plan time, Monte Carlo median and the worst miss cost for the safe route.

## Late addition: margin by headway (`bin/tables data -1 tab/hw`)
Margin demanded before boarding = 30 s if the following train is < 3.5 min behind, up to 4 min if 15+ min behind.
Result: plan 22:10-22:12 (flat 2 min margin: 22:44), but under the placeholder delay model the median is 24:54
versus 23:51 for the flat-margin route. Thin margins on frequent lines still cascade into infrequent connections later.
Next thing to try: scale the margin by the miss cost downstream (the `miss` output of sim), not by the local headway.
`out/best_headway.txt` is that route. Where the 22:44 route's time goes: 11:00 new track, 5:49 repeat track,
3:24 waiting, 1:51 running, 0:40 platform changes; repeat track is the largest reducible item.

## Experiments on 17 Nov (all on tab/k4, 4-5 minute searches)
* 24 candidates in out/candidates.csv: on-time 22:43 to 24:00, median about 23:15. Best all-round: k4_705 (now out/best_safe.txt).
* More exit points (WALK_PORTAL_CROW_MI=0.45 -> 283 portals, 176 groups, 1.65 GB table): 23:41 and 24:03 on two seeds. Not better
  at equal search time. The env var WALK_PORTAL_CROW_MI is kept for retesting with longer searches.
* Continuing a finished route with more search made it slower on time (the k4 objective improved, the zero-margin replay did not).
* First stage now runs 6 short static anneals and keeps the one that is best on the real timetable: 23:19 and 23:29 on two seeds, i.e. no
  visible gain on a tiny sample.
Conclusion: the limit is search quality on the timetable stage, not model freedom. Ideas not yet tried: or-opt with exhaustive
best insertion; time-of-day buckets in the static stage; a population of routes with crossover.

## 17 Nov morning: best-insertion polish + model floor
* solve.cpp now runs an exhaustive best-insertion polish (blocks of 1-3 segments, every position, both directions, plus
  direction flips) on the best route at every restart and at the end. Set NOPOLISH=1 to disable. The current best route
  (k4_705) is already locally optimal for it.
* Two 500 s searches on tab/k4 with polish: 22:44 and 23:38 on time. No breakthrough.
* Zero-margin searches (tab/s0) with polish: 21:51 and 21:56 on time. So the model's paper floor is about 21:50, only
  ~23 min under the record, and a flat 2-minute margin costs ~50 min. The record therefore needs margin only where a miss
  is expensive. Top priority now: margin by downstream miss cost (put margin on the ~20 connections whose miss cost is
  high, zero elsewhere), e.g. iterate: solve on s0 -> sim `miss` -> add per-connection slack for expensive trains -> re-solve.
* src/score.py scores existing solution files into out/candidates.csv (use it when a search is cut off before scoring).

## 17 Nov late morning: real delay model, targeted margins, re-planning rider

**Delay model fitted to real data (now the default in bin/sim `mc`).** 6 weekdays of subwaydata.nyc matched to the schedule by
trip id (~800k stop events). Lateness at a stop: p1 -4:39, p10 -1:41, p25 -0:34, median +0:21, p75 +2:14, p90 +5:16, p99 +17:39.
Per hop change: p10 -38 s, p90 +39 s, p99 +202 s. 10% of departures are 1:40+ EARLY, which the old placeholder ignored.
Model: per-trip start offset (3-part mixture) + mean-reverting walk with occasional holds; parameters in perturb() in sim.cpp.
Caveat: planned-work days are included and may inflate the late tail.

**Targeted margins (src/iterate_margins.py + tables mode -2 / SLACKMAP).** 6 rounds starting from the 21:51 zero-margin route:
margin is required only where the planned train is expensive to miss (>=10 min -> 1 min margin, >=20 min -> 2 min).
Did not converge: each new route has new tight spots, windows grew to 674, delay medians 25:09-27:13. Produced the best
on-time route so far, out/iter/it4_1.txt at 21:31 (median under delays ~25:50).

**Rescoring all ~40 routes on the real delay model (src/rescore.py, out/rescored.csv):** best is still k4_705
(on time 22:43, median 24:02, p10 23:28). No route beat 22:14:10 in 30 simulated days.

**Re-planning rider (src/adaptive_mc.py).** When >4 min behind plan, the rider considers keep / re-plan-on-s0 / re-plan-on-k4
and picks the order with the best mean over 6 sampled futures. Lessons: re-planning on the margin tables picks slower orders;
re-planning on the schedule picks fragile orders that collapse; choosing by sampled futures fixes both. Result on 4 days:
k4_705 23:45 both fixed and adaptive; it4_1 25:52, s0_1101 25:57 adaptive. Re-planning does not rescue fast fragile routes.

**Conclusion and next step.** Under realistic delays the robust route is ~1.5 h off the record, and the zero-margin floor of
this model is ~21:30. Kate Jones's 22:14 suggests her plan was near 21:30 AND robust; our fast plans are not robust and our
robust plans are not fast. Most promising next step: optimise directly on the robust objective, i.e. score candidate routes
in the search by a cheap delay-aware proxy (sum over connections of P(miss | margin, early/late distribution above) x
local loss = wait for the next train), instead of either flat margins or zero margins. Second: check whether the delay tail is
inflated by planned-work days (refit on days without supplemented service).

## 17 Nov early afternoon: delay-aware search (PEN) and in-between margins
* Delay model refit on clean trips only (89% of trains, ran their scheduled pattern): unchanged (median +19 s, 10.4% > 5 min
  late, 10% > 1:42 early). Planned work was not inflating it.
* Flat 1 min (tab/k2) and 1.5 min (tab/k3) margins, one seed each: real-model medians 24:13 and 24:43 (k4_705: 24:02).
* `PEN=<w>` env in solve adds an expected-delay penalty per change between segments: for relative lateness of 1/2/4/8 min
  (probabilities 0.109/0.128/0.122/0.083 from the fitted model) the extra time to FINISH the next segment, times w.
  Exact incremental bookkeeping (cumulative penalty arrays), checked drift-free with -DCHECK.
  - on tab/s0 (no margin): on time 22:18 / 24:09, medians 26:12 / 26:27  -> worse than flat margins
  - on tab/k4 + PEN=1: on time 23:07 / 23:29, medians 24:18 / 24:30      -> same as flat margins
  Why: the penalty treats each connection's lateness as independent; in reality a miss makes you late for everything after,
  and a flat margin gives the slack to catch up. A better proxy would carry a lateness state forward through the route
  (e.g. expected lateness after each segment = f(lateness before, margin, headway)) instead of resetting it each change.
* Plateau: every approach so far lands at a real-model median of ~24:00 (best 23:45-24:02). The record needs ~1.5 h more.

Most valuable next input: the user's own attempt logs (station-by-station times). Replaying the user's actual route through
bin/sim with the delay model would show whether the simulator is too pessimistic, which would change every conclusion above.

## 17 Nov night: tighter transfers (env XFER_FACTOR / XFER_MIN / XFER_SAME_STATION, network in data_t/)
Tight variant: 35% of GTFS min_transfer_time (>= 30 s), 30 s to change platforms in the same station.
* + 2 min margin (tab/t4): on time 22:30 / 23:19, real-model medians 25:07 / 24:19
* + 1 min margin (tab/t2): on time 22:19 / 22:29, real-model medians 25:18 / 24:55
No better than the default model (k4_705: 22:43 on time, 24:02 median). Transfer time is not the bottleneck; robustness under
delays is. Rescore with DATA=data_t for routes built on data_t (datom ids differ between networks).

## 18 Nov after midnight: cascade-aware objective, loss diagnostic, simulator start fix
* `CASCADE=<w>` env in solve (use with NOPOLISH=1, ~3k evals/s): cost = on-time duration + w x sum over changes of
  P(delay k) x (how much later the WHOLE route finishes if that change is hit by a 2/4/10/25 min delay, following the fixed
  order through the rest of the route; absorbed delays cost 0). On k4_705 it predicts 23:58 vs simulated 24:02, so it
  tracks the simulator for ordinary routes, but optimizing it gets exploited (optimizer's curse): best searched routes
  promise ~23:40 and simulate at 25:27-32:47. Single injected delays miss interactions between many simultaneous ones.
* Loss diagnostic for k4_705 (30 simulated days, 80 min median lateness gained): biggest single loss was the FIRST segment
  (Far Rockaway -> Broad Channel 03:14, 11.7 min avg, >10 min on 53% of days); everything else is spread thinly over the
  day (2-10 min per hour), no concentration late at night. So reordering fragile lines to the end will not help much.
* Simulator fix: `mc` mode had the rider arrive exactly at the first train's planned time, so an early first departure
  meant a 20 min overnight wait. Now the rider is 10 min early and the clock starts at the first actual departure (as the
  real-day replay already did). Medians after the fix: k4_705 23:46, k4_501 23:54, k4_601 24:00, k4pen_152 24:05.

## 18 Nov: setup for long unattended search (Codex / laptop)
* `./run_search.sh <hours> [jobs] [secs]` builds from the bundled `gtfs_subway.zip` and runs `src/search_driver.py`.
* New solver options: `START_ATOMS` / `END_ATOMS` (comma-separated directed-atom ids). The driver fixes the start to the
  Rockaways 00:00-04:00 and leaves the finish free. A Flushing finish (both of Ahn's records) is ruled out now: Flushing-bound
  7s skip 52 St and 69 St, so those stops need a Manhattan-bound ride. and `SHARED_TABLES=1`
  (parallel solvers share one copy of the tables in memory).
* Research: Ahn 2016 did 469 stations in 21:28:14 with real delays (start Rockaway Park 02:02, finish Flushing). That is
  about this model's best perfect-connection plan, so the main gap is plan quality (search), not delays. Every search so
  far was 5-8 minutes, with 30+ min spread between seeds.
* `seeds/` holds the best existing routes; the driver scores them first so elite restarts have material.

## 18 Nov evening: 4 h search, then search improvements (results/search-2026-11-18*, 2 cores)
* 4 h unattended search (14 jobs x 30 min): nothing beat k4_705 (median 23:46); no route beat 22:14:10 on any of 30 days.
  Elite restarts on the same table returned the same route or a duplicate (r023322 == k4_705). Fastest on-time plan
  found: r023311, 21:15 (s0), median 25:09.
* **Key finding: the table objective cannot tell routes apart that the delay model can.** Routes with exactly the same
  k4 cost (same on-time finish with 2 min margins) differ by up to ~1 h in median (one 15 min job: 23:46 to 24:42 across
  9 equal-cost routes). The solver used to keep one of them arbitrarily.
* Changes (solve.cpp: new env options only; travel rules, transfer times and delay model untouched; consistency test passes):
  - `POOL=<prefix>` (+ `POOL_N`, `POOL_MARGIN`, `POOL_POLISH_SECS`): at the end of each reheat cycle the cycle's state is
    polished (time-capped) and archived; distinct near-best routes are written to `<prefix>_<i>.txt`. Costs ~10 s per job.
  - `KICK=<k>` (+ `KICK_MAX`, default 60 ticks): bounded random walk applied to a loaded init route, so elite restarts
    explore a neighbouring basin. Unbounded kicks were useless (one move can miss a last train: +10 h).
  - search_driver.py: scores every pool route, skips duplicates, `cross` jobs (k4 anneal from the 5 fastest on-time plans),
    final rescore of the top 20 on 150 days -> out/search/final.csv. Defaults: --pool 16, --s0-frac 0.15, --cross-frac 0.1.
* 2 h test with the new driver (6 jobs): no new best (best new r040592, median 23:55 on 150 days). Per job, the best pool
  route beat the job's main route in all 5 k4 jobs (by 6-30 min) but not reliably in s0 jobs (pools of equal-cost
  zero-margin routes are fragile in different ways). Cross jobs were poor (24:49, 24:56). On 150 days k4_705 is 23:47,
  p90 24:45, beats the record on 1 day in 150.
* Caution: median alone hides fragile tails. A pool route tied k4_705 on median (23:47) but had p90 31:59. Check p90 in
  final.csv before choosing a route.
* Next ideas: (1) search the plateau of equal-k4-cost routes directly for the best median (e.g. a driver loop that takes
  a top route, generates equal-cost neighbours with the solver at low threshold, scores them on 30 days, keeps the best);
  (2) rank by a tail-aware score (median + 0.25 x (p90 - median)); (3) for choosing an attempt date: build per-date
  networks from the supplemented GTFS and compare dates by the best route's median.
