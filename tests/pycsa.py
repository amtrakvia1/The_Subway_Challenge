"""Tiny reference implementation (pure Python) of the deadhead rules, for cross-checking C++."""
import json, numpy as np
def load(d='data'):
    n = json.load(open(d + '/net.json'))
    c = np.fromfile(d + '/conn.bin', dtype=np.int32).reshape(-1, 6)
    x = np.fromfile(d + '/xfer.bin', dtype=np.int32).reshape(-1, 3)
    w = np.fromfile(d + '/walk.bin', dtype=np.int32).reshape(-1, 3)
    meta = dict(l.split() for l in open(d + '/meta.txt'))
    return n, c, x, w, {k: int(v) for k, v in meta.items()}

def deadhead(net, p, t, q, slack=0, verbose=False):
    n, c, x, w, meta = net
    NT = meta['NT']; same = meta['XSAME'] + slack; beta = meta['XPLAT'] + slack
    S = len(n['stations'])
    sx = {}
    for a, b, tt in list(x) + list(w):
        sx.setdefault(int(a), []).append((int(b), int(tt) + slack))
    free = {p: t}; pred = {p: ('start',)}
    def relax(s, fromp, tm, via):
        for y, v in [(fromp ^ 1, tm + same)] + [(2 * b + l, tm + tt) for b, tt in sx.get(s, []) for l in (0, 1)]:
            if v < free.get(y, 1 << 30): free[y] = v; pred[y] = ('edge', fromp, tm, via)
    relax(p // 2, p, t, None)
    best = free.get(q, 1 << 30); bestc = None
    on = {}
    day = 0
    order = np.argsort(c[:, 2], kind='stable')
    T = t
    # iterate conns cyclically starting at tick t
    start = np.searchsorted(c[:, 2], t % NT)
    base = t - t % NT
    idxs = list(range(start, len(c))) + list(range(0, len(c)))
    bases = [base] * (len(c) - start) + [base + NT] * len(c)
    for ci, bs in zip(idxs, bases):
        dp, ap, dt, at, trip, nx = map(int, c[ci])
        d = bs + dt
        if d >= best: break
        key = (ci, bs)
        if key not in on:
            if free.get(dp, 1 << 30) > d: continue
            on[key] = ('board', dp, d, trip)
        a = d + at - dt
        if nx >= 0:
            nb = bs if c[nx, 2] > dt else bs + NT
            on.setdefault((nx, nb), on[key])
        if ap == q:
            if a < best: best = a; bestc = (on[key], a)
            continue
        if a + beta < free.get(ap, 1 << 30): free[ap] = a + beta; pred[ap] = ('alight', on[key], a)
        relax(ap // 2, ap, a, on[key])
        if free.get(q, 1 << 30) < best: best = free[q]; bestc = pred[q]
    return best, bestc
