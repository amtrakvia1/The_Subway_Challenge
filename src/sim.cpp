// Direct (table-free) simulator: rides a fixed atom order on a concrete timetable, in seconds.
// Same rules as tables.cpp, so with the scheduled timetable the two must agree exactly (see tests).
//
//   sim <data_dir> <solution_file> itin  [slack_sec [pos platform sec]] -> legs as TSV on stdout (optionally from a mid-route state)
//   sim <data_dir> <solution_file> miss  [slack_sec]                 -> per boarded train: minutes lost if that train is missed
//   sim <data_dir> <solution_file> mc <samples> <seed> [scale]       -> finish durations (sec) under random delays
//   sim <data_dir> <solution_file> dur   [slack_sec]                 -> just the duration in seconds
//   sim <data_dir> <list_file> mcbatch <samples> <seed> [scale]      -> mc for many routes on the same days (one column each)
//   sim <data_dir> <solution_file> replan <pos> <platform> <now_sec> <window> <iters> [seed]
//        -> you are at <platform> at <now_sec> about to start atom number <pos> (0-based): try reordering the next
//           <window> atoms (local search, <iters> evaluations) and print the best order found (used by live.py)
// Set env TT=<file> to use a concrete timetable instead of the schedule (historical day or live feed):
//   int32 rows [dep_platform, arr_platform, dep_sec, arr_sec, trip_instance, route_code]
#include "common.h"
#include <random>
#include <cmath>
#include <array>

static const int INF = 1 << 30;

struct TT {                      // unrolled timetable, sorted by departure second
  std::vector<int> dp, ap, dep, arr, trip, sched;     // sched = index into net conn (for route names), trip = trip instance
  std::vector<std::vector<int>> tripConns;            // per trip instance: conn indices in riding order
  int ntrip = 0;
};

struct Leg { int kind; int a, b, t0, t1, trip, c0, c1; };   // kind 0 ride(c0..c1 conn idx), 1 same-station, 2 transfer, 3 run ; a,b platforms

struct Sim {
  Net n; TT tt; int S, P;
  int beta, same, slack;               // seconds
  double walkMul = 1.0;
  bool trace = false;
  int banned = -1;                     // trip instance that "does not exist"
  std::vector<int> free_, predC, predK, predFrom, board, onTrip, stamp, tstamp; int cur = 0;
  std::vector<int> hop;                // S*S -> hop index for the atom being ridden
  // atom scratch
  std::vector<int> ridden, rstamp, aboard;

  void init() {
    S = n.S; P = 2 * S;
    free_.assign(P, INF); predC.assign(P, -1); predK.assign(P, 0); predFrom.assign(P, -1); stamp.assign(P, 0);
    board.assign(tt.ntrip, -1); tstamp.assign(tt.ntrip, 0); onTrip.assign(tt.ntrip, 0);
    hop.assign((size_t)S * S, -1); ridden.assign(tt.ntrip, -1); rstamp.assign(tt.ntrip, 0); aboard.assign(tt.ntrip, -1);
  }
  int lower(int t) const { return std::lower_bound(tt.dep.begin(), tt.dep.end(), t) - tt.dep.begin(); }
  inline int& F(int x) { if (stamp[x] != cur) { stamp[x] = cur; free_[x] = INF; predC[x] = -1; predK[x] = 0; predFrom[x] = -1; } return free_[x]; }
  inline void relaxStation(int s, int fromP, int t, int viaConn) {
    auto put = [&](int x, int v, int k) { int& f = F(x); if (v < f) { f = v; predC[x] = viaConn; predK[x] = k; predFrom[x] = fromP; } };
    int other = fromP ^ 1;
    put(other, t + same, 1);
    for (auto& e : n.sx[s]) { int v = t + e.second * n.TICK + slack; put(2 * e.first, v, 2); put(2 * e.first + 1, v, 2); }
    for (auto& e : n.sw[s]) { int v = t + (int)std::ceil(e.second * n.TICK * walkMul) + slack; put(2 * e.first, v, 3); put(2 * e.first + 1, v, 3); }
  }

