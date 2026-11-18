"""All tunable modelling assumptions live here. Change, then re-run `make all`."""

TICK = 30                      # seconds; GTFS subway times are all multiples of 30 s
DAY = 86400
NT = DAY // TICK               # ticks per day (2880)

# ---- in-system transfers ---------------------------------------------------
import os
XFER_FACTOR = float(os.environ.get('XFER_FACTOR', 0.5))              # multiply GTFS min_transfer_time (user: "halve, if not more")
XFER_MIN = int(os.environ.get('XFER_MIN', 60))                  # floor for a transfer between two station complexes' platforms
XFER_SAME_STATION = int(os.environ.get('XFER_SAME_STATION', 60))         # other-direction platform of the same station (terminal turnbacks etc.)
XFER_SAME_PLATFORM = 0         # change trains on the same directional platform (cross-platform local<->express)

# ---- out-of-system (running) transfers --------------------------------------
STREET_FACTOR = 1.25           # crow-fly -> street distance (Manhattan-grid average)
PACE = [(1.0, 600), (1.0, 720), (1e9, 900)]   # (miles in tier, sec/mile): 10:00, 12:00, then 15:00
WALK_OVERHEAD = 45             # stairs + turnstile out + turnstile in + stairs
WALK_MAX_CROW_MI = 1.6         # ignore runs longer than this crow-fly (~2 street miles)

# GTFS gives each level of these stations its own id; the MTA (and Guinness) count each as ONE station.
STATION_ALIAS = {'D13': 'A12', 'D20': 'A32', 'R09': '718'}   # 145 St, W 4 St, Queensboro Plaza

# ---- network compression -----------------------------------------------------
import os
WALK_PORTAL_CROW_MI = float(os.environ.get('WALK_PORTAL_CROW_MI', 0.30))     # a station becomes a decision point if another line is this close
WALK_PORTAL_MIN_HOPS = 4       # ...and that station is at least this many stops away by rail

# ---- robustness ----------------------------------------------------------------
# slack added to EVERY change of trains when building "robust" tables (seconds)
SLACK_LEVELS = [0, 60, 120, 180]

RECORD_SECONDS = 22 * 3600 + 14 * 60 + 10   # Kate Jones, 17-18 Apr 2023


def walk_seconds(crow_miles: float) -> int:
    d = crow_miles * STREET_FACTOR
    t = 0.0
    for tier, pace in PACE:
        x = min(d, tier)
        t += x * pace
        d -= x
        if d <= 0:
            break
    t += WALK_OVERHEAD
    return int(-(-t // TICK) * TICK)       # round up to a tick


def walk_street_miles(crow_miles: float) -> float:
    return crow_miles * STREET_FACTOR
