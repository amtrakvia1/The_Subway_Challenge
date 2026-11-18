// Box-filter a table set along time of day (cyclic): each entry becomes the mean duration over +-w ticks.
// This turns "exactly which train" into "expected wait" and makes the optimizer's landscape smooth.
// Use as a first stage; refine on the exact or risk tables afterwards.
// usage: smooth <in_prefix> <out_prefix> <w_ticks> <NT>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <vector>
#include <string>
int main(int argc, char** argv) {
  if (argc < 5) { fprintf(stderr, "usage: smooth in_prefix out_prefix w NT\n"); return 1; }
  std::string in = argv[1], out = argv[2]; int w = atoi(argv[3]), NT = atoi(argv[4]);
  for (const char* suf : {"_D.bin", "_A.bin"}) {
    FILE* f = fopen((in + suf).c_str(), "rb"); FILE* g = fopen((out + suf).c_str(), "wb");
    if (!f || !g) { perror("open"); return 1; }
    std::vector<uint16_t> row(NT), res(NT);
    while (fread(row.data(), 2, NT, f) == (size_t)NT) {
      long s = 0; bool bad = false;
      for (int d = -w; d <= w; d++) { int v = row[((d % NT) + NT) % NT]; if (v == 65535) bad = true; s += v; }
      for (int t = 0; t < NT; t++) {
        res[t] = (uint16_t)((s + w) / (2 * w + 1));
        int o = row[((t - w) % NT + NT) % NT], n = row[(t + w + 1) % NT];
        s += n - o;
      }
      if (bad) for (int t = 0; t < NT; t++) { bool b = false; for (int d = -w; d <= w && !b; d++) b = row[((t + d) % NT + NT) % NT] == 65535; if (b) res[t] = 65535; }
      fwrite(res.data(), 2, NT, g);
    }
    fclose(f); fclose(g);
  }
  return 0;
}
