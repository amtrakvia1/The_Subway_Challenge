#!/usr/bin/env python3
"""Mid-run re-plan: you have finished the first POS atoms of a route and are standing at the end of the last one.
Re-optimizes the ORDER of everything that is left (table-based annealing, a few seconds), then prints the first legs.

usage: replan.py data solution.txt POS NOW_HH:MM:SS [seconds=15] [tables=tab/r1]
   POS = number of atoms already completed (see "atom" numbers in route_*.json)
"""
import sys, os, json, subprocess
data, sol, pos, now = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
secs = sys.argv[5] if len(sys.argv) > 5 else '15'
tab = sys.argv[6] if len(sys.argv) > 6 else 'tab/r1'
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
n = json.load(open(data + '/net.json')); da = n['datoms']; st = n['stations']
L = open(sol).read().split(); seq = list(map(int, L[2:]))
h, m, s = (list(map(int, now.split(':'))) + [0])[:3]
tick = (h * 3600 + m * 60 + s + 29) // 30
plat = da[seq[pos - 1]]['end_p']
rem = '/tmp/replan_in.txt'
open(rem, 'w').write('%d 0\n' % tick + '\n'.join(map(str, seq[pos:])) + '\n')
keep = subprocess.run([root + '/bin/solve', data, tab, '0', '1', '/tmp/replan_keep.txt', rem, '0.5', '0.1', '0', '0.5', str(plat), str(tick)], capture_output=True, text=True).stderr
subprocess.run([root + '/bin/solve', data, tab, secs, '1', '/tmp/replan_out.txt', rem, '0.8', '0.1', str(max(2, int(secs) // 3)), '0.6', str(plat), str(tick)], capture_output=True, text=True)
c0 = int(open('/tmp/replan_keep.txt').readline().split()[1]); c1 = int(open('/tmp/replan_out.txt').readline().split()[1])
f = lambda c: '%d:%02d' % (c * 30 // 3600, c * 30 % 3600 // 60)
print('standing at %s, %s' % (st[plat // 2]['name'], now))
print('keep planned order : %s more to go' % f(c0))
print('best new order     : %s more to go  (saves %d min)' % (f(c1), (c0 - c1) / 2))
new = list(map(int, open('/tmp/replan_out.txt').read().split()[2:]))
print('next atoms:')
for a in new[:6]:
    print('   ', st[da[a]['stations'][0]]['name'], '->', st[da[a]['stations'][-1]]['name'], '(%d stops)' % (len(da[a]['stations']) - 1))
