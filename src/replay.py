#!/usr/bin/env python3
"""Replay a route against every real day in a folder of .tt files (see ingest_subwaydata.py).
The rider keeps the planned order and start time and takes whatever real train comes first.
usage: replay.py data solution.txt out/days/ [-v]"""
import sys, glob, subprocess, os
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import config as C
data, sol, folder = sys.argv[1:4]
sim = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bin', 'sim')
files = sorted(glob.glob(folder + '/*.tt'))
def one(f):
    o = subprocess.run([sim, data, sol, 'dur'], env={**os.environ, 'TT': f}, capture_output=True, text=True).stdout.strip()
    return int(o) if o.lstrip('-').isdigit() else -1
with ThreadPoolExecutor(2) as ex:
    res = list(ex.map(one, files))
h = lambda s: '%d:%02d' % (s // 3600, s % 3600 // 60)
if '-v' in sys.argv:
    for f, d in zip(files, res): print(os.path.basename(f)[:10], 'no finish' if d <= 0 or d > 40 * 3600 else h(d))
ok = np.array([d for d in res if 0 < d < 40 * 3600])
sched = int(subprocess.run([sim, data, sol, 'dur'], capture_output=True, text=True).stdout)
print('plan %s | %d real days: best %s  25%% %s  median %s  75%% %s  worst %s | beat 22:14:10 on %d, no finish on %d' % (
    h(sched), len(res), h(ok.min()), h(int(np.percentile(ok, 25))), h(int(np.median(ok))), h(int(np.percentile(ok, 75))), h(ok.max()),
    (ok < C.RECORD_SECONDS).sum(), len(res) - len(ok)))
