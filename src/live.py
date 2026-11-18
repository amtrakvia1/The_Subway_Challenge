#!/usr/bin/env python3
"""LIVE RE-ROUTER (skeleton).  NOT yet run against the real MTA feed: the build sandbox had no access to it.

What it does each cycle:
  1. pull the 8 MTA GTFS-realtime feeds (no API key needed)
  2. build a concrete timetable: live predictions for trains in the feed + the schedule for later trains
  3. ask the simulator to re-plan from where you are: `sim ... replan` keeps the remaining atoms but tries
     reordering / flipping the next WINDOW of them, each candidate being simulated all the way to the finish
     (so it looks "five steps ahead" with live times and uses the schedule beyond the feed horizon)
  4. print the next legs and how much the best reordering saves

usage (laptop or small cloud VM; a helper can read results to the runner, or wrap this in a tiny web server):
  pip install gtfs-realtime-bindings requests
  python3 src/live.py data out/best_safe.txt --pos 37 --station A32 --dir N
     --pos      index of the next atom to start (0-based; the run sheet step -> atom mapping is in route_*.json)
     --station  GTFS parent id of the platform you are standing on, --dir N|S

Known gaps (see docs/HANDOFF.md): feed trip ids must be matched to scheduled trips to avoid duplicates (a simple
start-time cutoff is used here); trains with no predictions beyond a few stops are extended with scheduled run times.
"""
import sys, os, json, time, argparse, subprocess, datetime, zoneinfo
import numpy as np

FEEDS = ['nyct%2Fgtfs', 'nyct%2Fgtfs-ace', 'nyct%2Fgtfs-bdfm', 'nyct%2Fgtfs-g', 'nyct%2Fgtfs-jz', 'nyct%2Fgtfs-nqrw', 'nyct%2Fgtfs-l']
BASE = 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/'
MFLIP = {'M11', 'M12', 'M13', 'M14', 'M16', 'M18'}
CUTOFF = 20 * 60        # scheduled trains starting within this many seconds are assumed to be in the feed already


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('data'); ap.add_argument('solution')
    ap.add_argument('--pos', type=int, required=True); ap.add_argument('--station', required=True); ap.add_argument('--dir', default='N')
    ap.add_argument('--window', type=int, default=8); ap.add_argument('--iters', type=int, default=300)
    a = ap.parse_args()
    import requests
    from google.transit import gtfs_realtime_pb2
    net = json.load(open(a.data + '/net.json'))
    sidx = {s['id']: i for i, s in enumerate(net['stations'])}
    tz = zoneinfo.ZoneInfo('America/New_York')
    now = datetime.datetime.now(tz)
    midnight = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    now_sec = int(now.timestamp()) - midnight

    rows, tripno = [], 0
    for f in FEEDS:
        msg = gtfs_realtime_pb2.FeedMessage()
        msg.ParseFromString(requests.get(BASE + f, timeout=10).content)
        for ent in msg.entity:
            if not ent.HasField('trip_update'):
                continue
            tu = ent.trip_update
            route, prev = tu.trip.route_id, None
            for u in tu.stop_time_update:
                par, let = u.stop_id[:-1], u.stop_id[-1]
                if par not in sidx:
                    prev = None
                    continue
                if route == 'M' and par in MFLIP:
                    let = 'S' if let == 'N' else 'N'
                p = sidx[par] * 2 + (let == 'S')
                arr = u.arrival.time or u.departure.time
                dep = u.departure.time or u.arrival.time
                if prev and arr > prev[1]:
                    rows.append((prev[0], p, prev[1] - midnight, arr - midnight, tripno, 0))
                prev = (p, dep)
            tripno += 1
    # schedule for everything that starts later than the feed can be trusted to cover
    conn = np.fromfile(a.data + '/conn.bin', dtype=np.int32).reshape(-1, 6)
    first = np.ones(len(conn), bool); first[conn[conn[:, 5] >= 0, 5]] = False
    DAY = 86400
    for start in np.nonzero(first)[0]:
        for day in (0, 1):
            c, off = start, day * DAY
            t0 = conn[c, 2] * 30 + off
            if t0 < now_sec + CUTOFF or t0 > now_sec + 26 * 3600:
                continue
            last = t0
            while c >= 0:
                dep = conn[c, 2] * 30 + off
                if dep < last - 3600:           # wrapped past midnight
                    off += DAY; dep += DAY
                rows.append((conn[c, 0], conn[c, 1], dep, dep + (conn[c, 3] - conn[c, 2]) * 30, tripno, 0))
                last = dep; c = conn[c, 5]
            tripno += 1
    tt = '/tmp/live.tt'
    np.asarray(rows, dtype=np.int32).tofile(tt)
    plat = sidx[a.station] * 2 + (a.dir == 'S')
    sim = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bin', 'sim')
    out = subprocess.run([sim, a.data, a.solution, 'replan', str(a.pos), str(plat), str(now_sec), str(a.window), str(a.iters)],
                         env={**os.environ, 'TT': tt}, capture_output=True, text=True).stdout
    st = net['stations']
    for line in out.splitlines():
        f = line.split('\t')
        if f[0] == 'leg':
            k, x, y, t0, t1 = map(int, f[1:])
            hm = lambda t: '%02d:%02d:%02d' % (t % DAY // 3600, t % 3600 // 60, t % 60)
            print(['RIDE', 'CROSS', 'TRANSFER', 'RUN'][k].ljust(9), st[x // 2]['name'], '->', st[y // 2]['name'], hm(t0), hm(t1))
        else:
            print(line)


if __name__ == '__main__':
    main()
