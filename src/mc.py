#!/usr/bin/env python3
"""Monte-Carlo robustness of a route under random train delays (placeholder delay model in sim.cpp).
usage: mc.py data solution.txt [samples=300] [scale=1.0]"""
import sys, subprocess, os, numpy as np
import config as C
data, sol = sys.argv[1:3]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 300
scale = sys.argv[4] if len(sys.argv) > 4 else '1.0'
sim = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bin', 'sim')
half = N // 2
procs = [subprocess.Popen([sim, data, sol, 'mc', str(n), str(seed), scale], stdout=subprocess.PIPE, text=True)
         for n, seed in ((half, 1), (N - half, 2))]
d = np.array([int(x) for p in procs for x in p.communicate()[0].split()])
sched = int(subprocess.run([sim, data, sol, 'dur'], capture_output=True, text=True).stdout)
fin = d[d > 0]
h = lambda s: '%d:%02d' % (s // 3600, s % 3600 // 60)
print('scheduled %s | simulated days: median %s  p10 %s  p90 %s | P(beat 22:14:10) = %.0f%%  (n=%d, delay scale %s)' % (
    h(sched), h(int(np.median(fin))), h(int(np.percentile(fin, 10))), h(int(np.percentile(fin, 90))),
    100 * (fin < C.RECORD_SECONDS).sum() / len(d), len(d), scale))
