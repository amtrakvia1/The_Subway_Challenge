#!/usr/bin/env python3
"""Turn a solution file into a human itinerary + risk report.

usage: report.py <data_dir> <solution_file> <out_prefix> [slack_sec]
writes <out_prefix>.json (machine readable, used by the phone page) and <out_prefix>.md
"""
import sys, json, subprocess, os, collections
import config as C

data, sol, outp = sys.argv[1], sys.argv[2], sys.argv[3]
slack = sys.argv[4] if len(sys.argv) > 4 else '0'
here = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.join(here, '..', 'bin', 'sim')
n = json.load(open(data + '/net.json'))
st, trips = n['stations'], n['trips']
crow = n['walk_crow_mi']


def hm(t):
    d, t = divmod(int(t), 86400)
    return '%02d:%02d:%02d' % (t // 3600, t % 3600 // 60, t % 60) + ('' if d == 0 else ' (+%dd)' % d)


def dur(t):
    t = int(t)
    return '%d:%02d:%02d' % (t // 3600, t % 3600 // 60, t % 60)


raw = subprocess.run([SIM, data, sol, 'itin', slack], capture_output=True, text=True, check=True).stdout.splitlines()
hdr = raw[0].split()
t_start, t_end = int(hdr[1]), int(hdr[3])
legs = []
for line in raw[1:]:
    f = line.split('\t')
    k, a, b, t0, t1, trip, pos = map(int, f[:7])
    if k == 0:
        stops = [tuple(map(int, x.split('@'))) for x in f[7].split(',')]
        inst = int(f[8])
        if legs and legs[-1]['kind'] == 'ride' and legs[-1]['inst'] == inst and legs[-1]['stops'][-1][0] == stops[0][0]:
            legs[-1]['stops'] += stops[1:]
            legs[-1]['t1'] = t1
            legs[-1]['b'] = b
            continue
        legs.append({'kind': 'ride', 'a': a, 'b': b, 't0': t0, 't1': t1, 'inst': inst, 'route': trips[trip]['route'],
                     'trip_id': trips[trip]['id'], 'stops': stops})
    else:
        legs.append({'kind': ['', 'cross', 'transfer', 'run'][k], 'a': a, 'b': b, 't0': t0, 't1': t1})

miss = {}
for line in subprocess.run([SIM, data, sol, 'miss', slack], capture_output=True, text=True, check=True).stdout.splitlines():
    x, v = map(int, line.split())
    miss[x] = v

# ---- coverage ------------------------------------------------------------------
seen = {}
for i, L in enumerate(legs):
    if L['kind'] == 'ride':
        new = []
        for p, t in L['stops']:
            if p // 2 not in seen:
                seen[p // 2] = t
                new.append(p // 2)
        L['new'] = new
missing = [st[i]['name'] + ' [' + st[i]['id'] + ']' for i in range(len(st)) if i not in seen]

# ---- margins ------------------------------------------------------------------
prev_end = None
for i, L in enumerate(legs):
    if L['kind'] == 'ride':
        L['margin'] = None if prev_end is None else L['t0'] - prev_end
        L['miss_cost'] = miss.get(L['inst'])
    prev_end = L['t1']
    if L['kind'] == 'run':
        d = crow.get('%d,%d' % (L['a'] // 2, L['b'] // 2), 0)
        L['crow_mi'] = d
        L['street_mi'] = round(C.walk_street_miles(d), 2)

rides = [L for L in legs if L['kind'] == 'ride']
runs = [L for L in legs if L['kind'] == 'run']
total = t_end - t_start
summary = {
    'start': t_start, 'end': t_end, 'duration': total, 'duration_hms': dur(total),
    'beats_record_by': C.RECORD_SECONDS - total,
    'stations_visited': len(seen), 'stations_total': len(st), 'missing': missing,
    'rides': len(rides), 'runs': len(runs), 'run_miles_street': round(sum(r['street_mi'] for r in runs), 2),
    'slack_assumed': int(slack),
}


def nm(p):
    return st[p // 2]['name']


out_legs = []
for L in legs:
    o = {'kind': L['kind'], 'from': nm(L['a']), 'from_id': st[L['a'] // 2]['id'], 'to': nm(L['b']), 'to_id': st[L['b'] // 2]['id'],
         't0': L['t0'], 't1': L['t1']}
    if L['kind'] == 'ride':
        o.update(route=L['route'], dir='NS'[L['a'] % 2], trip_id=L['trip_id'], nstops=len(L['stops']) - 1, new=len(L['new']),
                 margin=L['margin'], miss_cost=L['miss_cost'],
                 stops=[[st[p // 2]['name'], t] for p, t in L['stops']])
    if L['kind'] == 'run':
        o.update(street_mi=L['street_mi'])
    out_legs.append(o)
json.dump({'summary': summary, 'legs': out_legs}, open(outp + '.json', 'w'))

# ---- markdown ------------------------------------------------------------------
w = []
w.append('# Route: %s  (%s vs record 22:14:10)\n' % (dur(total), ('%+d min' % round((total - C.RECORD_SECONDS) / 60))))
w.append('Start **%s** at **%s**, finish **%s** at **%s**. %d rides, %d runs (%.1f street miles). '
         'Stations stopped at: %d / %d.%s\n' % (
             hm(t_start), nm(legs[0]['a']), hm(t_end), nm(legs[-1]['b']), len(rides), len(runs),
             summary['run_miles_street'], len(seen), len(st), '' if not missing else ' **MISSING: ' + ', '.join(missing) + '**'))
w.append('Margin = spare time before the train you need leaves. Miss cost = minutes added to the finish if that train is missed.\n')
w.append('| # | Do | From | At | To | At | Stops (new) | Margin | Miss cost |')
w.append('|---|---|---|---|---|---|---|---|---|')
for i, L in enumerate(legs, 1):
    if L['kind'] == 'ride':
        mg = '' if L['margin'] is None else '%d:%02d' % divmod(L['margin'], 60)
        mc = '' if L['miss_cost'] is None else ('stuck' if L['miss_cost'] < 0 else '+%d' % round(L['miss_cost'] / 60))
        w.append('| %d | **%s** %s | %s | %s | %s | %s | %d (%d) | %s | %s |' % (
            i, L['route'], 'NS'[L['a'] % 2] + 'B', nm(L['a']), hm(L['t0']), nm(L['b']), hm(L['t1']), len(L['stops']) - 1, len(L['new']), mg, mc))
    elif L['kind'] == 'run':
        w.append('| %d | RUN %.2f mi | %s | %s | %s | %s | | | |' % (i, L['street_mi'], nm(L['a']), hm(L['t0']), nm(L['b']), hm(L['t1'])))
    else:
        w.append('| %d | %s | %s | %s | %s | %s | | | |' % (i, 'change platform' if L['kind'] == 'cross' else 'transfer', nm(L['a']), hm(L['t0']), nm(L['b']), hm(L['t1'])))
open(outp + '.md', 'w').write('\n'.join(w) + '\n')
tight = sorted([L for L in rides if L['margin'] is not None and L['miss_cost'] not in (None, 0)], key=lambda L: -(L['miss_cost'] if L['miss_cost'] > 0 else 10 ** 6))
print(json.dumps(summary, indent=1))
print('worst trains to miss:')
for L in tight[:12]:
    print('  %s %s at %s  margin %ds  miss cost %s min' % (L['route'], nm(L['a']), hm(L['t0']), L['margin'], 'STUCK' if L['miss_cost'] < 0 else round(L['miss_cost'] / 60)))
