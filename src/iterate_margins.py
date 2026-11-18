#!/usr/bin/env python3
"""Targeted margins: put spare time only on connections that are expensive to miss.

Loop:  solve on tables with the current margin map -> find boarded trains whose miss cost is high ->
       require margin when arriving at that platform around that time -> rebuild tables -> re-solve.
Margins accumulate across iterations (a station/time once flagged stays flagged).
Each iteration solves two seeds in parallel: one continuing from the best route so far, one fresh.

usage: iterate_margins.py <start_solution> <iterations> <solve_secs>
log: out/iter/log.txt   routes: out/iter/it<k>_<seed>.txt   best: out/iter/best.txt
"""
import sys, os, json, subprocess, shutil, time
import numpy as np

start, iters, secs = sys.argv[1], int(sys.argv[2]), sys.argv[3]
os.makedirs('out/iter', exist_ok=True)
net = json.load(open('data/net.json'))
sidx = {s['id']: i for i, s in enumerate(net['stations'])}
log = open('out/iter/log.txt', 'a')
h = lambda s: '%d:%02d' % (s // 3600, s % 3600 // 60)
MISS_BIG, MISS_MED = 1200, 600          # seconds of finish-time lost if this train is missed
BEFORE, AFTER = 40, 20                  # margin window around the planned boarding, in 30 s ticks


def say(*a):
    line = time.strftime('%H:%M ') + ' '.join(map(str, a))
    print(line, flush=True); log.write(line + '\n'); log.flush()


def score(f):
    """on-time duration, delay-model median and p90 (40 samples), report json"""
    d = int(subprocess.run(['./bin/sim', 'data', f, 'dur'], capture_output=True, text=True).stdout)
    mc = np.array([int(x) for sd in ('1', '2') for x in
                   subprocess.run(['./bin/sim', 'data', f, 'mc', '20', sd, '1.0'], capture_output=True, text=True).stdout.split()])
    mc = np.where(mc > 0, mc, 40 * 3600)
    subprocess.run(['python3', 'src/report.py', 'data', f, f[:-4]], capture_output=True)
    return d, int(np.median(mc)), int(np.percentile(mc, 90)), json.load(open(f[:-4] + '.json'))


slack = {}                              # (platform, center_tick) -> margin ticks


def add_margins(route):
    n = 0
    for L in route['legs']:
        if L['kind'] != 'ride' or L.get('miss_cost') in (None, 0):
            continue
        mc = L['miss_cost']
        need = 4 if (mc < 0 or mc >= MISS_BIG) else 2 if mc >= MISS_MED else 0
        if not need:
            continue
        p = sidx[L['from_id']] * 2 + (L['dir'] == 'S')
        k = (p, (L['t0'] // 30) % 2880)
        if slack.get(k, 0) < need:
            slack[k] = need; n += 1
    return n


def write_map():
    rows = [(p, c - BEFORE, c + AFTER, m) for (p, c), m in slack.items()]
    np.asarray(rows if rows else [(0, 0, 0, 0)], dtype=np.int32).tofile('out/iter/slackmap.bin')


best_file = 'out/iter/best.txt'
shutil.copy(start, best_file)
d, med, p90, R = score(best_file)
best_key = (med, d)
say('start', start, 'on-time', h(d), 'median', h(med), 'p90', h(p90))
add_margins(R)

for it in range(1, iters + 1):
    write_map()
    t = time.time()
    subprocess.run(['./bin/tables', 'data', '-2', 'tab/it'], env={**os.environ, 'SLACKMAP': 'out/iter/slackmap.bin'},
                   capture_output=True, check=True)
    say('iter', it, 'margin windows', len(slack), 'tables built in %ds' % (time.time() - t))
    outs, procs = [], []
    for k, init in ((0, best_file), (1, 'static')):
        f = 'out/iter/it%d_%d.txt' % (it, k); outs.append(f)
        procs.append(subprocess.Popen(['./bin/solve', 'data', 'tab/it', secs, str(1000 * it + k), f, init, '40', '1', '60', '30'],
                                      env={**os.environ, 'ACCEPT': 'rrt'}, stderr=subprocess.DEVNULL))
    for p in procs:
        p.wait()
    for f in outs:
        if not os.path.exists(f):
            continue
        d, med, p90, R = score(f)
        worst = [L['miss_cost'] for L in R['legs'] if L['kind'] == 'ride' and L.get('miss_cost')]
        worst = 'stuck' if min(worst) < 0 else '+%d' % (max(worst) // 60)
        say('  ', os.path.basename(f), 'on-time', h(d), 'median', h(med), 'p90', h(p90), 'worst miss', worst,
            'start', h(R['summary']['start'] % 86400), 'runs %.1f mi' % R['summary']['run_miles_street'])
        added = add_margins(R)
        if (med, d) < best_key:
            best_key = (med, d); shutil.copy(f, best_file)
            say('   new best; added', added, 'margin windows')
say('done. best: median', h(best_key[0]), 'on-time', h(best_key[1]))
