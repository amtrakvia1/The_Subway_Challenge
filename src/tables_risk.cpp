// Risk-aware ("expected time") versions of the D and A tables.
//
// Same rules as tables.cpp, plus a model of missed connections:
//   when you become able to board at a platform at time T and the train you want leaves at T+m,
//   you miss it with probability missProb(m) (m = spare margin beyond the physical transfer time).
//   If you miss it you are simply standing on that platform at T+m and choose again.
// Staying on the train you are already on is always certain.
// The tables then hold the EXPECTED ticks under the best policy, so the optimizer automatically
// avoids tight connections onto infrequent trains and is indifferent to tight ones onto frequent trains.
//
// usage: tables_risk <data_dir> <risk_scale> <out_prefix>
//   risk_scale 0 reproduces tables.cpp exactly (tested); 1 = default miss curve; 2 = twice as pessimistic.
#include "common.h"
#include <omp.h>
#include <cmath>

static const float INF = 1e9f;
static const int W = 20;                         // margins beyond 20 ticks (10 min) are treated as safe
// P(miss) by margin in ticks (30 s). PLACEHOLDER curve -> calibrate from subwaydata.nyc (docs/HANDOFF.md)
static const float Q0[W + 1] = {0.55f, 0.40f, 0.28f, 0.20f, 0.14f, 0.11f, 0.08f, 0.065f, 0.05f, 0.04f, 0.03f,
                                0.025f, 0.02f, 0.015f, 0.01f, 0.01f, 0.005f, 0.005f, 0.0025f, 0.0025f, 0.0f};

struct Ent { int T; float r; };

