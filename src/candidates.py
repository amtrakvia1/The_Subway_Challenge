#!/usr/bin/env python3
"""Generate route OPTIONS: run many seeds, score each, append to out/candidates.csv (solutions kept in out/cands/).
usage: candidates.py <tables: tab/k4|tab/hw|tab/s0> <secs_per_seed> <first_seed> <n_rounds> [start_from_tick start_to_tick]
Each round runs 2 seeds in parallel. Safe to stop and restart; pick routes later by sorting the CSV."""
import sys, os, subprocess, json, csv
import numpy as np
tab, secs, seed0, rounds = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
win = sys.argv[5:7]
os.makedirs('out/cands', exist_ok=True)
h = lambda s: '%d:%02d' % (s // 3600, s % 3600 // 60)
new = not os.path.exists('out/candidates.csv')
f = open('out/candidates.csv', 'a', newline=''); w = csv.writer(f)
if new: w.writerow(['file', 'tables', 'plan', 'start', 'delay_median', 'delay_p90', 'worst_miss_min', 'runs', 'run_miles']); f.flush()
for r in range(rounds):
    names = []
    procs = []
    for k in (0, 1):
        seed = seed0 + 2 * r + k
        name = 'out/cands/%s_%d.txt' % (os.path.basename(tab), seed); names.append(name)
        cmd = ['./bin/solve', 'data', tab, secs, str(seed), name, 'static', '40', '1', '60', '30'] + (['-1', '0'] + win if win else [])
        procs.append(subprocess.Popen(cmd, env={**os.environ, 'ACCEPT': 'rrt'}, stderr=subprocess.DEVNULL))
    for p in procs: p.wait()
    for name in names:
        try:
            d = int(subprocess.run(['./bin/sim', 'data', name, 'dur'], capture_output=True, text=True).stdout)
            mc = np.array([int(x) for sd in ('1', '2') for x in subprocess.run(['./bin/sim', 'data', name, 'mc', '20', sd, '1.0'], capture_output=True, text=True).stdout.split()])
            subprocess.run(['python3', 'src/report.py', 'data', name, name[:-4]], capture_output=True)
            R = json.load(open(name[:-4] + '.json')); S = R['summary']
            mcst = [x['miss_cost'] for x in R['legs'] if x['kind'] == 'ride' and x.get('miss_cost')]
            row = [name, tab, h(d), h(S['start'] % 86400), h(int(np.median(mc))), h(int(np.percentile(mc, 90))), 'stuck' if min(mcst) < 0 else round(max(mcst) / 60), S['runs'], S['run_miles_street']]
            w.writerow(row); f.flush(); print(*row)
        except Exception as e:
            print('failed', name, e)
