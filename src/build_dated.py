#!/usr/bin/env python3
"""Network for one calendar date from the MTA "supplemented" GTFS (planned work included), with the SAME structure
(stations, atoms, groups, transfers, runs) as an existing network, so route files stay valid and comparable.

usage: build_dated.py <supplemented_gtfs_dir> <base_data_dir> <out_dir> <YYYYMMDD>

Only the trains change, plus any segment direction that the base network lacks but this date's trains run (appended,
so existing directed-atom ids are unchanged). Services active on the date come from calendar.txt + calendar_dates.txt.
Clock window: the model is a cyclic 24 h day, so the date's network holds the trips of service day D (trips of the
previous service day that START after midnight are added too). A trip is kept whole and wrapped mod 24 h, exactly
like build_network.py does for the weekday timetable. Consequence: a route that starts in the early hours of D and
runs ~24 h meets D's early-morning trains again at its end, not D+1's (overnight work on the following night is not
seen). Connection building below mirrors build_network.py (keep the two in step).
"""
import sys, os, json, shutil, datetime as dt
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

gtfs, base, out, date = sys.argv[1].rstrip('/') + '/', sys.argv[2].rstrip('/') + '/', sys.argv[3].rstrip('/') + '/', sys.argv[4]
os.makedirs(out, exist_ok=True)
DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']


def active(d):
    cal = pd.read_csv(gtfs + 'calendar.txt', dtype=str)
    cd = pd.read_csv(gtfs + 'calendar_dates.txt', dtype=str) if os.path.exists(gtfs + 'calendar_dates.txt') else pd.DataFrame(columns=['service_id', 'date', 'exception_type'])
    wd = DAYS[dt.datetime.strptime(d, '%Y%m%d').weekday()]
    s = {r.service_id for r in cal.itertuples() if r.start_date <= d <= r.end_date and getattr(r, wd) == '1'}
    x = cd[cd.date == d]
    return (s | set(x[x.exception_type == '1'].service_id)) - set(x[x.exception_type == '2'].service_id)


prev = (dt.datetime.strptime(date, '%Y%m%d') - dt.timedelta(days=1)).strftime('%Y%m%d')
sv, sv_prev = active(date), active(prev)
net = json.load(open(base + 'net.json'))
used = [s['id'] for s in net['stations']]
sidx = {s: i for i, s in enumerate(used)}

trips = pd.read_csv(gtfs + 'trips.txt', dtype=str)
trips = trips[(trips.route_id != 'SI') & (trips.service_id.isin(sv | sv_prev))].reset_index(drop=True)
st = pd.read_csv(gtfs + 'stop_times.txt', dtype=str)
st = st[st.trip_id.isin(set(trips.trip_id))].copy()


def sec(col):
    p = col.str.split(':', expand=True).astype(int).values
    return p[:, 0] * 3600 + p[:, 1] * 60 + p[:, 2]


st['arr'] = sec(st.arrival_time)
st['dep'] = sec(st.departure_time)
first = st.groupby('trip_id').dep.min()
svc = trips.set_index('trip_id').service_id
keep = {t for t, f in first.items() if (svc[t] in sv and f < C.DAY) or (svc[t] in sv_prev and f >= C.DAY)}
trips = trips[trips.trip_id.isin(keep)].reset_index(drop=True)
st = st[st.trip_id.isin(keep)].copy()
shift = {t: (-C.DAY if first[t] >= C.DAY else 0) for t in keep}      # previous day's after-midnight trips
st['arr'] += st.trip_id.map(shift); st['dep'] += st.trip_id.map(shift)
st['seq'] = st.stop_sequence.astype(int)
st['par'] = st.stop_id.str[:-1].replace(C.STATION_ALIAS)
st['let'] = st.stop_id.str[-1]
st = st.merge(trips[['trip_id', 'route_id']], on='trip_id')
assert (st.arr % C.TICK == 0).all() and (st.dep % C.TICK == 0).all(), 'times not on tick grid'
flip = (st.route_id == 'M') & st.par.isin(['M11', 'M12', 'M13', 'M14', 'M16', 'M18'])
st.loc[flip, 'let'] = st.loc[flip, 'let'].map({'N': 'S', 'S': 'N'})
unknown = sorted(set(st.par) - set(sidx))
st = st[st.par.isin(sidx)]                     # a stop the base network does not have cannot be used
st = st.sort_values(['trip_id', 'seq']).reset_index(drop=True)

