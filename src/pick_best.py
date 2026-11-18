#!/usr/bin/env python3
"""Copy the best fast*/safe* run in out/runs to out/best_fast.txt / out/best_safe.txt (lowest cost in line 1)."""
import glob, shutil
for kind in ('fast', 'safe'):
    best = min(glob.glob(f'out/runs/{kind}*.txt'), key=lambda f: int(open(f).readline().split()[1]), default=None)
    if best:
        shutil.copy(best, f'out/best_{kind}.txt')
        print(kind, best, int(open(best).readline().split()[1]) * 30 / 3600, 'h')