int main(int argc, char** argv) {
  if (argc < 4) { fprintf(stderr, "usage: tables_risk data_dir risk_scale out_prefix\n"); return 1; }
  Net n = loadNet(argv[1]);
  double scale = atof(argv[2]);
  std::string out = argv[3];
  float Q[W + 1]; for (int m = 0; m <= W; m++) Q[m] = std::min(0.95, Q0[m] * scale);
  const int NT = n.NT, S = n.S, P = 2 * S, H = 2 * NT;
  const int beta = n.XPLAT, same = n.XSAME;
  int maxx = same;
  for (auto& e : n.xfer) maxx = std::max(maxx, e.t);
  for (auto& e : n.walk) maxx = std::max(maxx, e.t);
  int maxrun = 0;
  for (auto& c : n.conn) maxrun = std::max(maxrun, c.at - c.dt);
  const int PAD = maxx + maxrun + beta + W + 6;
  const int nsrc = n.srcP.size(), ntgt = n.tgtP.size(), NC = n.conn.size();
  // dwell before each connection (ticks since the same train arrived at this platform), -1 if first stop
  std::vector<int> gap(NC, -1);
  for (int i = 0; i < NC; i++) if (n.conn[i].next >= 0) { int j = n.conn[i].next; gap[j] = ((n.conn[j].dt - n.conn[i].at) % NT + NT) % NT; }
  fprintf(stderr, "risk scale %.2f  src=%d tgt=%d\n", scale, nsrc, ntgt);

  std::vector<uint16_t> D((size_t)nsrc * ntgt * NT);
  std::vector<std::vector<std::pair<int,int>>> se(S);
  for (int s = 0; s < S; s++) {
    se[s].push_back({s, same});
    for (auto& e : n.sx[s]) se[s].push_back(e);
    for (auto& e : n.sw[s]) se[s].push_back(e);
  }
  int done = 0;
  #pragma omp parallel
  {
    size_t RW = (size_t)(H + PAD);
    std::vector<float> Vs(RW * P), Vf(RW * P), RT(RW * P), Mf(RW * S), GS(RW * S), R(NC);
    std::vector<std::vector<Ent>> ent(P);
    std::vector<int> head(P);
    #pragma omp for schedule(dynamic, 1)
    for (int qi = 0; qi < ntgt; qi++) {
      int q = n.tgtP[qi];
      std::fill(Vs.begin(), Vs.end(), INF); std::fill(Vf.begin(), Vf.end(), INF); std::fill(RT.begin(), RT.end(), INF);
      std::fill(Mf.begin(), Mf.end(), INF); std::fill(GS.begin(), GS.end(), INF); std::fill(R.begin(), R.end(), INF);
      for (int p = 0; p < P; p++) { ent[p].clear(); head[p] = 0; }
      for (size_t T = 0; T < RW; T++) { Vs[T * P + q] = T; Vf[T * P + q] = T; Mf[T * S + q / 2] = T; }
      for (int T = H - 1; T >= 0; T--) {
        float* vs = &Vs[(size_t)T * P];
        memcpy(vs, vs + P, sizeof(float) * P);
        int tick = T % NT;
        for (int ci = n.cstart[tick]; ci < n.cstart[tick + 1]; ci++) {
          const Conn& c = n.conn[ci];
          int arr = T + (c.at - c.dt);
          float v = (c.ap == q) ? (float)arr : std::min(Vf[(size_t)(arr + beta) * P + c.ap], GS[(size_t)arr * S + c.ap / 2]);
          if (c.next >= 0) v = std::min(v, R[c.next]);
          R[ci] = v;
          if (v < vs[c.dp]) vs[c.dp] = v;
          ent[c.dp].push_back({T, v});
          if (gap[ci] >= 0 && T - gap[ci] >= 0) { float& rt = RT[(size_t)(T - gap[ci]) * P + c.dp]; if (v < rt) rt = v; }
        }
        vs[q] = T;
        float* vf = &Vf[(size_t)T * P];
        for (int p = 0; p < P; p++) {
          float best = Vs[(size_t)(T + W + 1) * P + p];
          auto& e = ent[p];
          while (head[p] < (int)e.size() && e[head[p]].T > T + W) head[p]++;
          for (int i = head[p]; i < (int)e.size(); i++) {
            int m = e[i].T - T; float qm = Q[m];
            float v = (1 - qm) * e[i].r + qm * Vf[(size_t)(e[i].T + 1) * P + p];
            if (v < best) best = v;
          }
          vf[p] = best;
          if (head[p] > 64) { e.erase(e.begin(), e.begin() + head[p]); head[p] = 0; }
        }
        vf[q] = T;
        float* mf = &Mf[(size_t)T * S];
        for (int s = 0; s < S; s++) mf[s] = std::min(vf[2 * s], vf[2 * s + 1]);
        for (int s = 0; s < S; s++) {
          float g = INF;
          for (auto& ed : se[s]) { float x = Mf[(size_t)(T + ed.second) * S + ed.first]; if (x < g) g = x; }
          GS[(size_t)T * S + s] = g;
        }
      }
      for (int si = 0; si < nsrc; si++) {
        int p = n.srcP[si];
        uint16_t* d = &D[((size_t)si * ntgt + qi) * NT];
        for (int t = 0; t < NT; t++) {
          float v = std::min(std::min(RT[(size_t)t * P + p], Vf[(size_t)t * P + p]), GS[(size_t)t * S + p / 2]) - t;
          d[t] = v >= 65535 ? 65535 : (uint16_t)std::lround(v);
        }
      }
      #pragma omp critical
      { if (++done % 100 == 0) fprintf(stderr, "  D targets %d/%d\n", done, ntgt); }
    }
  }
  { FILE* f = fopen((out + "_D.bin").c_str(), "wb"); fwrite(D.data(), 2, D.size(), f); fclose(f); }

  int NA = n.datom.size();
  std::vector<uint16_t> A((size_t)NA * NT);
  #pragma omp parallel
  {
    std::vector<float> G(NC);
    #pragma omp for schedule(dynamic, 4)
    for (int ai = 0; ai < NA; ai++) {
      const DAtom& da = n.datom[ai];
      int k = da.st.size() - 1;
      std::vector<int> hopOf(NC, -1);
      std::vector<std::vector<int>> byTick(NT);
      for (int ci = 0; ci < NC; ci++) {
        const Conn& c = n.conn[ci];
        for (int i = 0; i < k; i++) if (c.dp / 2 == da.st[i] && c.ap / 2 == da.st[i + 1]) { hopOf[ci] = i; byTick[c.dt].push_back(ci); }
      }
      size_t RW = (size_t)(H + PAD), ST = (size_t)(k + 1) * 2;
      std::vector<float> Fs(RW * ST, INF), Ff(RW * ST, INF), RTa(RW, INF);
      std::vector<std::vector<Ent>> ent(ST); std::vector<int> head(ST, 0);
      std::fill(G.begin(), G.end(), INF);
      int endl = da.end_p % 2;
      for (size_t T = 0; T < RW; T++) {
        Fs[T * ST + k * 2 + endl] = Ff[T * ST + k * 2 + endl] = T;
        Fs[T * ST + k * 2 + 1 - endl] = Ff[T * ST + k * 2 + 1 - endl] = T + same;
      }
      for (int T = H - 1; T >= 0; T--) {
        float* fs = &Fs[(size_t)T * ST]; float* ff = &Ff[(size_t)T * ST];
        memcpy(fs, fs + ST, sizeof(float) * (k * 2));
        for (int ci : byTick[T % NT]) {
          const Conn& c = n.conn[ci];
          int i = hopOf[ci], arr = T + (c.at - c.dt), al = c.ap % 2;
          float u;
          if (i + 1 == k) u = (c.ap == da.end_p) ? (float)arr : (float)(arr + same);
          else u = std::min(Ff[(size_t)(arr + beta) * ST + (i + 1) * 2 + al], Ff[(size_t)(arr + same) * ST + (i + 1) * 2 + 1 - al]);
          if (c.next >= 0 && hopOf[c.next] == i + 1) u = std::min(u, G[c.next]);
          G[ci] = u;
          int sidx = i * 2 + c.dp % 2;
          if (u < fs[sidx]) fs[sidx] = u;
          ent[sidx].push_back({T, u});
          if (i == 0 && c.dp == da.start_p && gap[ci] >= 0 && T - gap[ci] >= 0) { float& rt = RTa[T - gap[ci]]; if (u < rt) rt = u; }
        }
        for (int x = 0; x < k * 2; x++) {
          float best = std::min(Fs[(size_t)(T + W + 1) * ST + x], Ff[(size_t)(T + same) * ST + (x ^ 1)]);
          auto& e = ent[x];
          while (head[x] < (int)e.size() && e[head[x]].T > T + W) head[x]++;
          for (int j = head[x]; j < (int)e.size(); j++) {
            int m = e[j].T - T; float qm = Q[m];
            float v = (1 - qm) * e[j].r + qm * Ff[(size_t)(e[j].T + 1) * ST + x];
            if (v < best) best = v;
          }
          ff[x] = best;
        }
      }
      int sl = da.start_p % 2;
      for (int t = 0; t < NT; t++) {
        float v = std::min(RTa[t], Ff[(size_t)t * ST + sl]) - t;
        A[(size_t)ai * NT + t] = v >= 65535 ? 65535 : (uint16_t)std::lround(v);
      }
    }
  }
  { FILE* f = fopen((out + "_A.bin").c_str(), "wb"); fwrite(A.data(), 2, A.size(), f); fclose(f); }
  fprintf(stderr, "done\n");
  return 0;
}