  // earliest (raw) arrival at platform q from "at platform p at second t"; appends legs if rec
  int deadhead(int p, int t, int q, std::vector<Leg>* rec) {
    if (p == q) return t;
    cur++;
    F(p) = t; predC[p] = -1; predK[p] = 4;
    relaxStation(p / 2, p, t, -1);
    int best = INF, bestConn = -1;
    { int f = F(q); if (f < best) { best = f; bestConn = -2; } }
    int nc = tt.dep.size();
    for (int ci = lower(t); ci < nc; ci++) {
      int d = tt.dep[ci];
      if (d >= best) break;
      int X = tt.trip[ci];
      if (X == banned) continue;
      bool on = (tstamp[X] == cur && onTrip[X]);
      if (!on) {
        int x = tt.dp[ci];
        if (stamp[x] != cur || free_[x] > d) continue;
        tstamp[X] = cur; onTrip[X] = 1; board[X] = ci;
      }
      int y = tt.ap[ci], a = tt.arr[ci];
      if (y == q) { if (a < best) { best = a; bestConn = ci; } continue; }
      int& f = F(y);
      if (a + beta < f) { f = a + beta; predC[y] = ci; predK[y] = 0; predFrom[y] = y; }
      relaxStation(y / 2, y, a, ci);
      { int fq = F(q); if (fq < best) { best = fq; bestConn = -2; } }
    }
    if (best >= INF) return INF;
    if (rec) {
      std::vector<Leg> legs;
      int x; int c;
      if (bestConn >= 0) { c = bestConn; x = -1; }
      else { x = q; c = -3; }
      while (true) {
        if (c >= 0) {                       // ride ending with conn c
          int X = tt.trip[c], b = board[X];
          legs.push_back({0, tt.dp[b], tt.ap[c], tt.dep[b], tt.arr[c], X, b, c});
          x = tt.dp[b]; c = -3;
        }
        // how did we become free at x ?
        int k = predK[x];
        if (k == 4) break;
        if (k == 0) { c = predC[x]; continue; }
        int from = predFrom[x], via = predC[x];
        int tstart = via >= 0 ? tt.arr[via] : t;
        legs.push_back({k, from, x, tstart, free_[x], -1, -1, -1});
        if (via < 0) break;
        c = via;
      }
      for (auto it = legs.rbegin(); it != legs.rend(); ++it) rec->push_back(*it);
    }
    return best;
  }

  // ride a whole atom stopping everywhere. start: at start platform at second t (raw). returns raw arrival at the end platform
  int rideAtom(const DAtom& da, int t, std::vector<Leg>* rec) {
    int k = da.st.size() - 1;
    for (int i = 0; i < k; i++) hop[(size_t)da.st[i] * S + da.st[i + 1]] = i;
    cur++;
    std::vector<int> fr((k + 1) * 2, INF), pc((k + 1) * 2, -1);
    int sl = da.start_p % 2;
    fr[sl] = t; fr[1 - sl] = t + same;
    int best = INF, bestConn = -1, nc = tt.dep.size();
    for (int ci = lower(t); ci < nc; ci++) {
      int d = tt.dep[ci];
      if (d >= best) break;
      int x = tt.dp[ci], y = tt.ap[ci];
      int i = hop[(size_t)(x / 2) * S + y / 2];
      if (i < 0) continue;
      int X = tt.trip[ci];
      if (X == banned) continue;
      bool on = (rstamp[X] == cur && ridden[X] == i - 1);
      if (!on) {
        if (fr[i * 2 + x % 2] > d) continue;
        if (rstamp[X] != cur || ridden[X] < 0 || ridden[X] != i - 1) aboard[X] = ci;
      }
      rstamp[X] = cur; ridden[X] = i;
      int a = tt.arr[ci];
      if (i + 1 == k) {
        int v = (y == da.end_p) ? a : a + same;
        if (v < best) { best = v; bestConn = ci; }
      } else {
        int j = (i + 1) * 2 + y % 2;
        if (a + beta < fr[j]) { fr[j] = a + beta; pc[j] = ci; }
        if (a + same < fr[j ^ 1]) { fr[j ^ 1] = a + same; pc[j ^ 1] = ci; }
      }
    }
    for (int i = 0; i < k; i++) hop[(size_t)da.st[i] * S + da.st[i + 1]] = -1;
    if (best >= INF) return INF;
    if (rec) {
      std::vector<Leg> legs; int c = bestConn;
      while (c >= 0) {
        int X = tt.trip[c];
        // find boarding conn: walk back along the trip while the previous conn is the previous hop
        auto& tc = tt.tripConns[X];
        int pos = std::find(tc.begin(), tc.end(), c) - tc.begin();
        int b = pos;
        // aboard[X] is the conn where we (last) boarded this trip inside the atom
        while (tc[b] != aboard[X] && b > 0) b--;
        int bc = tc[b];
        legs.push_back({0, tt.dp[bc], tt.ap[c], tt.dep[bc], tt.arr[c], X, bc, c});
        int i = 0; for (int q = 0; q < k; q++) if (da.st[q] == tt.dp[bc] / 2) i = q;
        c = pc[i * 2 + tt.dp[bc] % 2];
      }
      for (auto it = legs.rbegin(); it != legs.rend(); ++it) rec->push_back(*it);
    }
    return best;
  }

