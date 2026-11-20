#!/usr/bin/env python3
"""Plateau search: improve top routes on the delay model directly, by walking among routes the k4 tables rate (nearly) equal.

Why: routes with the same k4 cost differ by up to ~1 h in median under delays, and the solver cannot see that. So each
walker repeatedly asks the solver for many near-equal-cost variants of its current route (a short low-threshold walk on
tab/k4 from that route, POOL=... keeps the end state of every short cycle), scores them all on the same training days
(bin/sim mcbatch), and moves to the best one if it beats the current route. Score = median + 0.25 x (p90 - median), so a
route cannot win on median while hiding a fragile tail. Picking the best of many routes on the same days mostly picks
lucky ones, so a move must ALSO beat the current route on a second, independent set of confirmation days, and the final
ranking is checked on held-out days (a third seed).

usage: plateau.py --hours 2 [--jobs 2] [--starts 4] [--secs 90] [--thr 6] [--train 60] [--test 150]
Output: out/plateau/log.txt, scores.csv (every route scored), final.csv (held-out check), runs/ (routes + itineraries)
"""
import argparse, os, json, time, random, subprocess, csv, glob, shutil
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument('--hours', type=float, default=2)
ap.add_argument('--jobs', type=int, default=os.cpu_count() or 2)
ap.add_argument('--starts', type=int, default=4, help='start from the best N distinct routes of out/search/final.csv')
ap.add_argument('--secs', type=int, default=90, help='solver seconds per step')
ap.add_argument('--thr', type=float, default=6, help='walk threshold in 30 s ticks above the best k4 cost of the step')
ap.add_argument('--margin', type=int, default=12, help='keep variants up to this many ticks above the best k4 cost')
ap.add_argument('--patience', type=int, default=3, help='steps without improvement before a walker restarts')
ap.add_argument('--train', type=int, default=60)
ap.add_argument('--train-seed', type=int, default=7)
ap.add_argument('--confirm', type=int, default=60, help='a move must also win on these independent days')
ap.add_argument('--confirm-seed', type=int, default=13)
ap.add_argument('--test', type=int, default=150)
ap.add_argument('--test-seed', type=int, default=99)
ap.add_argument('--out', default='out/plateau')
ap.add_argument('--tail', type=float, default=0.25, help='score = median + tail x (p90 - median)')
a = ap.parse_args()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
OUT = a.out; os.makedirs(OUT + '/runs', exist_ok=True)
REC = 22 * 3600 + 14 * 60 + 10
h = lambda s: '%d:%02d' % (s // 3600, s % 3600 // 60)
net = json.load(open('data/net.json'))
st, da = net['stations'], net['datoms']
start_atoms = [k for k, d in enumerate(da) if st[d['stations'][0]]['id'] in ('H11', 'H15')]


def log(*x):
    line = time.strftime('%Y-%m-%d %H:%M:%S ') + ' '.join(map(str, x))
    print(line, flush=True)
    open(OUT + '/log.txt', 'a').write(line + '\n')


def key(f):
    v = open(f).read().split()
    return (int(v[0]) % 2880, tuple(v[2:]))


def batch(files, n, seed):
    """durations (days x routes) on n simulated days; failed days count as 40 h"""
    lst = OUT + '/.list_%d.txt' % os.getpid()
    open(lst, 'w').write('\n'.join(files) + '\n')
    o = subprocess.run(['./bin/sim', 'data', lst, 'mcbatch', str(n), str(seed), '1.0'], capture_output=True, text=True).stdout
    M = np.array([[int(x) for x in l.split('\t')] for l in o.strip().split('\n')]).reshape(n, len(files))
    return np.where(M > 0, M, 40 * 3600)


def stats(col):
    med, p90 = float(np.median(col)), float(np.percentile(col, 90))
    return dict(median_s=int(med), p90_s=int(p90), score_s=int(med + a.tail * (p90 - med)), beat=int((col < REC).sum()))


def on_time(f):
    return int(subprocess.run(['./bin/sim', 'data', f, 'dur'], capture_output=True, text=True).stdout)


def complete(f):
    """every station visited (report.py checks the concrete itinerary); writes the .md/.json itinerary next to f"""
    subprocess.run(['python3', 'src/report.py', 'data', f, f[:-4]], capture_output=True)
    try:
        S = json.load(open(f[:-4] + '.json'))['summary']
        return S['stations_visited'] == S['stations_total']
    except Exception:
        return False


SC = OUT + '/scores.csv'
FIELDS = ['file', 'walker', 'parent', 'k4_cost', 'on_time', 'median', 'p90', 'score', 'beat_days', 'days', 'on_time_s',
          'median_s', 'p90_s', 'score_s']
seen = {}
conf = {}                      # file -> score on the confirmation days


def confirm_score(files):
    need = [f for f in files if f not in conf]
    if need:
        M = batch(need, a.confirm, a.confirm_seed)
        for k, f in enumerate(need): conf[f] = stats(M[:, k])['score_s']
    return [conf[f] for f in files]


def record(f, walker, parent, S):
    new = not os.path.exists(SC)
    with open(SC, 'a', newline='') as fh:
        w = csv.DictWriter(fh, FIELDS)
        if new: w.writeheader()
        d = on_time(f)
        w.writerow(dict(file=f, walker=walker, parent=parent, k4_cost=open(f).read().split()[1], on_time=h(d),
                        median=h(S['median_s']), p90=h(S['p90_s']), score=h(S['score_s']), beat_days=S['beat'], days=a.train,
                        on_time_s=d, **{k: S[k] for k in ('median_s', 'p90_s', 'score_s')}))


# start routes: best distinct routes of the last long search, by the same tail-aware score on its 150-day rescore
src = sorted(csv.DictReader(open('out/search/final.csv')),
             key=lambda r: int(r['median_s']) + a.tail * (sum(int(x) * m for x, m in zip(r['p90'].split(':'), (3600, 60))) - int(r['median_s'])))
starts = []
for r in src:
    f = r['file']
    if not os.path.exists(f) or int(open(f).read().split()[2]) not in start_atoms: continue
    if key(f) in {key(x) for x in starts}: continue
    dst = OUT + '/runs/' + os.path.basename(f)
    if not os.path.exists(dst): shutil.copy(f, dst)
    starts.append(dst)
    if len(starts) >= a.starts: break
M = batch(starts, a.train, a.train_seed)
cur = {}
for k, f in enumerate(starts):
    S = stats(M[:, k]); seen[key(f)] = f; cur[f] = S
    record(f, -1, '', S)
    log('start %s  median %s  p90 %s  score %s' % (os.path.basename(f), h(S['median_s']), h(S['p90_s']), h(S['score_s'])))
best_f = min(cur, key=lambda f: cur[f]['score_s'])
log('plateau search: %.1f h, %d walkers, %d s per step, threshold %g ticks, %d training days (seed %d)' % (
    a.hours, a.jobs, a.secs, a.thr, a.train, a.train_seed))

walkers = [dict(id=i, file=starts[i % len(starts)], stall=0, next_start=i + 1) for i in range(a.jobs)]
for w in walkers: w['S'] = cur[w['file']]
deadline = time.time() + a.hours * 3600
seed = int(time.time()) % 1000000
running = []


def launch(w):
    global seed
    seed += 1
    out = '%s/runs/p%06d.txt' % (OUT, seed)
    env = {**os.environ, 'ACCEPT': 'rrt', 'SHARED_TABLES': '1', 'NOPOLISH': '1', 'POOL': out[:-4] + '_v',
           'POOL_N': '24', 'POOL_MARGIN': str(a.margin), 'START_ATOMS': ','.join(map(str, start_atoms))}
    args = ['./bin/solve', 'data', 'tab/k4', str(a.secs), str(seed), out, w['file'], str(a.thr), '1', '4', str(a.thr),
            '-1', '0', '0', '480']
    return dict(p=subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=open(out[:-4] + '.log', 'w')), out=out, w=w)


