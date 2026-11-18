#!/usr/bin/env bash
# One command: build everything from the bundled timetable, then search for HOURS.
#   ./run_search.sh 8          # 8 hours, one solver per CPU core
#   ./run_search.sh 8 4 1800   # 8 hours, 4 jobs, 30 min per job
# Results: out/search/leaderboard.csv (sorted by median finish under real-data delays), routes in out/search/top/
set -euo pipefail
cd "$(dirname "$0")"
HOURS=${1:-8}; JOBS=${2:-$(nproc)}; SECS=${3:-1800}

mkdir -p bin data tab out
for t in tables solve sim; do
  if [ ! -x bin/$t ] || [ src/$t.cpp -nt bin/$t ] || [ src/common.h -nt bin/$t ]; then
    g++ -O3 -march=native -fopenmp -o bin/$t src/$t.cpp
  fi
done
if [ ! -f data/net.json ]; then
  mkdir -p gtfs && unzip -oq gtfs_subway.zip -d gtfs
  python3 src/build_network.py gtfs data
fi
[ -f tab/s0_D.bin ] || ./bin/tables data 0 tab/s0
[ -f tab/k4_D.bin ] || ./bin/tables data 4 tab/k4
python3 src/search_driver.py --hours "$HOURS" --jobs "$JOBS" --secs "$SECS"