  // full route. returns finish second (abs); fills legs / atomEnd if given
  int run(const std::vector<int>& seq, int t0, std::vector<Leg>* rec, std::vector<int>* legAtom, int startPos = 0, int startP = -1) {
    int t = t0, p = startP;
    for (size_t i = startPos; i < seq.size(); i++) {
      const DAtom& da = n.datom[seq[i]];
      size_t before = rec ? rec->size() : 0;
      if (p >= 0) { t = deadhead(p, t, da.start_p, rec); if (t >= INF) return INF; }
      if (trace) printf("%zu\t%d\t%d", i, seq[i], t);
      if (rec && legAtom) { legAtom->resize(rec->size(), -1); }
      t = rideAtom(da, t, rec); if (t >= INF) return INF;
      if (trace) printf("\t%d\n", t);
      if (rec && legAtom) { legAtom->resize(rec->size(), (int)i); }
      (void)before;
      p = da.end_p;
    }
    return t;
  }
};

static TT unroll(const Net& n, int days) {
  TT tt; int NC = n.conn.size(); const int DAY = n.NT * n.TICK;
  // a trip instance is identified by (trip, day its first connection departs).
  // conn times were wrapped mod DAY, so find for each conn its offset from the trip's first conn.
  std::vector<int> first(n.NTRIP, -1), off(NC, 0);
  {
    std::vector<char> hasPrev(NC, 0);
    for (int i = 0; i < NC; i++) if (n.conn[i].next >= 0) hasPrev[n.conn[i].next] = 1;
    for (int i = 0; i < NC; i++) if (!hasPrev[i]) {
      first[n.conn[i].trip] = i; int c = i, o = 0;
      while (true) {
        off[c] = o; int nx = n.conn[c].next; if (nx < 0) break;
        int depAbs = n.conn[c].dt * n.TICK + o;              // seconds since trip-day midnight of first conn
        int nd = n.conn[nx].dt * n.TICK;
        int o2 = o; while (nd + o2 < depAbs) o2 += DAY;
        o = o2; c = nx;
      }
    }
  }
  tt.ntrip = n.NTRIP * (days + 1);
  std::vector<std::array<int,6>> rows;
  for (int d = -1; d < days; d++) for (int i = 0; i < NC; i++) {
    const Conn& c = n.conn[i];
    int dep = c.dt * n.TICK + off[i] + d * DAY; if (dep < 0) continue;
    rows.push_back({dep, c.dp, c.ap, dep + (c.at - c.dt) * n.TICK, c.trip + (d + 1) * n.NTRIP, i});
  }
  std::sort(rows.begin(), rows.end());
  for (auto& r : rows) { tt.dep.push_back(r[0]); tt.dp.push_back(r[1]); tt.ap.push_back(r[2]); tt.arr.push_back(r[3]); tt.trip.push_back(r[4]); tt.sched.push_back(r[5]); }
  tt.tripConns.assign(tt.ntrip, {});
  for (size_t i = 0; i < tt.dep.size(); i++) tt.tripConns[tt.trip[i]].push_back(i);
  return tt;
}

