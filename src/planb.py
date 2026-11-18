#!/usr/bin/env python3
"""Pre-compute a Plan B for every train that is expensive to miss.

For each such train: assume you reach the platform just after it leaves, re-optimize the order of everything
that is left (same engine as replan.py), and store the resulting itinerary next to the main route so the phone
page can switch to it with one tap, with no server.

usage: planb.py data solution.txt out/route.json [min_miss_cost_min=8] [seconds_each=8] [tables=tab/r1]
adds "planb": [{step, keep_loss, loss, legs:[...]}] to the route JSON.
"""
import sys, os, json, subprocess
from concurrent.futures import ThreadPoolExecutor
data, sol, rj = sys.argv[1:4]
thr = float(sys.argv[4]) if len(sys.argv) > 4 else 8
secs = sys.argv[5] if len(sys.argv) > 5 else '8'
tab = sys.argv[6] if len(sys.argv) > 6 else 'tab/r1'
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SIM, SOLVE = root + '/bin/sim', root + '/bin/solve'
n = json.load(open(data + '/net.json')); st, trips, da = n['stations'], n['trips'], n['datoms']
src_ok = set(d['end_p'] for d in da)
route = json.load(open(rj))
L = open(sol).read().split(); seq = list(map(int, L[2:]))


def parse(lines):
    legs = []
    for line in lines:
        if line.startswith('#'):
            continue
        f = line.split('\t'); k, a, b, t0, t1, trip, pos = map(int, f[:7])
        if k == 0:
            stops = [tuple(map(int, x.split('@'))) for x in f[7].split(',')]; inst = int(f[8])
            if legs and legs[-1]['kind'] == 'ride' and legs[-1]['inst'] == inst and legs[-1]['last'] == stops[0][0]:
                legs[-1].update(t1=t1, to=st[b // 2]['name'], last=stops[-1][0]); legs[-1]['nstops'] += len(stops) - 1
                legs[-1]['stops'] += [[st[p // 2]['name'], t] for p, t in stops[1:]]
                continue
            legs.append({'kind': 'ride', 'from': st[a // 2]['name'], 'to': st[b // 2]['name'], 't0': t0, 't1': t1, 'inst': inst, 'pos': pos, 'a': a,
                         'route': trips[trip]['route'], 'dir': 'NS'[a % 2], 'nstops': len(stops) - 1, 'last': stops[-1][0],
                         'stops': [[st[p // 2]['name'], t] for p, t in stops]})
        else:
            legs.append({'kind': ['', 'cross', 'transfer', 'run'][k], 'from': st[a // 2]['name'], 'to': st[b // 2]['name'], 't0': t0, 't1': t1, 'pos': pos, 'a': a})
            if k == 3:
                legs[-1]['street_mi'] = round(1.25 * n['walk_crow_mi'].get('%d,%d' % (a // 2, b // 2), 0), 2)
    return legs


main = parse(subprocess.run([SIM, data, sol, 'itin', '0'], capture_output=True, text=True).stdout.splitlines())
assert len(main) == len(route['legs']), (len(main), len(route['legs']))
end_main = main[-1]['t1']
# atom index each leg works towards: legs carry pos=-1 while deadheading, so look ahead to the next atom leg
nxt = None
for Lg in reversed(main):
    if Lg['pos'] >= 0:
        nxt = Lg['pos']
    Lg['atom'] = nxt
jobs = []
for i, (Lg, R) in enumerate(zip(main, route['legs'])):
    mc = R.get('miss_cost')
    if Lg['kind'] != 'ride' or mc is None or (0 <= mc < thr * 60) or i == 0:
        continue
    if Lg['a'] not in src_ok or Lg['atom'] is None:
        continue
    jobs.append((i, Lg))


def work(job):
    i, Lg = job
    pos, plat, t = Lg['atom'], Lg['a'], Lg['t0'] + 30
    tick = (t + 29) // 30
    fin, fout = '/tmp/pb_in_%d.txt' % i, '/tmp/pb_out_%d.txt' % i
    open(fin, 'w').write('%d 0\n' % tick + '\n'.join(map(str, seq[pos:])) + '\n')
    subprocess.run([SOLVE, data, tab, secs, str(i), fout, fin, '1.5', '0.1', str(max(2, int(secs) // 2)), '1.0', str(plat), str(tick)], capture_output=True, text=True)
    new = list(map(int, open(fout).read().split()[2:]))
    full = '/tmp/pb_full_%d.txt' % i
    open(full, 'w').write('0 0\n' + '\n'.join(map(str, seq[:pos] + new)) + '\n')
    legs = parse(subprocess.run([SIM, data, full, 'itin', '0', str(pos), str(plat), str(tick * 30)], capture_output=True, text=True).stdout.splitlines())
    if not legs:
        return None
    for g in legs:
        for k in ('inst', 'pos', 'a', 'last', 'atom'):
            g.pop(k, None)
    return {'step': i, 'keep_loss': route['legs'][i]['miss_cost'], 'loss': legs[-1]['t1'] - end_main, 'legs': legs}


with ThreadPoolExecutor(2) as ex:
    res = [r for r in ex.map(work, jobs) if r]
# only keep plans that actually beat "keep the same order"
res = [r for r in res if r['keep_loss'] < 0 or r['loss'] < r['keep_loss'] - 60]
route['planb'] = res
json.dump(route, open(rj, 'w'))
print('%d risky trains, %d with a better Plan B' % (len(jobs), len(res)))
for r in res:
    print('  step %3d  keep order: %s   plan B: +%d min' % (r['step'] + 1, 'stuck' if r['keep_loss'] < 0 else '+%d min' % (r['keep_loss'] / 60), r['loss'] / 60))
