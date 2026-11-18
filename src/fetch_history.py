#!/usr/bin/env python3
"""Download subwaydata.nyc daily CSV archives for a date range and unpack them.
usage: fetch_history.py 2026-10-19 2026-11-13 hist/"""
import sys, json, os, subprocess, tarfile, io
get = lambda u: subprocess.run(['curl', '-sSf', '-m', '120', u], capture_output=True, check=True).stdout   # the server rejects urllib's user agent
a, b, out = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out, exist_ok=True)
meta = json.loads(get('https://data.subwaydata.nyc/subwaydatanyc_metadata.json'))['ProcessedDays']
got = 0
for d in sorted(meta, key=lambda x: x['Day']):
    if not (a <= d['Day'] <= b):
        continue
    if os.path.exists(f"{out}/subwaydatanyc_{d['Day']}_stop_times.csv"):
        got += 1; continue
    raw = get('https://data.subwaydata.nyc/' + d['Csv']['Path'])
    tarfile.open(fileobj=io.BytesIO(raw), mode='r:xz').extractall(out, filter='data')
    got += 1
print(got, 'days in', out, '; latest available', max(x['Day'] for x in meta))