// Random delays, fitted to subwaydata.nyc (6 weekdays, ~800k stop events matched to the schedule):
// lateness at a stop  p1 -279 s, p10 -101, p25 -34, p50 +21, p75 +134, p90 +316, p95 +487, p99 +1059
// change per hop      p10 -38 s, p90 +39, p99 +202.     Model: per-trip start offset from a 3-part mixture, then a
// mean-reverting walk with occasional holds.  Fit (src/fit_delays notes in HANDOFF) reproduces those within ~30 s.
static TT perturb(const TT& base, std::mt19937& rng, double scale) {
  const double C0 = 7.8, SD0 = 121.7, PT = 0.078, MT = 356.3, PV = 0.020, MV = 838.4, RHO = 0.959, SE = 27.0, PH = 0.019, MH = 303.5;
  TT tt; tt.ntrip = base.ntrip;
  std::uniform_real_distribution<double> U(0, 1); std::normal_distribution<double> N(0, 1); std::exponential_distribution<double> Ex(1.0);
  int nc = base.dep.size();
  std::vector<int> dep(nc), arr(nc);
  for (int X = 0; X < base.ntrip; X++) {
    auto& tc = base.tripConns[X]; if (tc.empty()) continue;
    double u = U(rng), d;
    if (u < PV) d = MV * Ex(rng); else if (u < PV + PT) d = MT * Ex(rng); else d = C0 + SD0 * N(rng);
    d = C0 + (d - C0) * scale;
    for (int c : tc) {
      dep[c] = base.dep[c] + (int)d;
      double e = SE * N(rng); if (U(rng) < PH) e += MH * Ex(rng);
      d = C0 + RHO * (d - C0) + e * scale;
      arr[c] = base.arr[c] + (int)d; if (arr[c] <= dep[c]) arr[c] = dep[c] + 15;
    }
  }
  std::vector<int> ord(nc); for (int i = 0; i < nc; i++) ord[i] = i;
  std::sort(ord.begin(), ord.end(), [&](int a, int b) { return dep[a] < dep[b] || (dep[a] == dep[b] && a < b); });
  tt.dep.resize(nc); tt.arr.resize(nc); tt.dp.resize(nc); tt.ap.resize(nc); tt.trip.resize(nc); tt.sched.resize(nc);
  for (int i = 0; i < nc; i++) { int o = ord[i]; tt.dep[i] = dep[o]; tt.arr[i] = arr[o]; tt.dp[i] = base.dp[o]; tt.ap[i] = base.ap[o]; tt.trip[i] = base.trip[o]; tt.sched[i] = base.sched[o]; }
  tt.tripConns.assign(tt.ntrip, {});
  for (int i = 0; i < nc; i++) tt.tripConns[tt.trip[i]].push_back(i);
  return tt;
}

