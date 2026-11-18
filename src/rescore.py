#!/usr/bin/env python3
"""Rescore many routes on the delay model fitted to real data (bin/sim mc), in parallel.
usage: rescore.py N_samples file1.txt file2.txt ...    -> out/rescored.csv sorted by median"""
import sys, subprocess, csv
from concurrent.futures import ThreadPoolExecutor
import numpy as np, os
DATA = os.environ.get('DATA', 'data')
N = int(sys.argv[1]); files = sys.argv[2:]
REC = 22 * 3600 + 14 * 60 + 10
h = lambda s: '%d:%02d' % (s // 3600, s % 3600 // 60)
def one(f):
    d = int(subprocess.run(['./bin/sim', DATA, f, 'dur'], capture_output=True, text=True).stdout)
    mc = np.array([int(x) for x in subprocess.run(['./bin/sim', DATA, f, 'mc', str(N), '7', '1.0'], capture_output=True, text=True).stdout.split()])
    mc = np.where(mc > 0, mc, 40 * 3600)
    return [f, h(d), h(int(np.median(mc))), h(int(np.percentile(mc, 10))), h(int(np.percentile(mc, 90))), int((mc < REC).sum()), len(mc), int(np.median(mc))]
with ThreadPoolExecutor(2) as ex:
    rows = list(ex.map(one, files))
rows.sort(key=lambda r: r[-1])
w = csv.writer(open('out/rescored.csv', 'w', newline=''))
w.writerow(['file', 'on_time', 'median', 'p10', 'p90', 'beat_record', 'samples'])
for r in rows: w.writerow(r[:-1]); print(*r[:-1])