steps = moves = 0
while True:
    for w in walkers:
        if not any(j['w'] is w for j in running) and time.time() + a.secs < deadline:
            running.append(launch(w))
    if not running: break
    time.sleep(3)
    for j in list(running):
        if j['p'].poll() is None: continue
        running.remove(j); w = j['w']; steps += 1
        cands = [f for f in [j['out']] + sorted(glob.glob(j['out'][:-4] + '_v_*.txt')) if os.path.exists(f)]
        fresh = []
        for f in cands:
            k = key(f)
            if k in seen: continue
            seen[k] = f; fresh.append(f)
        if fresh:
            M = batch(fresh, a.train, a.train_seed)
            Ss = [stats(M[:, k]) for k in range(len(fresh))]
            for f, S in zip(fresh, Ss): record(f, w['id'], w['file'], S)
            order = sorted(range(len(fresh)), key=lambda k: Ss[k]['score_s'])
            bk = next((k for k in order if Ss[k]['score_s'] < w['S']['score_s'] and complete(fresh[k])), None)
            if bk is not None:
                cn, cc = confirm_score([fresh[bk], w['file']])
                if cn >= cc:
                    log('walker %d: %s wins on training days (%s vs %s) but not on confirmation days (%s vs %s)' % (
                        w['id'], os.path.basename(fresh[bk]), h(Ss[bk]['score_s']), h(w['S']['score_s']), h(cn), h(cc)))
                    bk = None
        else:
            bk = None
        if bk is not None:
            moves += 1
            log('walker %d: %s -> %s  score %s -> %s  (median %s, p90 %s; confirmation %s -> %s; %d new variants)' % (
                w['id'], os.path.basename(w['file']), os.path.basename(fresh[bk]), h(w['S']['score_s']), h(Ss[bk]['score_s']),
                h(Ss[bk]['median_s']), h(Ss[bk]['p90_s']), h(cc), h(cn), len(fresh)))
            w['file'], w['S'], w['stall'] = fresh[bk], Ss[bk], 0
            cur[w['file']] = w['S']
            if w['S']['score_s'] < cur[best_f]['score_s']:
                best_f = w['file']; log('  new best: %s score %s' % (os.path.basename(best_f), h(cur[best_f]['score_s'])))
        else:
            w['stall'] += 1
            if w['stall'] >= a.patience:          # restart: the overall best or the next start route
                nf = best_f if random.random() < 0.5 else starts[w['next_start'] % len(starts)]
                w['next_start'] += 1
                log('walker %d: no better variant in %d steps (%d new variants last step), restarting from %s' % (
                    w['id'], w['stall'], len(fresh), os.path.basename(nf)))
                w['file'], w['S'], w['stall'] = nf, cur[nf], 0

