#!/usr/bin/env python3
"""subwaydata.nyc days -> timetable files the simulator can replay (TT=file bin/sim ...).
usage: ingest_subwaydata.py data hist/ out/days/ 2026-11-02 [2026-11-03 ...]
For each start date D writes out/days/D.tt covering D and D+1 (an attempt crosses midnight);
times are seconds after local midnight of D."""
import sys, os, datetime
import numpy as np, pandas as pd
import hist
data, folder, out, dates = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
os.makedirs(out, exist_ok=True)
net, sidx = hist.stations(data)
cache = {}
def day(d):
    if d not in cache: cache[d] = hist.load_day(folder, d, sidx)
    return cache[d]
for d in dates:
    d2 = str(datetime.date.fromisoformat(d) + datetime.timedelta(days=1))
    try: h = pd.concat([day(d), day(d2)])
    except FileNotFoundError: print('skip', d); continue
    base = hist.midnight(d)
    codes = {t: i for i, t in enumerate(h.trip.unique())}
    rows = np.column_stack([h.dp, h.ap, h.dep - base, h.arr - base, h.trip.map(codes), np.zeros(len(h))]).astype(np.int32)
    rows = rows[(rows[:, 2] >= 0)]
    rows.tofile(f'{out}/{d}.tt')
    print(d, len(rows), 'train movements')
