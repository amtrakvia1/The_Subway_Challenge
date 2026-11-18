#!/usr/bin/env python3
"""Long unattended route search. Keeps JOBS solver processes busy until the deadline, scores every finished route,
and keeps a leaderboard. Safe to stop (Ctrl-C) and restart: results accumulate in out/search/.

usage: search_driver.py --hours 8 [--jobs N] [--secs 1800] [--free-frac 0.2] [--elite-frac 0.35]

Each job is a randomly chosen configuration:
  tables      tab/k4 (2 min margin on every change, 70% of jobs) or tab/s0 (no margin, 30%)
  endpoints   start in the Rockaways (Far Rockaway or Rockaway Park) between 00:00 and 04:00, finish at
              Flushing-Main St (what Matthew Ahn did for both his records); --free-frac of jobs are unconstrained
  init        fresh ("static" first stage) or, --elite-frac of the time, a route from the current top 10
Scoring: on-time duration (bin/sim dur) and the real-data delay model (bin/sim mc, 30 days, fixed seed so all routes
face the same days). Leaderboard order: median finish under delays. Top 20 kept in out/search/top/.
"""
import argparse, os, sys, json, time, random, subprocess, csv, shutil, glob
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument('--hours', type=float, default=8)
ap.add_argument('--jobs', type=int, default=os.cpu_count() or 2)
ap.add_argument('--secs', type=int, default=1800)
ap.add_argument('--free-frac', type=float, default=0.2)
ap.add_argument('--elite-frac', type=float, default=0.35)
ap.add_argument('--samples', type=int, default=30)
a = ap.parse_args()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
OUT = 'out/search'; os.makedirs(OUT + '/runs', exist_ok=True); os.makedirs(OUT + '/top', exist_ok=True)
REC = 22 * 3600 + 14 * 60 + 10
h = lambda s: '%d:%02d' % (s // 3600, s % 3600 // 60)
net = json.load(open('data/net.json'))
st, da = net['stations'], net['datoms']
start_atoms = [k for k, d in enumerate(da) if st[d['stations'][0]]['id'] in ('H11', 'H15')]
end_atoms = [k for k, d in enumerate(da) if st[d['stations'][-1]]['id'] == '701']
assert start_atoms and end_atoms, 'could not find the Rockaway / Flushing segments in data/net.json'
LB = OUT + '/leaderboard.csv'
FIELDS = ['file', 'config', 'on_time', 'median', 'p10', 'p90', 'beat_record_days', 'days', 'start', 'start_station', 'end_station',
          'runs_mi', 'median_s', 'on_time_s']


def log(*x):
    line = time.strftime('%Y-%m-%d %H:%M:%S ') + ' '.join(map(str, x))
    print(line, flush=True)
    open(OUT + '/log.txt', 'a').write(line + '\n')


def board():
    if not os.path.exists(LB):
        return []
    return sorted(csv.DictReader(open(LB)), key=lambda r: (int(r['median_s']), int(r['on_time_s'])))


def score(f, cfg):
    d = int(subprocess.run(['./bin/sim', 'data', f, 'dur'], capture_output=True, text=True).stdout)
    mc = np.array([int(x) for x in subprocess.run(['./bin/sim', 'data', f, 'mc', str(a.samples), '7', '1.0'],
                                                   capture_output=True, text=True).stdout.split()])
    mc = np.where(mc > 0, mc, 40 * 3600)
    subprocess.run(['python3', 'src/report.py', 'data', f, f[:-4]], capture_output=True)
    R = json.load(open(f[:-4] + '.json')); S = R['summary']; L = R['legs']
    if S['stations_visited'] != S['stations_total']:
        log('REJECT (missing stations)', f); return None
    row = dict(file=f, config=cfg, on_time=h(d), median=h(int(np.median(mc))), p10=h(int(np.percentile(mc, 10))),
               p90=h(int(np.percentile(mc, 90))), beat_record_days=int((mc < REC).sum()), days=len(mc),
               start=h(S['start'] % 86400), start_station=L[0]['from'], end_station=L[-1]['to'],
               runs_mi=S['run_miles_street'], median_s=int(np.median(mc)), on_time_s=d)
    new = not os.path.exists(LB)
    with open(LB, 'a', newline='') as fh:
        w = csv.DictWriter(fh, FIELDS)
        if new: w.writeheader()
        w.writerow(row)
    top = board()[:20]
    keep = {r['file'] for r in top}
    for old in glob.glob(OUT + '/top/*.txt'):
        if os.path.join(OUT, 'runs', os.path.basename(old)) not in keep: os.remove(old)
    for r in top:
        shutil.copy(r['file'], OUT + '/top/' + os.path.basename(r['file']))
    return row


def launch(seed):
    tab = 'tab/s0' if random.random() < 0.3 else 'tab/k4'
    free = random.random() < a.free_frac
    elite = [r['file'] for r in board()[:10] if os.path.exists(r['file'])]
    init = random.choice(elite) if (elite and random.random() < a.elite_frac) else 'static'
    if init != 'static' and not free:
        # an elite route may come from a free run; only reuse it for constrained runs if it satisfies the endpoints
        L = open(init).read().split()
        if int(L[2]) not in start_atoms or int(L[-1]) not in end_atoms: init = 'static'
    cfg = '%s %s %s' % (tab.split('/')[1], 'free' if free else 'rock->flushing', 'elite' if init != 'static' else 'fresh')
    f = '%s/runs/r%06d.txt' % (OUT, seed)
    env = {**os.environ, 'ACCEPT': 'rrt', 'SHARED_TABLES': '1'}
    args = ['./bin/solve', 'data', tab, str(a.secs), str(seed), f, init, '40', '1', '60', '30']
    if not free:
        env['START_ATOMS'] = ','.join(map(str, start_atoms)); env['END_ATOMS'] = ','.join(map(str, end_atoms))
        args += ['-1', '0', '0', '480']
    p = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=open(f[:-4] + '.log', 'w'))
    return p, f, cfg


deadline = time.time() + a.hours * 3600
seed = int(time.time()) % 1000000
running = []
if not board():
    for f in sorted(glob.glob('seeds/*.txt')):          # known good routes, so elite restarts have material from the start
        dst = OUT + '/runs/' + os.path.basename(f); shutil.copy(f, dst)
        r = score(dst, 'seed')
        if r: log('seed', os.path.basename(f), 'on time', r['on_time'], 'median', r['median'])
log('search start: %.1f h, %d jobs, %d s per job' % (a.hours, a.jobs, a.secs))
try:
    while True:
        while len(running) < a.jobs and time.time() + a.secs < deadline:
            seed += 1; running.append(launch(seed))
        if not running:
            break
        time.sleep(10)
        for job in list(running):
            p, f, cfg = job
            if p.poll() is None:
                continue
            running.remove(job)
            if os.path.exists(f):
                r = score(f, cfg)
                if r:
                    best = board()[0]
                    log('%s  [%s]  on time %s  median %s  p90 %s | best so far: median %s (%s)' % (
                        os.path.basename(f), cfg, r['on_time'], r['median'], r['p90'], best['median'], os.path.basename(best['file'])))
except KeyboardInterrupt:
    log('stopped by user')
    for p, _, _ in running: p.terminate()
log('search end. leaderboard: ' + LB)
