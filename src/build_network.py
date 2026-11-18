#!/usr/bin/env python3
"""GTFS -> compact network files used by the C++ tools.

usage: build_network.py <gtfs_dir> <out_dir> [service_id=Weekday]

Outputs (out_dir):
  net.json        stations, platforms, atoms, groups, walks, transfers (human readable)
  conn.bin        int32[n,6]: dep_platform, arr_platform, dep_tick, arr_tick(abs, may exceed NT), trip, next_conn(-1)
  xfer.bin        int32[n,3]: from_station, to_station, ticks   (complex transfers, directed)
  walk.bin        int32[n,3]: from_station, to_station, ticks   (street runs, directed)
  atoms.bin       int32 flat: per directed atom: n, station sequence...
  meta.txt        key value pairs for the C++ side
"""
import sys, json, math, collections
import numpy as np, pandas as pd
import config as C

gtfs, out = sys.argv[1].rstrip('/') + '/', sys.argv[2].rstrip('/') + '/'
service = sys.argv[3] if len(sys.argv) > 3 else 'Weekday'

stops = pd.read_csv(gtfs + 'stops.txt', dtype=str)
trips = pd.read_csv(gtfs + 'trips.txt', dtype=str)
st = pd.read_csv(gtfs + 'stop_times.txt', dtype=str)
tr = pd.read_csv(gtfs + 'transfers.txt', dtype=str)

trips = trips[(trips.service_id == service) & (trips.route_id != 'SI')].reset_index(drop=True)
st = st[st.trip_id.isin(set(trips.trip_id))].copy()


def sec(col):
    p = col.str.split(':', expand=True).astype(int).values
    return p[:, 0] * 3600 + p[:, 1] * 60 + p[:, 2]


st['arr'] = sec(st.arrival_time)
st['dep'] = sec(st.departure_time)
st['seq'] = st.stop_sequence.astype(int)
st['par'] = st.stop_id.str[:-1].replace(C.STATION_ALIAS)
st['let'] = st.stop_id.str[-1]
st = st.merge(trips[['trip_id', 'route_id']], on='trip_id')
assert (st.arr % C.TICK == 0).all() and (st.dep % C.TICK == 0).all(), 'times not on tick grid'

# The M shares M11..M18 with the J/Z but labels directions the other way round.
# Flip the M's letter there so a letter means one physical platform.
flip = (st.route_id == 'M') & st.par.isin(['M11', 'M12', 'M13', 'M14', 'M16', 'M18'])
st.loc[flip, 'let'] = st.loc[flip, 'let'].map({'N': 'S', 'S': 'N'})

st = st.sort_values(['trip_id', 'seq']).reset_index(drop=True)

# ---------------- stations ------------------------------------------------------
used = sorted(st.par.unique())
par = stops[stops.stop_id.isin(used)].set_index('stop_id').loc[used]
S = len(used)
sidx = {s: i for i, s in enumerate(used)}
names = par.stop_name.tolist()
lat = par.stop_lat.astype(float).values
lon = par.stop_lon.astype(float).values
routes_at = st.groupby('par').route_id.agg(lambda x: sorted(set(x))).to_dict()


def landmass(i):
    sid, la, lo = used[i], lat[i], lon[i]
    if sid == 'B06':
        return 'ROOSEVELT'
    if sid == 'H04':
        return 'BROADCHANNEL'
    if la < 40.607 and lo > -73.86:
        return 'ROCKAWAY'
    if la >= 40.79:
        return 'MAIN'
    if la < 40.709:
        return 'MAIN' if (la > 40.70 and lo < -74.003) else 'LI'
    xs = [40.709, 40.716, 40.730, 40.742, 40.755, 40.765, 40.775, 40.785, 40.79]
    ys = [-73.9765, -73.970, -73.967, -73.965, -73.957, -73.950, -73.940, -73.930, -73.92]
    return 'MAIN' if lo < np.interp(la, xs, ys) else 'LI'


land = [landmass(i) for i in range(S)]

# ---------------- connections ------------------------------------------------------
tidx = {t: i for i, t in enumerate(trips.trip_id)}
st['s'] = st.par.map(sidx)
st['p'] = st.s * 2 + (st.let == 'S').astype(int)
st['t'] = st.trip_id.map(tidx)
nxt = st.shift(-1)
ok = (st.trip_id == nxt.trip_id)
conn = pd.DataFrame({
    'dp': st.p[ok].values, 'ap': nxt.p[ok].astype(int).values,
    'dt': st.dep[ok].values, 'at': nxt.arr[ok].astype(int).values,
    'trip': st.t[ok].values})
