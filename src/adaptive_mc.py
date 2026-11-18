#!/usr/bin/env python3
"""Monte Carlo with a rider who RE-PLANS: whenever they finish a segment more than LATE seconds behind the current plan,
they re-optimize the order of everything left (bin/solve, fixed start, on the given tables, a few seconds) and carry on.
Delays come from the model fitted to real data (bin/sim mctrace). Same seeds -> same delays, so routes compare fairly.
usage: adaptive_mc.py solution.txt N [tables=tab/s0] [late_sec=240] [replan_secs=3]"""
import sys, os, json, subprocess, numpy as np
sol, N = sys.argv[1], int(sys.argv[2])
tab = sys.argv[3] if len(sys.argv) > 3 else 'tab/s0'
LATE = int(sys.argv[4]) if len(sys.argv) > 4 else 240
RS = sys.argv[5] if len(sys.argv) > 5 else '3'
net = json.load(open('data/net.json')); da = net['datoms']
L = open(sol).read().split(); t0 = int(L[0]) * 30; seq0 = list(map(int, L[2:]))
tag = '%d_%d' % (os.getpid(), abs(hash(sol)) % 10000)

def write(seq, path): open(path, 'w').write('0 0\n' + '\n'.join(map(str, seq)) + '\n')
def trace(mode, seq, extra):
    p = '/tmp/am_%s.txt' % tag; write(seq, p)
    out = subprocess.run(['./bin/sim', 'data', p, mode] + list(map(str, extra)), capture_output=True, text=True).stdout.split('\n')
    rows = [tuple(map(int, l.split('\t'))) for l in out if l.count('\t') == 3]
    return rows, 'STUCK' in out

FUTURE_N = 6
def one(seed):
    seq, pos, plat, t, replans = list(seq0), 0, -1, t0, 0
    decisions = [0]
    while True:
        plan, _ = trace('trace2', seq, [pos, plat, t])
        real, stuck = trace('mctrace', seq, [seed, 1.0, pos, plat, t])
        pe = {r[0]: r[3] for r in plan}
        k = next((r for r in real if r[0] >= pos and r[3] - pe.get(r[0], 1 << 40) > LATE), None)
        if k is None and stuck and real: k = real[-1]
        if k is None or k[0] + 1 >= len(seq):
            return (real[-1][3] if real and not stuck else 40 * 3600 + t0) - t0, replans
        i = k[0]; pos, plat, t = i + 1, da[seq[i]]['end_p'], k[3]
        rem = '/tmp/am_rem_%s.txt' % tag; out = '/tmp/am_out_%s.txt' % tag
        open(rem, 'w').write('%d 0\n' % ((t + 29) // 30) + '\n'.join(map(str, seq[pos:])) + '\n')
        cands = [seq]
        for tb in ('tab/s0', 'tab/k4'):
            subprocess.run(['./bin/solve', 'data', tb, RS, str(seed), out, rem, '1.0', '0.1', '1', '0.8', str(plat), str((t + 29) // 30)],
                           env={**os.environ, 'ACCEPT': 'rrt'}, capture_output=True)
            c = seq[:pos] + list(map(int, open(out).read().split()[2:]))
            if c not in cands: cands.append(c)
        # choose by expected finish over FUTURE_N sampled futures (independent of the true day)
        def expected(c):
            v = []
            for j in range(FUTURE_N):
                rr, st = trace('mctrace', c, [50000 + 97 * seed + j, 1.0, pos, plat, t])
                v.append(rr[-1][3] if rr and not st else t + 40 * 3600)
            return np.mean(v)
        scores = [expected(c) for c in cands]
        best = int(np.argmin(scores))
        if best != 0: replans += 1
        seq = cands[best]; decisions[0] += 1
        if decisions[0] > 25: return (trace('mctrace', seq, [seed, 1.0, pos, plat, t])[0][-1][3] - t0), replans

res = [one(100 + i) for i in range(N)]
d = np.array([r[0] for r in res]); h = lambda s: '%d:%02d' % (s // 3600, s % 3600 // 60)
print('%s adaptive: median %s  p10 %s  p90 %s | beat record %d/%d | replans per day %.1f' % (
    sol, h(int(np.median(d))), h(int(np.percentile(d, 10))), h(int(np.percentile(d, 90))), (d < 80050).sum(), N, np.mean([r[1] for r in res])))
