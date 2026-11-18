// Simulated annealing over the order/direction of atoms, evaluated on the D/A tables.
// usage: solve <data_dir> <table_prefix> <seconds> <seed> <out_file> [init_file|-] [T0] [T1] [cycle_sec] [T_reheat]
// First a normal anneal T0->T1, then repeated short re-anneals (T_reheat->T1) that each restart from the best so far.
// out file: line 1 "t0_tick cost_ticks", then one directed-atom id per line (in riding order)
#include "common.h"
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <random>
#include <chrono>
#include <cmath>

static const uint16_t* mapFile(const std::string& f, size_t& n) {
  int fd = open(f.c_str(), O_RDONLY); if (fd < 0) { perror(f.c_str()); exit(1); }
  struct stat st; fstat(fd, &st); n = st.st_size / 2;
  if (getenv("SHARED_TABLES")) {   // let N parallel solvers share one copy of the tables via the page cache
    void* q = mmap(nullptr, st.st_size, PROT_READ, MAP_SHARED | MAP_POPULATE, fd, 0);
    if (q == MAP_FAILED) { perror("mmap"); exit(1); }
    close(fd); return (const uint16_t*)q;
  }
  size_t len = ((size_t)st.st_size + (2u << 20) - 1) & ~((size_t)(2u << 20) - 1);
  void* p = mmap(nullptr, len, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
  if (p == MAP_FAILED) { perror("mmap"); exit(1); }
  madvise(p, len, MADV_HUGEPAGE);
  size_t off = 0; while (off < (size_t)st.st_size) { ssize_t r = read(fd, (char*)p + off, std::min((size_t)st.st_size - off, (size_t)1 << 28)); if (r <= 0) { perror("read"); exit(1); } off += r; }
  close(fd);
  return (const uint16_t*)p;
}

struct Solver {
  Net n; const uint16_t *D, *A; int NT, ntgt;
  std::vector<int> sI, eI;      // per datom: target idx of start platform, source idx of end platform
  int fixSrc = -1;              // >=0: route starts at this source-platform index at a fixed time (mid-run re-plan)
  inline int firstLeg(int a, int t0) const {   // ticks to finish the first atom from the start state
    int d0 = 0;
    if (fixSrc >= 0) { d0 = D[((size_t)fixSrc * ntgt + sI[a]) * NT + t0 % NT]; if (d0 == 65535) return 65535; }
    int d = A[(size_t)a * NT + (t0 + d0) % NT]; return d == 65535 ? 65535 : d0 + d;
  }
  static constexpr int BAD = 1 << 28;

  // elements are directed atom ids
  // Delay penalty (env PEN = weight, 0/unset = off). At each change between atoms, arriving 1/2/4/8 min late (relative to the
  // connecting train) happens with the probabilities below (fitted to subwaydata.nyc); the penalty is the expected delay this
  // causes at the start of the next atom, i.e. lateness that is NOT absorbed by waiting, including a missed train's wait.
  double lam = 0; static constexpr int DK[4] = {2, 4, 8, 16}; static constexpr double WK[4] = {0.109, 0.128, 0.122, 0.083};
  inline int pen(int cur, int a, int T) const {   // expected extra time to FINISH atom a if you are delta late at T
    if (lam <= 0) return 0;
    const uint16_t* row = &D[((size_t)cur * ntgt + sI[a]) * NT]; const uint16_t* ar = &A[(size_t)a * NT];
    auto fin = [&](int t) -> int { int d = row[t % NT]; if (d == 65535) return -1; int x = ar[(t + d) % NT]; return x == 65535 ? -1 : d + x; };
    int base = fin(T); if (base < 0) return 0; double acc = 0;
    for (int k = 0; k < 4; k++) { int f2 = fin(T + DK[k]); acc += WK[k] * (f2 < 0 ? 240 : std::max(0, f2 - base + DK[k])); }
    return (int)std::lround(lam * acc);
  }
  // Cascade-aware objective (env CASCADE = weight). For every change between segments, inject a delay of 2/4/10 min
  // (probabilities 0.128/0.122/0.083 from the real-data model) and follow it through the REST of the route in this
  // order; the cost is how much later the whole route finishes. Absorbed delays rejoin the on-time timeline and cost 0.
  double casc = 0; static constexpr int CK[4] = {4, 8, 20, 50}; static constexpr double CW[4] = {0.128, 0.122, 0.065, 0.018};
  int evalRaw(const std::vector<int>& seq, int t0, std::vector<int>* tt) const {
    int t = t0; int a = seq[0]; int d = firstLeg(a, t0); if (d == 65535) return BAD;
    t += d; int cur = eI[a]; if (tt) (*tt)[0] = t;
    for (size_t i = 1; i < seq.size(); i++) {
      a = seq[i]; d = D[((size_t)cur * ntgt + sI[a]) * NT + t % NT]; if (d == 65535) return BAD; t += d;
      d = A[(size_t)a * NT + t % NT]; if (d == 65535) return BAD; t += d; cur = eI[a]; if (tt) (*tt)[i] = t;
    }
    return t - t0;
  }
  int evalCascade(const std::vector<int>& seq, int t0) const {
    int N = seq.size(); std::vector<int> tt(N);
    int dur = evalRaw(seq, t0, &tt); if (dur >= BAD) return BAD;
    double extra = 0;
    for (int i = 1; i < N; i++) for (int k = 0; k < 4; k++) {
      int t = tt[i - 1] + CK[k], cur = eI[seq[i - 1]], j = i, x = 0;
      for (; j < N; j++) {
        int a = seq[j]; int d = D[((size_t)cur * ntgt + sI[a]) * NT + t % NT]; if (d == 65535) { x = 2880; break; }
        t += d; d = A[(size_t)a * NT + t % NT]; if (d == 65535) { x = 2880; break; }
        t += d; cur = eI[a];
        if (t <= tt[j]) { x = 0; break; }               // absorbed: back on the planned timeline
      }
      if (j == N) x = t - tt[N - 1];
      extra += CW[k] * x;
    }
    return dur + (int)std::lround(casc * extra);
  }
  // Fixed endpoints (env START_ATOMS / END_ATOMS = comma-separated directed-atom ids): a route that does not start / end
  // with one of them pays a one-day penalty, so the search treats it as infeasible but can still pass through it.
  std::vector<char> okStart, okEnd;
  inline int endPen(const std::vector<int>& seq) const {
    int p = 0;
    if (!okStart.empty() && !okStart[seq[0]]) p += 2880;
    if (!okEnd.empty() && !okEnd[seq.back()]) p += 2880;
    return p;
  }
  inline int eval(const std::vector<int>& seq, int t0) const {
    if (casc > 0) { int c = evalCascade(seq, t0); return c >= BAD ? BAD : c + endPen(seq); }
    return evalPlain(seq, t0) + endPen(seq);
  }
  inline int evalPlain(const std::vector<int>& seq, int t0) const {
    int t = t0, tk = t0 % NT;
    int a = seq[0];
    int d = firstLeg(a, t0); if (d == 65535) return BAD;
    t += d; int cur = eI[a]; (void)tk;
    int P = 0;
    for (size_t i = 1; i < seq.size(); i++) {
      a = seq[i]; tk = t % NT;
      d = D[((size_t)cur * ntgt + sI[a]) * NT + tk]; if (d == 65535) return BAD;
      P += pen(cur, a, t);
      t += d; tk = t % NT;
      d = A[(size_t)a * NT + tk]; if (d == 65535) return BAD;
      t += d; cur = eI[a];
    }
    return t - t0 + P;
  }
  // Incremental: `old` = times after each position of the current solution `oseq`.
  // Candidate `seq` differs from `oseq` only in positions [f, l]. Writes candidate times to `ct` for
  // positions f..(return stop), where `stop` is the first position whose time matches the old one
  // (everything after is unchanged) or N-1.  Returns total duration (BAD if infeasible).
  // ocp/ccp: cumulative penalty after each position (old solution / candidate)
  inline int evalInc(const std::vector<int>& seq, int t0, const std::vector<int>& old, int oldT0, int f, int l,
                     std::vector<int>& ct, int& stop, const std::vector<int>& ocp, std::vector<int>& ccp) const {
    int N = seq.size(); int t, cur; int i = f; int P;
    if (f == 0) {
      int a = seq[0]; int d = firstLeg(a, t0); if (d == 65535) return BAD;
      t = t0 + d; cur = eI[a]; ct[0] = t; ccp[0] = 0; P = 0; i = 1;
      if (l < 0 && t == old[0]) { stop = 0; return old[N - 1] - t0 + ocp[N - 1]; }
    } else { t = old[f - 1]; cur = eI[seq[f - 1]]; P = ocp[f - 1]; }
    for (; i < N; i++) {
      int a = seq[i];
      int d = D[((size_t)cur * ntgt + sI[a]) * NT + t % NT]; if (d == 65535) return BAD;
      P += pen(cur, a, t);
      t += d;
      d = A[(size_t)a * NT + t % NT]; if (d == 65535) return BAD;
      t += d; cur = eI[a]; ct[i] = t; ccp[i] = P;
      if (i > l && t == old[i]) { stop = i; return old[N - 1] - t0 + P + (ocp[N - 1] - ocp[i]); }
    }
    stop = N - 1; (void)oldT0;
    return t - t0 + P;
  }
  void times(const std::vector<int>& seq, int t0, std::vector<int>& tt, std::vector<int>& cp) const {
    int t = t0 + firstLeg(seq[0], t0); int cur = eI[seq[0]]; tt[0] = t; cp[0] = 0; int P = 0;
    for (size_t i = 1; i < seq.size(); i++) { int a = seq[i]; P += pen(cur, a, t); t += D[((size_t)cur * ntgt + sI[a]) * NT + t % NT]; t += A[(size_t)a * NT + t % NT]; cur = eI[a]; tt[i] = t; cp[i] = P; }
  }
  // best start tick for a fixed order (exhaustive), also strips initial waiting
  int w0 = 0, w1 = 1 << 30;     // allowed start-tick window (within the day)
  inline bool inWin(int t) const { t = (t % NT + NT) % NT; return w0 <= w1 ? (t >= w0 && t <= w1) : (t >= w0 || t <= w1); }
  int bestStart(const std::vector<int>& seq, int& t0) const {
    int best = BAD, bt = 0;
    for (int t = 0; t < NT; t++) { if (!inWin(t)) continue; int c = eval(seq, t); if (c <= best) { best = c; bt = t; } }
    // latest start with same finish => no waiting at the first platform
    while (inWin(bt + 1) && eval(seq, (bt + 1) % NT) == best - 1) { bt = (bt + 1) % NT; best--; }
    t0 = bt; return best;
  }
};

int main(int argc, char** argv) {
  if (argc < 6) { fprintf(stderr, "usage: solve data_dir table_prefix seconds seed out [init|-] [T0] [T1] [cycle_sec] [T_reheat] [start_platform|-1 start_tick] [win_from_tick win_to_tick]\n"); return 1; }
  Solver s; s.n = loadNet(argv[1]);
  std::string pre = argv[2]; double secs = atof(argv[3]); unsigned seed = atoi(argv[4]); std::string out = argv[5];
  std::string init = argc > 6 ? argv[6] : "-";
  double T0 = argc > 7 ? atof(argv[7]) : 5.0, T1 = argc > 8 ? atof(argv[8]) : 0.12;
  double cyc = argc > 9 ? atof(argv[9]) : 120, Tr = argc > 10 ? atof(argv[10]) : 0.9;   // after the first anneal: reheat cycles from the best
  int fixP = argc > 11 ? atoi(argv[11]) : -1, fixT = argc > 12 ? atoi(argv[12]) : 0;   // re-plan: start platform id and tick
  if (argc > 14) { s.w0 = atoi(argv[13]); s.w1 = atoi(argv[14]); }                    // start window in ticks
  size_t nd, na; s.D = mapFile(pre + "_D.bin", nd); s.A = mapFile(pre + "_A.bin", na);
  Net& n = s.n; s.NT = n.NT; s.ntgt = n.tgtP.size();
  int NA = n.datom.size(), NG = n.group.size(), NT = n.NT;
  s.sI.resize(NA); s.eI.resize(NA);
  for (int i = 0; i < NA; i++) { s.sI[i] = n.tgtIdx[n.datom[i].start_p]; s.eI[i] = n.srcIdx[n.datom[i].end_p]; }
  if (fixP >= 0) { s.fixSrc = n.srcIdx[fixP]; if (s.fixSrc < 0) { fprintf(stderr, "start platform is not the end of any atom\n"); return 1; } }
  // Drop options that only have part-time service (e.g. a hop that exists only on a few rush-hour trains): a route that
  // needs one of those is one delay away from waiting until tomorrow. Keep them only if the group has nothing else.
  { int dropped = 0;
    for (auto& g : n.group) {
      std::vector<int> keep;
      for (int o : g) { int mx = 0; for (int t = 0; t < NT; t++) mx = std::max<int>(mx, s.A[(size_t)o * NT + t]); if (mx <= 180) keep.push_back(o); }
      if (!keep.empty() && keep.size() < g.size()) { dropped += g.size() - keep.size(); g = keep; }
    }
    fprintf(stderr, "dropped %d part-time options\n", dropped); }
  for (auto pr : {std::make_pair("START_ATOMS", &s.okStart), std::make_pair("END_ATOMS", &s.okEnd)}) if (getenv(pr.first)) {
    pr.second->assign(NA, 0); std::stringstream ss(getenv(pr.first)); std::string tok;
    while (std::getline(ss, tok, ',')) if (!tok.empty()) (*pr.second)[atoi(tok.c_str())] = 1;
    fprintf(stderr, "%s set\n", pr.first); }
  if (getenv("CASCADE")) { s.casc = atof(getenv("CASCADE")); fprintf(stderr, "cascade weight %.2f\n", s.casc); }
  if (getenv("PEN")) { s.lam = atof(getenv("PEN")); fprintf(stderr, "delay penalty weight %.2f\n", s.lam); }
  std::mt19937 rng(seed);
  auto rnd = [&](int k) { return (int)(rng() % (unsigned)k); };
  auto uni = [&]() { return (rng() >> 8) * (1.0 / 16777216.0); };

  // solution: order of groups, chosen option (directed atom) per position
  std::vector<int> grp(NG), seq(NG); int t0 = 0;
  std::vector<int> optOfGroup;   // helper
  auto flip = [&](int g, int a) {   // opposite direction of atom a if that is also an option of group g
    int r = n.rev[a]; if (r < 0) return a;
    for (int o : n.group[g]) if (o == r) return r;
    return a;
  };

  bool loaded = false;
  if (init != "-" && init != "static") {
    std::ifstream in(init); int c; std::vector<int> v; int x;
    if (in >> t0 >> c) { while (in >> x) v.push_back(x); }
    if (fixP >= 0 && !v.empty() && (int)v.size() < NG) { NG = v.size(); grp.resize(NG); seq.resize(NG); t0 = fixT; }
    if (fixP >= 0) t0 = fixT;
    if ((int)v.size() == NG) {
      // map each directed atom to a distinct group containing it
      int NGall = n.group.size(); std::vector<char> used(NGall, 0); bool ok = true;
      for (int i = 0; i < NG && ok; i++) {
        int found = -1;
        for (int g = 0; g < NGall; g++) if (!used[g] && std::find(n.group[g].begin(), n.group[g].end(), v[i]) != n.group[g].end() && n.group[g].size() <= 2) { found = g; break; }
        if (found < 0) for (int g = 0; g < NGall; g++) if (!used[g] && std::find(n.group[g].begin(), n.group[g].end(), v[i]) != n.group[g].end()) { found = g; break; }
        if (found < 0) ok = false; else { used[found] = 1; grp[i] = found; seq[i] = v[i]; }
      }
      loaded = ok;
    }
    if (!loaded) fprintf(stderr, "init file unusable, using greedy\n");
  }
  if (!loaded && init == "static") {
    // Stage 0: time-independent sequencing problem. C[a][b] = typical time to get from the end of atom a to the end of
    // atom b when you have just stepped off a train at the end of a (so riding straight through costs no wait).
    std::vector<float> C((size_t)NA * NA), W(NA);
    std::vector<int> v; 
    for (int a = 0; a < NA; a++) {
      std::vector<int> ends;
      for (int t = 600; t < 2760; t += 13) { int d = s.A[(size_t)a * NT + t]; if (d != 65535) ends.push_back(t + d); }   // 05:00-23:00
      { v.clear(); for (int t = 600; t < 2760; t += 13) v.push_back(s.A[(size_t)a * NT + t]); std::sort(v.begin(), v.end()); W[a] = v[v.size() / 10]; }
      for (int b = 0; b < NA; b++) {
        v.clear();
        for (int e : ends) { int d = s.D[((size_t)s.eI[a] * s.ntgt + s.sI[b]) * NT + e % NT]; int x = s.A[(size_t)b * NT + (e + d) % NT]; v.push_back(d == 65535 || x == 65535 ? 60000 : d + x); }
        std::sort(v.begin(), v.end());
        C[(size_t)a * NA + b] = v.empty() ? 60000 : v[v.size() * 35 / 100];
      }
    }
    auto sc = [&](const std::vector<int>& q) { double c = W[q[0]]; for (int i = 1; i < NG; i++) c += C[(size_t)q[i - 1] * NA + q[i]]; return c; };
    // several short static anneals; keep the one that is best on the REAL timetable (not the static estimate)
    const int KST = 6; int bestReal = 1 << 30; std::vector<int> keepS, keepG; double bestStatic = 0;
    for (int rep = 0; rep < KST; rep++) {
    for (int g = 0; g < NG; g++) { grp[g] = g; seq[g] = n.group[g][rnd(n.group[g].size())]; }
    std::shuffle(grp.begin(), grp.end(), rng); for (int i = 0; i < NG; i++) seq[i] = n.group[grp[i]][rnd(n.group[grp[i]].size())];
    double cur = sc(seq), best = cur; std::vector<int> bs = seq, bg = grp, cs2(NG), cg2(NG);
    double stSecs = std::min(90.0, std::max(5.0, secs * 0.2)) / KST; auto ts = std::chrono::steady_clock::now(); long its = 0; double Ts = 20;
    while (true) {
      if ((its & 8191) == 0) { double e = std::chrono::duration<double>(std::chrono::steady_clock::now() - ts).count(); if (e > stSecs) break; Ts = 20 * std::pow(0.02 / 20, e / stSecs); }
      its++; cs2 = seq; cg2 = grp; int mv = rnd(100);
      if (mv < 40) { int Ls = 1 + rnd(6); int i = rnd(NG - Ls + 1), k = rnd(NG - Ls + 1); if (k == i) continue;
        if (rnd(2)) { std::reverse(cs2.begin() + i, cs2.begin() + i + Ls); std::reverse(cg2.begin() + i, cg2.begin() + i + Ls); for (int j = i; j < i + Ls; j++) cs2[j] = flip(cg2[j], cs2[j]); }
        if (k > i) { std::rotate(cs2.begin() + i, cs2.begin() + i + Ls, cs2.begin() + k + Ls); std::rotate(cg2.begin() + i, cg2.begin() + i + Ls, cg2.begin() + k + Ls); }
        else { std::rotate(cs2.begin() + k, cs2.begin() + i, cs2.begin() + i + Ls); std::rotate(cg2.begin() + k, cg2.begin() + i, cg2.begin() + i + Ls); }
      } else if (mv < 75) { int i = rnd(NG), j = rnd(NG); if (i > j) std::swap(i, j); if (i == j) continue;
        std::reverse(cs2.begin() + i, cs2.begin() + j + 1); std::reverse(cg2.begin() + i, cg2.begin() + j + 1); for (int x = i; x <= j; x++) cs2[x] = flip(cg2[x], cs2[x]);
      } else if (mv < 85) { int i = rnd(NG), j = rnd(NG); if (i == j) continue; std::swap(cs2[i], cs2[j]); std::swap(cg2[i], cg2[j]);
      } else { int i = rnd(NG); auto& g = n.group[cg2[i]]; if (g.size() < 2) continue; cs2[i] = g[rnd(g.size())]; }
      double c = sc(cs2);
      if (c <= cur || uni() < std::exp((cur - c) / Ts)) { seq.swap(cs2); grp.swap(cg2); cur = c; if (cur < best) { best = cur; bs = seq; bg = grp; } }
    }
    int bt; int real = s.bestStart(bs, bt);
    if (real < bestReal) { bestReal = real; keepS = bs; keepG = bg; bestStatic = best; }
    }
    std::vector<int> bs = keepS, bg = keepG; double best = bestStatic;
    seq = bs; grp = bg; loaded = true; t0 = 0;
    fprintf(stderr, "static stage: %.1f min typical, best of %d on the real timetable %.1f min\n", best * n.TICK / 60.0, KST, bestReal * n.TICK / 60.0);
  }
  if (!loaded) {
    // greedy: random first group & start time, then always the option finishing earliest
    std::vector<char> used(NG, 0);
    int g0 = rnd(NG); t0 = rnd(NT); for (int k = 0; k < 100000 && !s.inWin(t0); k++) t0 = rnd(NT);
    grp[0] = g0; seq[0] = n.group[g0][rnd(n.group[g0].size())]; used[g0] = 1;
    int t = t0 + s.A[(size_t)seq[0] * NT + t0 % NT], cur = s.eI[seq[0]];
    for (int i = 1; i < NG; i++) {
      int best = 1 << 30, bg = -1, bo = -1;
      for (int g = 0; g < NG; g++) if (!used[g]) for (int o : n.group[g]) {
        int d = s.D[((size_t)cur * s.ntgt + s.sI[o]) * NT + t % NT]; if (d == 65535) continue;
        int e = t + d; int a = s.A[(size_t)o * NT + e % NT]; if (a == 65535) continue;
        e += a + rnd(3);
        if (e < best) { best = e; bg = g; bo = o; }
      }
      if (bg < 0) { fprintf(stderr, "greedy stuck\n"); return 1; }
      used[bg] = 1; grp[i] = bg; seq[i] = bo;
      t += s.D[((size_t)cur * s.ntgt + s.sI[bo]) * NT + t % NT]; t += s.A[(size_t)bo * NT + t % NT]; cur = s.eI[bo];
    }
  }
  int cost = s.eval(seq, t0);
  if (fixP < 0) { int bt; int c = s.bestStart(seq, bt); if (c < cost) { cost = c; t0 = bt; } }
  fprintf(stderr, "seed %u start cost %.1f min\n", seed, cost * n.TICK / 60.0);
  std::vector<int> bestSeq = seq, bestGrp = grp; int bestCost = cost, bestT0 = t0;

  // Best-insertion polish: take each block of 1-3 segments out, try it at every position in both directions,
  // keep the best improvement; repeat until a full pass finds nothing. Exhaustive, so it finds moves random search misses.
  auto polish = [&](std::vector<int>& P, std::vector<int>& Gp, int pt0, int& pc) {
    bool improved = true; int passes = 0;
    std::vector<int> cs, cg;
    while (improved && passes < 6) {
      improved = false; passes++;
      for (int L = 1; L <= 3; L++) for (int i = 0; i + L <= NG; i++) {
        std::vector<int> bs(P.begin() + i, P.begin() + i + L), bgp(Gp.begin() + i, Gp.begin() + i + L);
        std::vector<int> rs = bs, rg = bgp; std::reverse(rs.begin(), rs.end()); std::reverse(rg.begin(), rg.end());
        for (int j = 0; j < L; j++) rs[j] = flip(rg[j], rs[j]);
        std::vector<int> restS, restG;
        restS.insert(restS.end(), P.begin(), P.begin() + i); restS.insert(restS.end(), P.begin() + i + L, P.end());
        restG.insert(restG.end(), Gp.begin(), Gp.begin() + i); restG.insert(restG.end(), Gp.begin() + i + L, Gp.end());
        int bestC = pc, bestK = -1, bestR = 0;
        for (int k = 0; k <= NG - L; k++) for (int r = 0; r < 2; r++) {
          if (k == i && r == 0) continue;
          cs = restS; cg = restG;
          cs.insert(cs.begin() + k, (r ? rs : bs).begin(), (r ? rs : bs).end());
          cg.insert(cg.begin() + k, (r ? rg : bgp).begin(), (r ? rg : bgp).end());
          int c = s.eval(cs, pt0);
          if (c < bestC) { bestC = c; bestK = k; bestR = r; }
        }
        if (bestK >= 0) {
          P = restS; Gp = restG;
          P.insert(P.begin() + bestK, (bestR ? rs : bs).begin(), (bestR ? rs : bs).end());
          Gp.insert(Gp.begin() + bestK, (bestR ? rg : bgp).begin(), (bestR ? rg : bgp).end());
          pc = bestC; improved = true;
        }
      }
      // single-segment direction flips
      for (int i = 0; i < NG; i++) for (int o : n.group[Gp[i]]) if (o != P[i]) {
        int old = P[i]; P[i] = o; int c = s.eval(P, pt0);
        if (c < pc) { pc = c; improved = true; } else P[i] = old;
      }
    }
  };
  auto save = [&]() {
    std::ofstream o(out); o << bestT0 << " " << bestCost << "\n";
    for (int a : bestSeq) o << a << "\n";
  };
  auto tStart = std::chrono::steady_clock::now();
  auto elapsed = [&]() { return std::chrono::duration<double>(std::chrono::steady_clock::now() - tStart).count(); };
  std::vector<int> cs(NG), cg(NG), tt(NG), ct(NG), cp(NG), ccp(NG);
  s.times(seq, t0, tt, cp);
  const bool rrt = getenv("ACCEPT") && std::string(getenv("ACCEPT")) == "rrt";
  double T = T0; long it = 0, acc = 0; double lastSave = 0; int cycle = -1;
  auto nearPos = [&](int i, int lo, int hi) {   // position near i (geometric-ish), within [lo,hi]
    int k; if (rnd(3) == 0) k = lo + rnd(hi - lo + 1); else { int d = 1 + (int)(-std::log(1 - uni() * 0.999) * 6); k = i + (rnd(2) ? d : -d); }
    return std::max(lo, std::min(hi, k));
  };
  while (true) {
    if ((it & 16383) == 0) {
      double e = elapsed(); if (e > secs) break;
      double first = std::min(secs, cyc > 0 ? std::max(3 * cyc, 0.25 * secs) : secs);
      if (e <= first) T = T0 * std::pow(T1 / T0, e / first);
      else {
        int k = (int)((e - first) / cyc);
        if (k != cycle) {             // new cycle: polish the best, then restart from it
          if (!getenv("NOPOLISH")) { int pc = bestCost; polish(bestSeq, bestGrp, bestT0, pc);
            if (pc < bestCost) { fprintf(stderr, "  polish %.1f -> %.1f min\n", bestCost * n.TICK / 60.0, pc * n.TICK / 60.0); bestCost = pc; } }
          cycle = k; seq = bestSeq; grp = bestGrp; t0 = bestT0; cost = bestCost; s.times(seq, t0, tt, cp);
        }
        T = Tr * std::pow(T1 / Tr, std::fmod(e - first, cyc) / cyc);
      }
      if (e - lastSave > 30) { save(); lastSave = e; fprintf(stderr, "  [%u] %.0fs T=%.2f cur %.1f best %.1f min (%.2f h)  it %ldM\n", seed, e, T, cost * n.TICK / 60.0, bestCost * n.TICK / 60.0, bestCost * n.TICK / 3600.0, it / 1000000); }
    }
    it++;
#ifdef CHECK
    if ((it & 65535) == 0) { int e = s.eval(seq, t0); if (e != cost) { fprintf(stderr, "DRIFT it %ld cost %d eval %d\n", it, cost, e); cost = e; s.times(seq, t0, tt, cp); } }
#endif
    int mv = rnd(100), ct0 = t0, f, l;
    memcpy(cs.data(), seq.data(), sizeof(int) * NG); memcpy(cg.data(), grp.data(), sizeof(int) * NG);
    if (mv < 45) {                       // or-opt: move a short segment, maybe reversed
      int L = 1 + rnd(5); if (L >= NG) continue;
      int i = rnd(NG - L + 1), k = nearPos(i, 0, NG - L); if (k == i) continue;
      bool rv = rnd(2);
      if (rv) { std::reverse(cs.begin() + i, cs.begin() + i + L); std::reverse(cg.begin() + i, cg.begin() + i + L); for (int j = i; j < i + L; j++) cs[j] = flip(cg[j], cs[j]); }
      if (k > i) { std::rotate(cs.begin() + i, cs.begin() + i + L, cs.begin() + k + L); std::rotate(cg.begin() + i, cg.begin() + i + L, cg.begin() + k + L); f = i; l = k + L - 1; }
      else { std::rotate(cs.begin() + k, cs.begin() + i, cs.begin() + i + L); std::rotate(cg.begin() + k, cg.begin() + i, cg.begin() + i + L); f = k; l = i + L - 1; }
    } else if (mv < 65) {                // 2-opt: reverse a segment and flip directions
      int i = rnd(NG), j = nearPos(i, 0, NG - 1); if (i > j) std::swap(i, j); if (i == j) continue;
      std::reverse(cs.begin() + i, cs.begin() + j + 1); std::reverse(cg.begin() + i, cg.begin() + j + 1);
      for (int x = i; x <= j; x++) cs[x] = flip(cg[x], cs[x]);
      f = i; l = j;
    } else if (mv < 75) {                // swap two
      int i = rnd(NG), j = nearPos(i, 0, NG - 1); if (i == j) continue; if (i > j) std::swap(i, j);
      std::swap(cs[i], cs[j]); std::swap(cg[i], cg[j]); f = i; l = j;
    } else if (mv < 93) {                // change direction / option
      int i = rnd(NG); auto& g = n.group[cg[i]]; if (g.size() < 2) continue;
      int o = g[rnd(g.size())]; if (o == cs[i]) continue; cs[i] = o; f = l = i;
    } else if (fixP >= 0) { continue;
    } else if (mv < 99) {                // shift the start time
      ct0 = t0 + (rnd(2) ? 1 : -1) * (1 + rnd(20)); f = 0; l = -1;
      if (!s.inWin(ct0)) continue;
      if (ct0 < 0 || ct0 >= 3 * NT) { ct0 = (ct0 % NT + NT) % NT; l = NG - 1; }
    } else {                             // rotate: move a prefix to the end (changes start station)
      if (rnd(50)) continue;
      int i = 1 + rnd(NG - 1);
      std::rotate(cs.begin(), cs.begin() + i, cs.end()); std::rotate(cg.begin(), cg.begin() + i, cg.end());
      int bt; s.bestStart(cs, bt); ct0 = bt; f = 0; l = NG - 1;
    }
    int stop;
    int c = (s.casc > 0) ? s.eval(cs, ct0) : s.evalInc(cs, ct0, tt, t0, f, l, ct, stop, cp, ccp);
    if (s.casc <= 0 && c < Solver::BAD) c += s.endPen(cs);
    if (s.casc > 0) stop = f - 1;
    // acceptance: Metropolis, or (ACCEPT=rrt) record-to-record travel where T is a threshold in ticks above the best:
    // bounded wandering, but still able to step over a missed-train cliff
    if (c <= cost || (rrt ? c <= bestCost + T : uni() < std::exp((cost - c) / T))) {
      seq.swap(cs); grp.swap(cg); cost = c; t0 = ct0; acc++;
      memcpy(tt.data() + f, ct.data() + f, sizeof(int) * (stop - f + 1));
      if (stop >= f) { int shift = (stop < NG - 1) ? (ccp[stop] - cp[stop]) : 0; memcpy(cp.data() + f, ccp.data() + f, sizeof(int) * (stop - f + 1)); if (shift) for (int j = stop + 1; j < NG; j++) cp[j] += shift; }
      if (cost < bestCost) { bestCost = cost; bestSeq = seq; bestGrp = grp; bestT0 = t0; }
    }
  }
  if (!getenv("NOPOLISH")) { int pc = bestCost; polish(bestSeq, bestGrp, bestT0, pc); bestCost = pc; }
  if (fixP < 0) { int bt; int c = s.bestStart(bestSeq, bt); if (c <= bestCost) { bestCost = c; bestT0 = bt; } }
  save();
  fprintf(stderr, "seed %u final best %.1f min = %.3f h, start tick %d (%02d:%02d), iters %ldk acc %.1f%%\n", seed, bestCost * n.TICK / 60.0,
          bestCost * n.TICK / 3600.0, bestT0, bestT0 * n.TICK / 3600, bestT0 * n.TICK % 3600 / 60, it / 1000, 100.0 * acc / it);
  return 0;
}
