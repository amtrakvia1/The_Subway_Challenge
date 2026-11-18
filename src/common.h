// Shared loaders for the compact network produced by build_network.py
#pragma once
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <map>
#include <algorithm>
#include <fstream>
#include <iostream>
#include <sstream>

struct Conn { int32_t dp, ap, dt, at, trip, next; };   // dt in [0,NT); at = dt + run (ticks)
struct Edge { int32_t a, b, t; };
struct DAtom { std::vector<int> st; int start_p, end_p; };

struct Net {
  int S = 0, NT = 0, TICK = 0, XSAME = 0, XPLAT = 0, NTRIP = 0;
  std::vector<Conn> conn;
  std::vector<int> cstart;                 // first conn index with dt >= tick, size NT+1
  std::vector<Edge> xfer, walk;
  std::vector<std::vector<std::pair<int,int>>> sx, sw;   // per station: (to station, ticks)
  std::vector<DAtom> datom;
  std::vector<std::vector<int>> group;     // group -> directed atom options
  std::vector<int> srcP, tgtP;             // sorted unique end / start platforms
  std::vector<int> srcIdx, tgtIdx;         // platform -> index or -1
  std::vector<int> rev;                    // directed atom -> opposite direction atom or -1
};

template <class T> static std::vector<T> readBin(const std::string& f) {
  std::ifstream in(f, std::ios::binary | std::ios::ate);
  if (!in) { fprintf(stderr, "cannot open %s\n", f.c_str()); exit(1); }
  size_t n = in.tellg(); in.seekg(0);
  std::vector<T> v(n / sizeof(T));
  in.read((char*)v.data(), n);
  return v;
}

static Net loadNet(const std::string& dir) {
  Net n;
  std::ifstream m(dir + "/meta.txt");
  std::string k; long v; std::map<std::string,long> kv;
  while (m >> k >> v) kv[k] = v;
  n.S = kv["S"]; n.NT = kv["NT"]; n.TICK = kv["TICK"]; n.XSAME = kv["XSAME"]; n.XPLAT = kv["XPLAT"]; n.NTRIP = kv["NTRIP"];
  n.conn = readBin<Conn>(dir + "/conn.bin");
  n.cstart.assign(n.NT + 1, 0);
  { size_t i = 0; for (int t = 0; t <= n.NT; t++) { while (i < n.conn.size() && n.conn[i].dt < t) i++; n.cstart[t] = (int)i; } }
  n.xfer = readBin<Edge>(dir + "/xfer.bin");
  n.walk = readBin<Edge>(dir + "/walk.bin");
  n.sx.resize(n.S); n.sw.resize(n.S);
  for (auto& e : n.xfer) n.sx[e.a].push_back({e.b, e.t});
  for (auto& e : n.walk) n.sw[e.a].push_back({e.b, e.t});
  auto a = readBin<int32_t>(dir + "/atoms.bin");
  for (size_t i = 0; i < a.size();) {
    DAtom d; int len = a[i]; d.start_p = a[i+1]; d.end_p = a[i+2];
    d.st.assign(a.begin() + i + 3, a.begin() + i + 3 + len);
    n.datom.push_back(d); i += 3 + len;
  }
  auto g = readBin<int32_t>(dir + "/groups.bin");
  for (size_t i = 0; i < g.size();) { int len = g[i]; n.group.emplace_back(g.begin() + i + 1, g.begin() + i + 1 + len); i += 1 + len; }
  n.srcIdx.assign(2 * n.S, -1); n.tgtIdx.assign(2 * n.S, -1);
  for (auto& d : n.datom) { n.srcIdx[d.end_p] = 0; n.tgtIdx[d.start_p] = 0; }
  for (int p = 0; p < 2 * n.S; p++) {
    if (n.srcIdx[p] == 0) { n.srcIdx[p] = n.srcP.size(); n.srcP.push_back(p); }
    if (n.tgtIdx[p] == 0) { n.tgtIdx[p] = n.tgtP.size(); n.tgtP.push_back(p); }
  }
  n.rev.assign(n.datom.size(), -1);
  for (size_t i = 0; i < n.datom.size(); i++) for (size_t j = 0; j < n.datom.size(); j++) {
    if (i == j || n.datom[i].st.size() != n.datom[j].st.size()) continue;
    if (std::equal(n.datom[i].st.begin(), n.datom[i].st.end(), n.datom[j].st.rbegin())) n.rev[i] = j;
  }
  return n;
}