tidx = {t: i for i, t in enumerate(trips.trip_id)}
st['s'] = st.par.map(sidx)
st['p'] = st.s * 2 + (st.let == 'S').astype(int)
st['t'] = st.trip_id.map(tidx)
nxt = st.shift(-1)
ok = (st.trip_id == nxt.trip_id)
conn = pd.DataFrame({'dp': st.p[ok].values, 'ap': nxt.p[ok].astype(int).values,
                     'dt': st.dep[ok].values, 'at': nxt.arr[ok].astype(int).values, 'trip': st.t[ok].values})
assert (conn['at'] > conn['dt']).all()
run = conn['at'] - conn['dt']
conn['dt'] = conn['dt'] % C.DAY
conn['at'] = conn['dt'] + run
conn['dt'] //= C.TICK
conn['at'] //= C.TICK
conn = conn.sort_values(['dt', 'trip']).reset_index(drop=True)
tmp = pd.DataFrame({'trip': st.t[ok].values, 'dp': st.p[ok].values, 'rawdep': st.dep[ok].values})
tk = list(zip(tmp.trip, tmp.dp, (tmp.rawdep % C.DAY) // C.TICK))
keypos = {k: i for i, k in enumerate(zip(conn.trip, conn.dp, conn.dt))}
nx = np.full(len(conn), -1, dtype=np.int64)
for a, b in zip(tk[:-1], tk[1:]):
    if a[0] == b[0]:
        nx[keypos[a]] = keypos[b]
conn['next'] = nx

# Directions that the base network lacks but this date's trains run (e.g. the 7's 52 St / 69 St skip runs the other
# way during some planned work): append them as new directed atoms (existing ids unchanged, so route files stay
# valid) and add them to every group that offers the other direction of the same atom.
import collections
hop_let = collections.defaultdict(collections.Counter)
for dp, ap in zip(conn.dp.values, conn.ap.values):
    hop_let[(dp // 2, ap // 2)][(dp % 2, ap % 2)] += 1
have = {(d['atom'], d['dir']) for d in net['datoms']}
added = []
for k, ch in enumerate(net['atoms']):
    for d, seq in enumerate((ch, ch[::-1])):
        if (k, d) in have or not all((x, y) in hop_let for x, y in zip(seq[:-1], seq[1:])):
            continue
        pl = [hop_let[(x, y)].most_common(1)[0][0] for x, y in zip(seq[:-1], seq[1:])]
        nid = len(net['datoms'])
        net['datoms'].append({'atom': k, 'dir': d, 'stations': seq, 'start_p': seq[0] * 2 + pl[0][0], 'end_p': seq[-1] * 2 + pl[-1][1]})
        for g in net['groups']:
            if any(net['datoms'][o]['atom'] == k for o in g['options']): g['options'].append(nid)
        added.append(' > '.join(net['stations'][x]['name'] for x in (seq[0], seq[-1])))

np.asarray(conn[['dp', 'ap', 'dt', 'at', 'trip', 'next']].values, dtype=np.int32).tofile(out + 'conn.bin')
for f in ('xfer.bin', 'walk.bin'):
    shutil.copy(base + f, out + f)
flat = []
for d in net['datoms']:
    flat += [len(d['stations']), d['start_p'], d['end_p']] + d['stations']
np.asarray(flat, dtype=np.int32).tofile(out + 'atoms.bin')
gflat = []
for g in net['groups']:
    gflat += [len(g['options'])] + g['options']
np.asarray(gflat, dtype=np.int32).tofile(out + 'groups.bin')
for f in ('atoms.bin', 'groups.bin'):          # unchanged structure must give byte-identical files
    if not added: assert open(out + f, 'rb').read() == open(base + f, 'rb').read(), f
meta = dict(l.split() for l in open(base + 'meta.txt') if l.strip())
meta['NCONN'], meta['NTRIP'], meta['NDATOM'] = str(len(conn)), str(len(trips)), str(len(net['datoms']))
open(out + 'meta.txt', 'w').write(''.join('%s %s\n' % kv for kv in meta.items()))
net['service'] = 'date %s: %s (+ after-midnight starts of %s)' % (date, ' '.join(sorted(sv)), prev)
net['trips'] = [{'id': t, 'route': r} for t, r in zip(trips.trip_id, trips.route_id)]
json.dump(net, open(out + 'net.json', 'w'), default=lambda o: o.item())
print('date %s (%s): services %s | trips %d, connections %d%s' % (
    date, DAYS[dt.datetime.strptime(date, '%Y%m%d').weekday()][:3], ' '.join(sorted(sv)), len(trips), len(conn),
    (' | stops not in base network (dropped): ' + ' '.join(unknown)) if unknown else '')
    + (' | directions added: ' + '; '.join(added) if added else ''))
