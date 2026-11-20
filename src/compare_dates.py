#!/usr/bin/env python3
"""Compare attempt dates: how much does each date's planned work cost, and what is the best route for that date?

usage: compare_dates.py <supplemented_gtfs_dir> <YYYYMMDD> [<YYYYMMDD> ...] [--secs 900] [--days 60]

Per date: build dates/<D>/ (build_dated.py: same structure as data/, that date's trains), k4 tables, then
  fixed  - score the routes in seeds/ as planned for a regular weekday on that date (a segment that has no train
           all day is swapped for a served option of its group, usually the other direction)
  tuned  - re-anneal the 2 best of them on that date's k4 tables (2 parallel solver jobs, --secs each, pool of 16
           near-best routes each) and score everything
Scores: median and p90 finish over --days simulated days (real-data delay model, seed 7; the same days for every route
and date), score = median + 0.25 x (p90 - median). Also scored on the regular weekday network (data/) as a baseline.
Output: out/dates/summary.csv, out/dates/<D>/ (routes + itineraries), out/dates/log.txt.
The tables for a date (1 GB) are deleted after that date is done.
"""
import argparse, os, json, time, subprocess, csv, glob, shutil
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument('gtfs')
ap.add_argument('dates', nargs='+')
ap.add_argument('--secs', type=int, default=900)
ap.add_argument('--days', type=int, default=60)
ap.add_argument('--tail', type=float, default=0.25)
ap.add_argument('--out', default='out/dates')
a = ap.parse_args()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
OUT = a.out; os.makedirs(OUT, exist_ok=True)
REC = 22 * 3600 + 14 * 60 + 10
h = lambda s: '%d:%02d' % (s // 3600, s % 3600 // 60)
DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
net = json.load(open('data/net.json'))
st, da = net['stations'], net['datoms']
start_atoms = [k for k, d in enumerate(da) if st[d['stations'][0]]['id'] in ('H11', 'H15')]
refs = sorted(glob.glob('seeds/*.txt'))


def log(*x):
    line = time.strftime('%Y-%m-%d %H:%M:%S ') + ' '.join(map(str, x))
    print(line, flush=True)
    open(OUT + '/log.txt', 'a').write(line + '\n')


def score(data, files):
    lst = OUT + '/.list.txt'
    open(lst, 'w').write('\n'.join(files) + '\n')
    o = subprocess.run(['./bin/sim', data, lst, 'mcbatch', str(a.days), '7', '1.0'], capture_output=True, text=True).stdout
    M = np.array([[int(x) for x in l.split('\t')] for l in o.strip().split('\n')]).reshape(a.days, len(files))
    M = np.where(M > 0, M, 40 * 3600)
    res = []
    for k, f in enumerate(files):
        med, p90 = float(np.median(M[:, k])), float(np.percentile(M[:, k], 90))
        d = int(subprocess.run(['./bin/sim', data, f, 'dur'], capture_output=True, text=True).stdout)
        res.append(dict(file=f, on_time_s=d, median_s=int(med), p90_s=int(p90), score_s=int(med + a.tail * (p90 - med)),
                        beat=int((M[:, k] < REC).sum())))
    return res


def complete(data, f):
    subprocess.run(['python3', 'src/report.py', data, f, f[:-4]], capture_output=True)
    try:
        S = json.load(open(f[:-4] + '.json'))['summary']
        return S['stations_visited'] == S['stations_total']
    except Exception:
        return False


rows = []


def summarize(label, dow, fixed, tuned):
    bf = min(fixed, key=lambda r: r['score_s'])
    bt = min(tuned, key=lambda r: r['score_s']) if tuned else bf
    row = dict(date=label, day=dow, best_fixed=os.path.basename(bf['file']), fixed_on_time=h(bf['on_time_s']),
               fixed_median=h(bf['median_s']), fixed_p90=h(bf['p90_s']), best_tuned=os.path.basename(bt['file']),
               tuned_on_time=h(bt['on_time_s']), tuned_median=h(bt['median_s']), tuned_p90=h(bt['p90_s']),
               tuned_beat_days=bt['beat'], days=a.days, tuned_score_s=bt['score_s'], fixed_score_s=bf['score_s'])
    rows.append(row)
    with open(OUT + '/summary.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, list(row.keys()), restval=''); w.writeheader(); w.writerows(rows)
    log('%s %s | fixed: best %s on time %s median %s p90 %s | tuned: best %s on time %s median %s p90 %s, beat record %d/%d' % (
        label, dow, row['best_fixed'], row['fixed_on_time'], row['fixed_median'], row['fixed_p90'], row['best_tuned'],
        row['tuned_on_time'], row['tuned_median'], row['tuned_p90'], bt['beat'], a.days))


log('compare dates %s: %d s x 2 tuning jobs per date, %d simulated days, routes from seeds/: %s' % (
    ' '.join(a.dates), a.secs, a.days, ' '.join(os.path.basename(f) for f in refs)))
base = score('data', refs)
summarize('regular', 'weekday', base, [])
seed = 500000
for D in a.dates:
    dow = DOW[time.strptime(D, '%Y%m%d').tm_wday]
    data, tab, od = 'dates/' + D, 'tab/d' + D, OUT + '/' + D
    os.makedirs(od, exist_ok=True)
    if not os.path.exists(data + '/conn.bin'):
        subprocess.run(['python3', 'src/build_dated.py', a.gtfs, 'data', data, D], check=True)
    t = time.time()
    if not os.path.exists(tab + '_D.bin'):
        subprocess.run(['./bin/tables', data, '4', tab], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log('%s: tables built in %.0f s' % (D, time.time() - t))
    # feasibility: every group needs an option that some train serves end to end at some time of day
    dn = json.load(open(data + '/net.json'))
    A = np.fromfile(tab + '_A.bin', dtype=np.uint16).reshape(len(dn['datoms']), -1)
    dead = [g for g in dn['groups'] if not any((A[o] != 65535).any() for o in g['options'])]
    if dead:
        c = np.fromfile(data + '/conn.bin', dtype=np.int32).reshape(-1, 6)
        served_st = set((c[:, 0] // 2).tolist()) | set((c[:, 1] // 2).tolist())
        names = sorted({dn['stations'][s]['name'] for g in dead for s in g['covers'] if s not in served_st}) or \
            sorted({dn['stations'][s]['name'] for g in dead for s in g['covers']})
        log('%s %s: NOT POSSIBLE - no train serves %s all day (planned work)' % (D, dow, ', '.join(names)))
        rows.append(dict(date=D, day=dow, best_fixed='not possible: no trains at ' + '; '.join(names)))
        with open(OUT + '/summary.csv', 'w', newline='') as fh:
            w = csv.DictWriter(fh, list(rows[0].keys()), restval=''); w.writeheader(); w.writerows(rows)
        for f in glob.glob(tab + '_*.bin'): os.remove(f)
        continue
    # planned routes, minimally adapted: a segment with no train all day on this date is replaced by a served option of
    # the same group (the other direction if possible); everything else is ridden as planned
    served = {k for k in range(A.shape[0]) if (A[k] != 65535).any()}
    gof = {}
    for g in dn['groups']:
        for o in g['options']: gof.setdefault(o, g['options'])
    rev = {}
    for i, d1 in enumerate(dn['datoms']):
        for j, d2 in enumerate(dn['datoms']):
            if d1['atom'] == d2['atom'] and d1['dir'] != d2['dir']: rev[i] = j
    adapted = []
    for f in refs:
        v = open(f).read().split(); head, seq = v[:2], [int(x) for x in v[2:]]
        nrep = 0
        for i, x in enumerate(seq):
            if x in served: continue
            opts = [o for o in gof.get(x, []) if o in served]
            y = rev[x] if rev.get(x) in opts else (opts[0] if opts else x)
            nrep += y != x; seq[i] = y
        g = od + '/' + os.path.basename(f)
        open(g, 'w').write(' '.join(head) + '\n' + '\n'.join(map(str, seq)) + '\n')
        adapted.append(g)
        if nrep: log('  %s: %d segment(s) without trains replaced' % (os.path.basename(f), nrep))
    fixed = score(data, adapted)
    for r in sorted(fixed, key=lambda r: r['score_s']):
        log('  fixed %-22s on time %s  median %s  p90 %s' % (os.path.basename(r['file']), h(r['on_time_s']), h(r['median_s']), h(r['p90_s'])))
    inits = [r['file'] for r in sorted(fixed, key=lambda r: r['score_s'])[:2]]
    procs, outs = [], []
    for init in inits:
        seed += 1
        f = '%s/t%06d.txt' % (od, seed)
        env = {**os.environ, 'ACCEPT': 'rrt', 'SHARED_TABLES': '1', 'POOL': f[:-4] + '_p', 'POOL_N': '16', 'KEEP_PARTTIME': '1',
               'START_ATOMS': ','.join(map(str, start_atoms))}
        procs.append(subprocess.Popen(['./bin/solve', data, tab, str(a.secs), str(seed), f, init, '40', '1', '60', '30',
                                       '-1', '0', '0', '480'], env=env, stdout=subprocess.DEVNULL, stderr=open(f[:-4] + '.log', 'w')))
        outs.append(f)
    for p in procs: p.wait()
    cands = [f for o in outs for f in [o] + sorted(glob.glob(o[:-4] + '_p_*.txt'))
             if os.path.exists(f) and len(open(f).read().split()) > 2]
    tuned = score(data, cands) if cands else []
    if not cands: log('%s: the tuning jobs produced no route (see %s/*.log)' % (D, od))
    tuned.sort(key=lambda r: r['score_s'])
    good = []
    for r in tuned:                      # itinerary check on the date's own trains, best first
        if complete(data, r['file']): good.append(r)
        if len(good) >= 3: break
    for r in fixed: complete(data, r['file'])
    summarize(D, dow, fixed, good)
    for f in glob.glob(tab + '_*.bin'): os.remove(f)
log('done: ' + OUT + '/summary.csv')
