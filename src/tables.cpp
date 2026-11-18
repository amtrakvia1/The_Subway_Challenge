// Build the two lookup tables the optimizer runs on.
//   D[src][tgt][t] : ticks from "at end-platform src at tick t" to "at start-platform tgt", any trains / transfers / runs
//   A[datom][t]    : ticks to ride a whole atom (stopping at every station) starting at tick t on its start platform
// Time is cyclic (weekday follows weekday).  uint16, 65535 = unreachable.
// usage: tables <data_dir> <slack_ticks> <out_prefix>
#include "common.h"
#include <omp.h>

static const int INF = 1 << 29;

int main(int argc, char** argv) {
  if (argc < 4) { fprintf(stderr, "usage: tables data_dir slack_ticks out_prefix\n"); return 1; }
  Net n = loadNet(argv[1]);
  int slack = atoi(argv[2]);
  std::string out = argv[3];
  const int NT = n.NT, S = n.S, P = 2 * S, H = 2 * NT;
  int beta = n.XPLAT + slack, same = n.XSAME + slack; if (slack < 0) { beta = n.XPLAT; same = n.XSAME; }
  int maxx = same;
  for (auto& e : n.xfer) maxx = std::max(maxx, e.t + slack);
  for (auto& e : n.walk) maxx = std::max(maxx, e.t + slack);
  int maxrun = 0;
  for (auto& c : n.conn) maxrun = std::max(maxrun, c.at - c.dt);
  const int PAD = maxx + maxrun + beta + 4 + 10;
  const int nsrc = n.srcP.size(), ntgt = n.tgtP.size();
  fprintf(stderr, "S=%d conns=%zu src=%d tgt=%d slack=%d ticks, table %.2f GB\n", S, n.conn.size(), nsrc, ntgt, slack,
          (double)nsrc * ntgt * NT * 2 / 1e9);

  // Margin by headway (slack argument = -1): the spare time demanded before boarding at a platform depends on how long
  // the NEXT train there is. Frequent service -> 30 s; a 10+ minute gap -> 3 min. sl[p*NT+tick] in ticks.
  std::vector<uint8_t> sl((size_t)P * NT, 0);
  // slack == -2: targeted margins from a file (env SLACKMAP): int32 rows [platform, from_tick, to_tick, margin_ticks].
  // Arriving at that platform in that time window requires that much spare time before boarding; zero elsewhere.
  if (slack == -2) {
    const char* f = getenv("SLACKMAP");
    if (f) { auto v = readBin<int32_t>(f);
      for (size_t i = 0; i + 3 < v.size(); i += 4) for (int t = v[i + 1]; t <= v[i + 2]; t++) {
        uint8_t& x = sl[(size_t)v[i] * NT + ((t % NT) + NT) % NT]; x = std::max<int>(x, v[i + 3]); }
      fprintf(stderr, "slack map: %zu windows\n", v.size() / 4); }
    slack = 0;
  }
  const bool byHeadway = slack == -1;
  if (byHeadway) {
    std::vector<std::vector<int>> deps(P);
    for (auto& c : n.conn) deps[c.dp].push_back(c.dt);
    for (int p = 0; p < P; p++) {
      auto& d = deps[p]; if (d.empty()) continue;
      std::sort(d.begin(), d.end()); d.erase(std::unique(d.begin(), d.end()), d.end());
      for (int t = 0; t < NT; t++) {
        auto it = std::lower_bound(d.begin(), d.end(), t);
        int i = (it == d.end()) ? 0 : it - d.begin();
        int first = d[i] + (it == d.end() ? NT : 0), second = d[(i + 1) % d.size()] + ((i + 1 >= (int)d.size() || it == d.end()) ? NT : 0);
        int gap = second - first;                       // ticks between the next train and the one after it
        sl[(size_t)p * NT + t] = gap >= 30 ? 8 : gap >= 20 ? 6 : gap >= 12 ? 4 : gap >= 7 ? 2 : 1;
      }
    }
    slack = 0;
  }
  // ---------------- D ----------------
  std::vector<uint16_t> D((size_t)nsrc * ntgt * NT);
  // station-level edges with slack folded in
  std::vector<std::vector<std::pair<int,int>>> se(S);
  for (int s = 0; s < S; s++) {
    se[s].push_back({s, same});
    for (auto& e : n.sx[s]) se[s].push_back({e.first, e.second + slack});
    for (auto& e : n.sw[s]) se[s].push_back({e.first, e.second + slack});
  }
  int done = 0;
  #pragma omp parallel
  {
    std::vector<int> E((size_t)(H + PAD) * P), M((size_t)(H + PAD) * S), GS((size_t)(H + PAD) * S), R(n.conn.size());
    #pragma omp for schedule(dynamic, 1)
    for (int qi = 0; qi < ntgt; qi++) {
      int q = n.tgtP[qi];
      std::fill(E.begin(), E.end(), INF); std::fill(M.begin(), M.end(), INF); std::fill(GS.begin(), GS.end(), INF); std::fill(R.begin(), R.end(), INF);
      for (int T = 0; T < H + PAD; T++) { E[(size_t)T * P + q] = T; M[(size_t)T * S + q / 2] = T; }
      // E  = "may only board a train here" (you just walked/transferred in, or are waiting)
      // GS = best via one same-station / complex / street move from this station (then you must board)
      for (int T = H - 1; T >= 0; T--) {
        int* row = &E[(size_t)T * P];
        memcpy(row, row + P, sizeof(int) * P);                       // wait one tick
        int tick = T % NT;
        for (int ci = n.cstart[tick]; ci < n.cstart[tick + 1]; ci++) {
          const Conn& c = n.conn[ci];
          int arr = T + (c.at - c.dt);
          // leave the train here: same platform after beta, or one move to another platform / the street
          int v = (c.ap == q) ? arr : std::min(E[(size_t)(arr + beta + sl[(size_t)c.ap * NT + arr % NT]) * P + c.ap], GS[(size_t)arr * S + c.ap / 2]);
          if (c.next >= 0) v = std::min(v, R[c.next]);
          R[ci] = v;
          if (v < row[c.dp]) row[c.dp] = v;
        }
        row[q] = T;
        int* mr = &M[(size_t)T * S];
        for (int s = 0; s < S; s++) mr[s] = std::min(E[(size_t)(T + sl[(size_t)(2 * s) * NT + tick]) * P + 2 * s], E[(size_t)(T + sl[(size_t)(2 * s + 1) * NT + tick]) * P + 2 * s + 1]);
        mr[q / 2] = std::min(mr[q / 2], T);
        for (int s = 0; s < S; s++) {
          int g = INF;
          for (auto& e : se[s]) { int x = M[(size_t)(T + e.second) * S + e.first]; if (x < g) g = x; }
          GS[(size_t)T * S + s] = g;
        }
      }
      for (int si = 0; si < nsrc; si++) {
        int p = n.srcP[si];
        uint16_t* d = &D[((size_t)si * ntgt + qi) * NT];
        for (int t = 0; t < NT; t++) { int v = std::min(E[(size_t)t * P + p], GS[(size_t)t * S + p / 2]) - t; d[t] = v >= 65535 ? 65535 : (uint16_t)v; }
      }
      #pragma omp critical
      { if (++done % 50 == 0) fprintf(stderr, "  D targets %d/%d\n", done, ntgt); }
    }
  }
  { FILE* f = fopen((out + "_D.bin").c_str(), "wb"); fwrite(D.data(), 2, D.size(), f); fclose(f); }

  // ---------------- A ----------------
  int NA = n.datom.size();
  std::vector<uint16_t> A((size_t)NA * NT);
  #pragma omp parallel
  {
    std::vector<int> G(n.conn.size());
    #pragma omp for schedule(dynamic, 4)
    for (int ai = 0; ai < NA; ai++) {
      const DAtom& da = n.datom[ai];
      int k = da.st.size() - 1;
      std::vector<int> hopOf(n.conn.size(), -1);
      std::vector<std::vector<int>> byTick(NT);
      for (size_t ci = 0; ci < n.conn.size(); ci++) {
        const Conn& c = n.conn[ci];
        for (int i = 0; i < k; i++) if (c.dp / 2 == da.st[i] && c.ap / 2 == da.st[i + 1]) { hopOf[ci] = i; byTick[c.dt].push_back(ci); }
      }
      // F[(T*(k+1) + i)*2 + l]
      std::vector<int> F((size_t)(H + PAD) * (k + 1) * 2, INF);
      auto f = [&](int T, int i, int l) -> int& { return F[((size_t)T * (k + 1) + i) * 2 + l]; };
      std::fill(G.begin(), G.end(), INF);
      int endl = da.end_p % 2;
      for (int T = 0; T < H + PAD; T++) { f(T, k, endl) = T; f(T, k, 1 - endl) = T + same; }
      for (int T = H - 1; T >= 0; T--) {
        for (int i = 0; i < k; i++) for (int l = 0; l < 2; l++) f(T, i, l) = std::min(f(T + 1, i, l), f(T + same, i, 1 - l));
        for (int ci : byTick[T % NT]) {
          const Conn& c = n.conn[ci];
          int i = hopOf[ci], arr = T + (c.at - c.dt);
          int u = (i + 1 == k) ? f(arr, k, c.ap % 2) : f(arr + beta + sl[(size_t)c.ap * NT + arr % NT], i + 1, c.ap % 2);
          if (c.next >= 0 && hopOf[c.next] == i + 1) u = std::min(u, G[c.next]);
          G[ci] = u;
          int& x = f(T, i, c.dp % 2);
          if (u < x) x = u;
        }
      }
      int sl = da.start_p % 2;
      for (int t = 0; t < NT; t++) { int v = f(t, 0, sl) - t; A[(size_t)ai * NT + t] = v >= 65535 ? 65535 : (uint16_t)v; }
    }
  }
  { FILE* f = fopen((out + "_A.bin").c_str(), "wb"); fwrite(A.data(), 2, A.size(), f); fclose(f); }
  fprintf(stderr, "done\n");
  return 0;
}