assert (conn['at'] > conn['dt']).all()
# wrap to a cyclic service day: dep in [0, DAY), arr = dep + run time
run = conn['at'] - conn['dt']
conn['dt'] = conn['dt'] % C.DAY
conn['at'] = conn['dt'] + run
conn['dt'] //= C.TICK
conn['at'] //= C.TICK
conn = conn.sort_values(['dt', 'trip']).reset_index(drop=True)
# next connection of the same trip (index), -1 at end
conn['next'] = -1
last = {}
order = np.argsort(-(st.seq[ok].values), kind='stable')  # not used; compute via groupby below
by_trip = collections.defaultdict(list)
raw_dep = (st.dep[ok].values)
tmp = pd.DataFrame({'trip': st.t[ok].values, 'dp': st.p[ok].values, 'rawdep': raw_dep})
tmp['key'] = list(zip(tmp.trip, tmp.dp, (tmp.rawdep % C.DAY) // C.TICK))
keypos = {k: i for i, k in enumerate(zip(conn.trip, conn.dp, conn.dt))}
tk = tmp['key'].tolist()
nx = np.full(len(conn), -1, dtype=np.int64)
for a, b in zip(tk[:-1], tk[1:]):
    if a[0] == b[0]:
        nx[keypos[a]] = keypos[b]
conn['next'] = nx
trip_route = trips.route_id.tolist()

# ---------------- base (physical) adjacency ------------------------------------------
pat = st.groupby('trip_id').s.agg(tuple)
patterns = collections.Counter(pat.values)
hops = collections.Counter()
for p, n in patterns.items():
    for a, b in zip(p[:-1], p[1:]):
        hops[(a, b)] += n
skip = set()
for p in patterns:
    pos = {s: i for i, s in enumerate(p)}
    for (a, b) in hops:
        if a in pos and b in pos and pos[b] - pos[a] > 1:
            skip.add((a, b))
base = {h for h in hops if h not in skip}
und = collections.defaultdict(set)
for a, b in base:
    und[a].add(b)
    und[b].add(a)
express_ends = set()
for a, b in skip:
    express_ends.add(a)
    express_ends.add(b)

# ---------------- transfers & walks ------------------------------------------------------
xfer = {}
for f, t, m in zip(tr.from_stop_id, tr.to_stop_id, tr.min_transfer_time):
    f, t = C.STATION_ALIAS.get(f, f), C.STATION_ALIAS.get(t, t)
    if f != t and f in sidx and t in sidx:
        secs = max(C.XFER_MIN, C.XFER_FACTOR * int(m))
        xfer[(sidx[f], sidx[t])] = int(-(-secs // C.TICK))


def crow(i, j):
    la1, lo1, la2, lo2 = map(math.radians, (lat[i], lon[i], lat[j], lon[j]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


walk = {}
crowd = {}
for i in range(S):
    for j in range(S):
        if i == j or land[i] != land[j] or (i, j) in xfer:
            continue
        d = crow(i, j)
        if d <= C.WALK_MAX_CROW_MI:
            walk[(i, j)] = C.walk_seconds(d) // C.TICK
            crowd[(i, j)] = d

# ---------------- portals (decision points) ------------------------------------------
railnb = collections.defaultdict(set)
for a in und:
    railnb[a] |= und[a]
for (a, b) in xfer:
    railnb[a].add(b)


def within_hops(a, k):
    seen, fr = {a}, {a}
    for _ in range(k):
        fr = {y for x in fr for y in railnb[x]} - seen
        seen |= fr
    return seen


portal = set()
why = collections.defaultdict(list)
for s in range(S):
    if len(und[s]) != 2:
        portal.add(s); why[s].append('junction/terminal')
    if s in express_ends:
        portal.add(s); why[s].append('express stop')
    if any(a == s for a, _ in xfer):
        portal.add(s); why[s].append('transfer complex')
for s in range(S):
    near = within_hops(s, C.WALK_PORTAL_MIN_HOPS)
    for j in range(S):
        if (s, j) in crowd and crowd[(s, j)] <= C.WALK_PORTAL_CROW_MI and j not in near:
            portal.add(s); why[s].append('walk to ' + names[j]); break

# ---------------- atoms: chains between portals ------------------------------------------
atoms = []          # undirected chains as station lists
seen_edge = set()
for p in sorted(portal):
    for n in sorted(und[p]):
        if (p, n) in seen_edge:
            continue
        chain = [p, n]
        seen_edge.add((p, n))
        while chain[-1] not in portal:
            a, b = chain[-2], chain[-1]
            nb = [x for x in und[b] if x != a]
            assert len(nb) == 1
            seen_edge.add((b, nb[0]))
            chain.append(nb[0])
        seen_edge.add((chain[-1], chain[-2]))
        atoms.append(chain)
covered = set(x for a in atoms for x in a)
assert covered == set(range(S)), 'stations outside any chain: %s' % [used[i] for i in set(range(S)) - covered]

# directed atoms; a directed atom is usable only if every hop exists as a base hop in that direction
datoms = []
for k, ch in enumerate(atoms):
    for d, seq in enumerate((ch, ch[::-1])):
        if all((a, b) in base for a, b in zip(seq[:-1], seq[1:])):
            datoms.append({'atom': k, 'dir': d, 'stations': seq})

# start/end platform of each directed atom = majority letter on first/last hop
hop_let = collections.defaultdict(collections.Counter)
for dp, ap in zip(conn.dp.values, conn.ap.values):
    hop_let[(dp // 2, ap // 2)][(dp % 2, ap % 2)] += 1
for da in datoms:
    seq = da['stations']
    plats = []
    for a, b in zip(seq[:-1], seq[1:]):
        (l1, l2), _ = hop_let[(a, b)].most_common(1)[0]
        plats.append((a * 2 + l1, b * 2 + l2))
    da['start_p'] = plats[0][0]
    da['end_p'] = plats[-1][1]

# groups: one must be chosen from each.  interior-bearing atom -> its directions.
interior_cov = set()
groups = []
for k, ch in enumerate(atoms):
    if len(ch) > 2:
        opts = [i for i, da in enumerate(datoms) if da['atom'] == k]
        groups.append({'kind': 'chain', 'label': names[ch[0]] + ' <> ' + names[ch[-1]], 'options': opts,
                       'covers': ch})
        interior_cov |= set(ch)
iso = [s for s in sorted(portal) if s not in interior_cov]
# isolated portals: must ride at least one hop touching them. pair up adjacent isolated portals greedily.
iso_set = set(iso)
done = set()
for s in iso:
    if s in done:
        continue
    mate = next((n for n in sorted(und[s]) if n in iso_set and n not in done and n != s), None)
    if mate is not None:
        opts = [i for i, da in enumerate(datoms) if set(da['stations']) == {s, mate} and len(da['stations']) == 2]
        if opts:
            groups.append({'kind': 'hop', 'label': names[s] + ' <> ' + names[mate], 'options': opts, 'covers': [s, mate]})
            done |= {s, mate}
            continue
    opts = [i for i, da in enumerate(datoms) if len(da['stations']) == 2 and s in da['stations']]
    assert opts, names[s]
    groups.append({'kind': 'point', 'label': names[s] + ' [' + used[s] + ']', 'options': opts, 'covers': [s]})
    done.add(s)
allcov = set(x for g in groups for x in g['covers'])
assert allcov == set(range(S))

# ---------------- write ------------------------------------------------------------
np.asarray(conn[['dp', 'ap', 'dt', 'at', 'trip', 'next']].values, dtype=np.int32).tofile(out + 'conn.bin')
np.asarray([(a, b, t) for (a, b), t in sorted(xfer.items())], dtype=np.int32).tofile(out + 'xfer.bin')
np.asarray([(a, b, t) for (a, b), t in sorted(walk.items())], dtype=np.int32).tofile(out + 'walk.bin')
flat = []
for da in datoms:
    flat += [len(da['stations']), da['start_p'], da['end_p']] + da['stations']
np.asarray(flat, dtype=np.int32).tofile(out + 'atoms.bin')
gflat = []
for g in groups:
    gflat += [len(g['options'])] + g['options']
np.asarray(gflat, dtype=np.int32).tofile(out + 'groups.bin')
with open(out + 'meta.txt', 'w') as f:
    f.write(f"S {S}\nNT {C.NT}\nTICK {C.TICK}\nNCONN {len(conn)}\nNXFER {len(xfer)}\nNWALK {len(walk)}\n"
            f"NDATOM {len(datoms)}\nNGROUP {len(groups)}\nNTRIP {len(trips)}\n"
            f"XSAME {C.XFER_SAME_STATION // C.TICK}\nXPLAT {C.XFER_SAME_PLATFORM // C.TICK}\n")
json.dump({
    'service': service,
    'stations': [{'id': used[i], 'name': names[i], 'lat': lat[i], 'lon': lon[i], 'land': land[i],
                  'routes': routes_at[used[i]], 'portal': i in portal, 'why': why.get(i, [])} for i in range(S)],
    'trips': [{'id': t, 'route': r} for t, r in zip(trips.trip_id, trip_route)],
    'atoms': atoms, 'datoms': datoms, 'groups': groups,
    'xfer': [[a, b, t] for (a, b), t in sorted(xfer.items())],
    'walk_crow_mi': {f'{a},{b}': round(d, 3) for (a, b), d in crowd.items()},
}, open(out + 'net.json', 'w'), default=lambda o: o.item())

print(f'stations {S}  portals {len(portal)}  atoms {len(atoms)} (directed {len(datoms)})  groups {len(groups)}')
print('  group kinds', collections.Counter(g['kind'] for g in groups))
print(f'connections {len(conn)}  trips {len(trips)}  complex transfers {len(xfer)}  walk edges {len(walk)}'
      f' (avg degree {len(walk) / S:.1f})')
print('land', collections.Counter(land))
print('degree hist', collections.Counter(len(und[s]) for s in range(S)))
sp = set(da['start_p'] for da in datoms); ep = set(da['end_p'] for da in datoms)
print('start platforms', len(sp), 'end platforms', len(ep))
longest = sorted(atoms, key=len, reverse=True)[:8]
for ch in longest:
    print('  ', len(ch), names[ch[0]], '->', names[ch[-1]])