log('plateau search done: %d steps, %d moves. Held-out check on %d days (seed %d)' % (steps, moves, a.test, a.test_seed))
rows = sorted(csv.DictReader(open(SC)), key=lambda r: int(r['score_s']))
found = [r['file'] for r in rows if r['file'] not in starts]
pick = []                                                # the 12 best new routes (training score) and the start routes
for f in found:
    if len(pick) >= 12: break
    if complete(f): pick.append(f)
pick += starts
for f in starts: complete(f)
T = batch(pick, a.test, a.test_seed)
train = {r['file']: r for r in rows}
res = []
for k, f in enumerate(pick):
    S = stats(T[:, k]); tr = train[f]
    res.append(dict(file=f, start_route='yes' if f in starts else '', on_time=tr['on_time'], train_median=tr['median'],
                    train_p90=tr['p90'], test_median=h(S['median_s']), test_p90=h(S['p90_s']), test_p10=h(int(np.percentile(T[:, k], 10))),
                    test_score=h(S['score_s']), test_beat_days=S['beat'], test_days=a.test, test_score_s=S['score_s']))
res.sort(key=lambda r: r['test_score_s'])
with open(OUT + '/final.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, list(res[0].keys())); w.writeheader(); w.writerows(res)
for r in res[:8]:
    log('  held-out %-22s %s on time %s  train median %s p90 %s | test median %s p90 %s  beat %d/%d' % (
        os.path.basename(r['file']), '(start)' if r['start_route'] else '       ', r['on_time'], r['train_median'], r['train_p90'],
        r['test_median'], r['test_p90'], r['test_beat_days'], r['test_days']))
for f in glob.glob(OUT + '/.list_*'): os.remove(f)
log('plateau end: ' + OUT + '/final.csv')