int main(int argc, char** argv) {
  if (argc < 4) { fprintf(stderr, "usage: see header of sim.cpp\n"); return 1; }
  Sim s; s.n = loadNet(argv[1]);
  std::ifstream in(argv[2]); int t0tick = 0, c = 0; in >> t0tick >> c; std::vector<int> seq; int x; while (in >> x) seq.push_back(x);
  std::string mode = argv[3];
  const int TICK = s.n.TICK;
  auto setSlack = [&](int sl) { s.slack = sl; s.beta = s.n.XPLAT * TICK + sl; s.same = s.n.XSAME * TICK + sl; };
  TT base;
  if (const char* f = getenv("TT")) {
    auto v = readBin<int32_t>(f); size_t m = v.size() / 6;
    std::vector<int> ord(m); for (size_t i = 0; i < m; i++) ord[i] = i;
    std::sort(ord.begin(), ord.end(), [&](int a, int b) { return v[a * 6 + 2] < v[b * 6 + 2] || (v[a * 6 + 2] == v[b * 6 + 2] && a < b); });
    for (int o : ord) { base.dp.push_back(v[o * 6]); base.ap.push_back(v[o * 6 + 1]); base.dep.push_back(v[o * 6 + 2]); base.arr.push_back(v[o * 6 + 3]);
                        base.trip.push_back(v[o * 6 + 4]); base.sched.push_back(-1); base.ntrip = std::max(base.ntrip, v[o * 6 + 4] + 1); }
    base.tripConns.assign(base.ntrip, {});
    for (size_t i = 0; i < base.dep.size(); i++) base.tripConns[base.trip[i]].push_back(i);
  } else base = unroll(s.n, 3);
  int t0 = t0tick * TICK;
  if (mode == "dur" || mode == "itin" || mode == "miss" || mode == "trace") {
    setSlack(argc > 4 ? atoi(argv[4]) : 0);
    s.tt = base; s.init();
    std::vector<Leg> legs; std::vector<int> la;
    // optional: start mid-route -> itin <slack> <pos> <platform> <sec>
    int sPos = argc > 7 ? atoi(argv[5]) : 0, sPlat = argc > 7 ? atoi(argv[6]) : -1;
    if (argc > 7) t0 = atoi(argv[7]);
    int end = s.run(seq, t0, &legs, &la, sPos, sPlat);
    if (mode == "trace") { s.trace = true; s.run(seq, t0, nullptr, nullptr); return 0; }
    if (mode == "dur") {
      if (getenv("TT")) {        // real day: arrive 10 min early and time from the first train actually boarded
        legs.clear(); la.clear(); end = s.run(seq, t0 - 600, &legs, &la);
        printf("%d\n", end >= INF || legs.empty() ? -1 : end - legs[0].t0); return 0;
      }
      printf("%d\n", end - t0); return 0; }
    if (mode == "itin") {
      printf("#start %d end %d dur %d\n", t0, end, end - t0);
      for (size_t i = 0; i < legs.size(); i++) {
        auto& L = legs[i];
        printf("%d\t%d\t%d\t%d\t%d\t%d\t%d", L.kind, L.a, L.b, L.t0, L.t1, L.kind == 0 ? s.n.conn[s.tt.sched[L.c0]].trip : -1, la[i]);
        if (L.kind == 0) {   // stops made
          auto& tc = s.tt.tripConns[L.trip];
          size_t b = std::find(tc.begin(), tc.end(), L.c0) - tc.begin();
          printf("\t%d@%d", s.tt.dp[tc[b]], s.tt.dep[tc[b]]);
          for (size_t j = b; j < tc.size(); j++) { printf(",%d@%d", s.tt.ap[tc[j]], s.tt.arr[tc[j]]); if (tc[j] == L.c1) break; }
          printf("\t%d", L.trip);
        }
        printf("\n");
      }
      return 0;
    }
    // miss analysis: ban each boarded train in turn
    std::vector<int> trips; for (auto& L : legs) if (L.kind == 0 && (trips.empty() || trips.back() != L.trip)) trips.push_back(L.trip);
    for (int X : trips) { s.banned = X; int e = s.run(seq, t0, nullptr, nullptr); printf("%d\t%d\n", X, e >= INF ? -1 : e - end); }
    return 0;
  }
  if (mode == "mctrace") {     // one delayed day (seed), riding seq from a mid-route state; prints per-atom times
    unsigned seed = atoi(argv[4]); double scale = atof(argv[5]); int pos = atoi(argv[6]), plat = atoi(argv[7]), t = atoi(argv[8]);
    setSlack(0); std::mt19937 rng(seed);
    s.tt = perturb(base, rng, scale); s.init(); s.trace = true;
    int e = s.run(seq, t, nullptr, nullptr, pos, plat);
    if (e >= INF) printf("STUCK\n");
    return 0;
  }
  if (mode == "trace2") {      // schedule trace from a mid-route state
    int pos = atoi(argv[4]), plat = atoi(argv[5]), t = atoi(argv[6]);
    setSlack(0); s.tt = base; s.init(); s.trace = true; s.run(seq, t, nullptr, nullptr, pos, plat); return 0;
  }
  if (mode == "mc") {
    int N = atoi(argv[4]); unsigned seed = atoi(argv[5]); double scale = argc > 6 ? atof(argv[6]) : 1.0;
    setSlack(0);
    std::mt19937 rng(seed); std::normal_distribution<double> Nd(0, 1);
    for (int i = 0; i < N; i++) {
      s.tt = perturb(base, rng, scale); s.init();
      s.walkMul = std::exp(0.06 * Nd(rng) * scale);
      // be on the first platform 10 min early; the clock starts when the first train actually leaves
      std::vector<Leg> lg; std::vector<int> la2;
      int end = s.run(seq, t0 - 600, &lg, &la2);
      printf("%d\n", end >= INF || lg.empty() ? -1 : end - lg[0].t0); fflush(stdout);
    }
    return 0;
  }
  if (mode == "mcbatch") {    // sim <data> <list_file> mcbatch <samples> <seed> [scale]: like mc, for every route listed
    // (one solution file per line) on the SAME simulated days, perturbing each day once. Prints one row per day,
    // one column per route; per route identical to `mc` with the same samples/seed/scale.
    int N = atoi(argv[4]); unsigned seed = atoi(argv[5]); double scale = argc > 6 ? atof(argv[6]) : 1.0;
    std::vector<std::vector<int>> seqs; std::vector<int> starts;
    { std::ifstream L(argv[2]); std::string f;
      while (std::getline(L, f)) { if (f.empty()) continue; std::ifstream r(f); int a, b; std::vector<int> q; int y;
        if (!(r >> a >> b)) { fprintf(stderr, "bad route file %s\n", f.c_str()); return 1; }
        while (r >> y) q.push_back(y); seqs.push_back(q); starts.push_back(a * TICK); } }
    setSlack(0);
    std::mt19937 rng(seed); std::normal_distribution<double> Nd(0, 1);
    for (int i = 0; i < N; i++) {
      s.tt = perturb(base, rng, scale);
      double wm = std::exp(0.06 * Nd(rng) * scale);
      for (size_t k = 0; k < seqs.size(); k++) {
        s.init(); s.walkMul = wm;
        std::vector<Leg> lg; std::vector<int> la2;
        int end = s.run(seqs[k], starts[k] - 600, &lg, &la2);
        printf(k ? "\t%d" : "%d", end >= INF || lg.empty() ? -1 : end - lg[0].t0);
      }
      printf("\n"); fflush(stdout);
    }
    return 0;
  }
  if (mode == "replan") {
    int pos = atoi(argv[4]), plat = atoi(argv[5]), now = atoi(argv[6]), win = atoi(argv[7]), iters = atoi(argv[8]);
    unsigned seed = argc > 9 ? atoi(argv[9]) : 1;
    setSlack(0); s.tt = base; s.init();
    std::mt19937 rng(seed);
    int N = seq.size(), hi = std::min(N, pos + win);
    auto flip = [&](int a) { return s.n.rev[a] >= 0 ? s.n.rev[a] : a; };
    int baseEnd = s.run(seq, now, nullptr, nullptr, pos, plat), best = baseEnd;
    std::vector<int> bestSeq = seq;
    for (int it = 0; it < iters && hi - pos >= 2; it++) {
      std::vector<int> c = bestSeq; int mv = rng() % 4;
      int i = pos + rng() % (hi - pos), j = pos + rng() % (hi - pos);
      if (mv == 0) { if (i == j) continue; int x = c[i]; c.erase(c.begin() + i); if (rng() % 2) x = flip(x); c.insert(c.begin() + j, x); }
      else if (mv == 1) { if (i == j) continue; std::swap(c[i], c[j]); }
      else if (mv == 2) { if (flip(c[i]) == c[i]) continue; c[i] = flip(c[i]); }
      else { if (i > j) std::swap(i, j); if (i == j) continue; std::reverse(c.begin() + i, c.begin() + j + 1); for (int q = i; q <= j; q++) c[q] = flip(c[q]); }
      int e = s.run(c, now, nullptr, nullptr, pos, plat);
      if (e < best) { best = e; bestSeq = c; }
    }
    printf("keep_order_finish %d\nbest_finish %d\nsaved_sec %d\n", baseEnd, best, baseEnd >= INF ? -1 : baseEnd - best);
    printf("order"); for (int i = pos; i < N; i++) printf(" %d", bestSeq[i]); printf("\n");
    std::vector<Leg> legs; std::vector<int> la; s.run(bestSeq, now, &legs, &la, pos, plat);
    int shown = 0;
    for (auto& L : legs) { if (shown++ >= 12) break; printf("leg\t%d\t%d\t%d\t%d\t%d\n", L.kind, L.a, L.b, L.t0, L.t1); }
    return 0;
  }
  fprintf(stderr, "unknown mode\n"); return 1;
}
