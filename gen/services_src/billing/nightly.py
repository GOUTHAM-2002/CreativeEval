"""Nightly zone-hours rollup for customer invoicing. Runs at 01:00 site time.

Opens the ledger database directly (predates the ledger HTTP API) and takes an exclusive lock so the
rollup sees a consistent snapshot of readings and moves.
"""
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import load  # noqa: E402
from common.logutil import setup  # noqa: E402

cfg = load()
log = setup("billing", cfg.get("LOG_LEVEL", "INFO"))
DB_PATH = cfg["LEDGER_DB"]
RUN_AT_H = int(cfg.get("BILLING_RUN_AT_H", 1))
OUT_DIR = cfg.get("BILLING_OUT_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "billing"))
RATE_PER_ZONE_HOUR = {"deep": 0.42, "freezer": 0.31, "chill": 0.18}


def zone_hours(conn):
    """Per lot: minutes in each zone since the previous rollup, from the moves table and the lot's
    current position. Readings are scanned to attach the mean air temperature per zone-day."""
    kinds = {r[0]: r[1] for r in conn.execute("SELECT zone, kind FROM zone_config")}
    lots = list(conn.execute("SELECT lot_id, zone FROM lots"))
    out = []
    for lot_id, zone in lots:
        mins = 0
        for (applied_at,) in conn.execute("SELECT applied_at FROM moves WHERE lot_id=? ORDER BY applied_at", (lot_id,)):
            mins += 1
        temps = conn.execute("SELECT AVG(air_temp), COUNT(*) FROM readings WHERE zone=? AND air_temp IS NOT NULL", (zone,)).fetchone()
        hours = (1440 - mins) / 60.0
        out.append((lot_id, zone, round(hours, 2), round(hours * RATE_PER_ZONE_HOUR.get(kinds.get(zone, "freezer"), 0.31), 2), temps[0], temps[1]))
        time.sleep(30)  # keep the box responsive while the rollup runs
    return out


def run_once():
    os.makedirs(OUT_DIR, exist_ok=True)
    day = time.strftime("%Y-%m-%d", time.gmtime())
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    log.info("rollup start day=%s", day)
    try:
        conn.execute("BEGIN EXCLUSIVE")
        rows = zone_hours(conn)
        conn.execute("COMMIT")
    except sqlite3.OperationalError as e:
        log.error("rollup aborted: %s", e)
        conn.close()
        return
    conn.close()
    with open(os.path.join(OUT_DIR, f"zone_hours_{day}.csv"), "w") as f:
        f.write("lot_id,zone,hours,amount,mean_air_temp,n_readings\n")
        for r in rows:
            f.write(",".join("" if v is None else str(v) for v in r) + "\n")
    log.info("rollup done day=%s lots=%d took=%.0fs", day, len(rows), time.time() - t0)


def main():
    log.info("billing scheduler started run_at=%02d:00", RUN_AT_H)
    last_day = None
    while True:
        now = time.gmtime()
        day = time.strftime("%Y-%m-%d", now)
        if now.tm_hour == RUN_AT_H and day != last_day:
            last_day = day
            run_once()
        time.sleep(30)


if __name__ == "__main__":
    main()
