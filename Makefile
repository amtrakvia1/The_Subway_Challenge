# NYC subway all-stations record planner.  `make all GTFS=/path/to/unzipped/gtfs_subway`
GTFS ?= gtfs
CXX = g++ -O3 -march=native
SECS ?= 330

bin/%: src/%.cpp src/common.h
	@mkdir -p bin
	$(CXX) -fopenmp -o $@ $<

build: bin/tables bin/tables_risk bin/solve bin/sim bin/smooth

network: build
	@mkdir -p data tab out/runs
	python3 src/build_network.py $(GTFS) data

tables: network
	./bin/tables data 0 tab/s0          # optimistic: every scheduled connection is made
	./bin/tables data 4 tab/k4          # safe: every change of trains needs 2 spare minutes (4 ticks)

# two-stage search; results differ by seed, so run several and keep the best (pick_best.py).
# append `-1 0 0 480` to force a start between 00:00 and 04:00 (ticks 0-480)
solve:
	ACCEPT=rrt ./bin/solve data tab/s0 $(SECS) 1 out/runs/fast1.txt static 40 1 60 30 & ACCEPT=rrt ./bin/solve data tab/s0 $(SECS) 2 out/runs/fast2.txt static 40 1 60 30 & wait
	ACCEPT=rrt ./bin/solve data tab/k4 $(SECS) 3 out/runs/safe1.txt static 40 1 60 30 & ACCEPT=rrt ./bin/solve data tab/k4 $(SECS) 4 out/runs/safe2.txt static 40 1 60 30 & wait
	python3 src/pick_best.py

report:
	python3 src/report.py data out/best_safe.txt out/route_safe
	python3 src/planb.py data out/best_safe.txt out/route_safe.json 8 8 tab/k4
	python3 src/make_page.py out/route_safe.json out/run_sheet.html
	python3 src/report.py data out/best_fast.txt out/route_fast
	python3 src/mc.py data out/best_safe.txt 300
	python3 src/mc.py data out/best_fast.txt 300

test:
	python3 tests/test_consistency.py out/best_fast.txt
test-risk:
	./bin/tables_risk data 0 tab/r0 && cmp tab/r0_D.bin tab/s0_D.bin && cmp tab/r0_A.bin tab/s0_A.bin && echo identical; rm -f tab/r0_*

all: tables solve report test
