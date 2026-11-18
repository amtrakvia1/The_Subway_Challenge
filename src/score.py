#!/usr/bin/env python3
"""Score existing solution files and append them to out/candidates.csv.
usage: score.py <tables_label> file1.txt [file2.txt ...]"""
import sys, subprocess, json, csv
import numpy as np
h = lambda s: '%d:%02d' % (s // 3600, s % 3600 // 60)
w = csv.writer(open('out/candidates.csv', 'a', newline=''))
for name in sys.argv[2:]:
    d = int(subprocess.run(['./bin/sim', 'data', name, 'dur'], capture_output=True, text=True).stdout)
    mc = np.array([int(x) for sd in ('1', '2') for x in subprocess.run(['./bin/sim', 'data', name, 'mc', '20', sd, '1.0'], capture_output=True, text=True).stdout.split()])
    subprocess.run(['python3', 'src/report.py', 'data', name, name[:-4]], capture_output=True)
    R = json.load(open(name[:-4] + '.json')); S = R['summary']
    m = [x['miss_cost'] for x in R['legs'] if x['kind'] == 'ride' and x.get('miss_cost')]
    row = [name, sys.argv[1], h(d), h(S['start'] % 86400), h(int(np.median(mc))), h(int(np.percentile(mc, 90))),
           'stuck' if min(m) < 0 else round(max(m) / 60), S['runs'], S['run_miles_street']]
    w.writerow(row); print(*row)
