#!/usr/bin/env python3
"""What planned work does a date have? Compares a dated network (build_dated.py on the supplemented GTFS) with the
normal timetable of the same day type (build_dated.py on the regular GTFS for the same date).

usage: date_work.py <regular_gtfs_dir> <dates_dir> <YYYYMMDD> [...]
Prints per date: stations with no train at all, and for each line the hours where it runs under half its normal
stop-to-stop service (a sign of a suspension or a reroute on part of the line).
"""
import sys, os, json, subprocess, collections, tempfile
import numpy as np

reg, ddir, dates = sys.argv[1], sys.argv[2], sys.argv[3:]
here = os.path.dirname(os.path.abspath(__file__))


def load(d):
    n = json.load(open(d + '/net.json'))
    c = np.fromfile(d + '/conn.bin', dtype=np.int32).reshape(-1, 6)
    route = np.array([t['route'] for t in n['trips']])[c[:, 4]]
    hour = (c[:, 2] * 30 // 3600) % 24
    cnt = collections.Counter(zip(route, hour))
    st = np.zeros(len(n['stations']), dtype=int)
    np.add.at(st, c[:, 0] // 2, 1); np.add.at(st, c[:, 1] // 2, 1)
    return n, cnt, st


def hours(hs):
    hs = sorted(hs); out = []; a = b = hs[0]
    for x in hs[1:]:
        if x == b + 1: b = x
        else: out.append((a, b)); a = b = x
    out.append((a, b))
    return ', '.join('%02d-%02d' % (a, b + 1) for a, b in out)


with tempfile.TemporaryDirectory() as tmp:
    for D in dates:
        base = tmp + '/' + D
        subprocess.run(['python3', here + '/build_dated.py', reg, ddir + '/' + D, base, D], check=True, capture_output=True)
        n, cd, sd = load(ddir + '/' + D)
        _, cr, sr = load(base)
        print('== %s (%s)' % (D, n['service']))
        dead = [n['stations'][i]['name'] for i in range(len(sd)) if sd[i] == 0 and sr[i] > 0]
        if dead: print('   no trains at all: ' + ', '.join(dead))
        for r in sorted({r for r, _ in cr}):
            low = [hh for hh in range(24) if cr.get((r, hh), 0) >= 20 and cd.get((r, hh), 0) < 0.5 * cr[(r, hh)]]
            if low: print('   %-3s under half of normal service %s' % (r, hours(low)))
