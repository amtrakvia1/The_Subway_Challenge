#!/usr/bin/env python3
"""Cross-checks between the three independent implementations of the travel rules.
run: python3 tests/test_consistency.py [solution_file]
 1. table lookups (tables.cpp)  ==  direct simulation (sim.cpp)   for a full route
 2. table lookups               ==  pure-Python reference (pycsa)  for random point-to-point queries
 3. the route's actual rides stop at every station
(tables_risk.cpp with risk 0 is byte-identical to tables.cpp; checked by `make test-risk`.)
"""
import sys, os, json, random, subprocess
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import pycsa
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sol = sys.argv[1] if len(sys.argv) > 1 else root + '/out/best_fast.txt'
net = pycsa.load(root + '/data'); n = net[0]; da = n['datoms']; NT = 2880
src = sorted(set(d['end_p'] for d in da)); tgt = sorted(set(d['start_p'] for d in da))
D = np.memmap(root + '/tab/s0_D.bin', dtype=np.uint16, mode='r').reshape(len(src), len(tgt), NT)
A = np.memmap(root + '/tab/s0_A.bin', dtype=np.uint16, mode='r').reshape(len(da), NT)

L = open(sol).read().split(); t0 = int(L[0]); seq = list(map(int, L[2:]))
t = t0; cur = None
for a in seq:
    if cur is not None: t += int(D[src.index(cur), tgt.index(da[a]['start_p']), t % NT])
    t += int(A[a, t % NT]); cur = da[a]['end_p']
simd = int(subprocess.run([root + '/bin/sim', root + '/data', sol, 'dur'], capture_output=True, text=True).stdout)
assert (t - t0) * 30 == simd, ('table vs sim', (t - t0) * 30, simd)
print('1 ok: table == simulator  (%d s)' % simd)

random.seed(5); bad = 0
for _ in range(40):
    p, q, tt = random.choice(src), random.choice(tgt), random.randrange(NT)
    ref, _ = pycsa.deadhead(net, p, tt, q)
    if ref - tt != int(D[src.index(p), tgt.index(q), tt]): bad += 1; print('  mismatch', p, q, tt, ref - tt, int(D[src.index(p), tgt.index(q), tt]))
assert bad == 0
print('2 ok: table == python reference on 40 random queries')

rows = subprocess.run([root + '/bin/sim', root + '/data', sol, 'itin'], capture_output=True, text=True).stdout.splitlines()[1:]
seen = set()
for r in rows:
    f = r.split('\t')
    if f[0] == '0': seen |= {int(x.split('@')[0]) // 2 for x in f[7].split(',')}
assert len(seen) == len(n['stations']), len(seen)
print('3 ok: all %d stations are stopped at' % len(seen))
