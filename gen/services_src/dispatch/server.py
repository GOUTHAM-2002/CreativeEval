"""Dispatch: pallet reconciliation queue. Jobs arrive from the gateway (scanner moves and controller
activity) and are applied to the ledger by a small worker pool."""
import json
import os
import sqlite3
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import netutil  # noqa: E402
from common.config import load  # noqa: E402
from common.httpd import JSONHandler, serve  # noqa: E402
from common.logutil import setup  # noqa: E402

cfg = load()
log = setup("dispatch", cfg.get("LOG_LEVEL", "INFO"))
LEDGER = cfg["LEDGER_URL"]
QUEUE_DB = cfg["DISPATCH_QUEUE_DB"]
WORKERS = int(cfg.get("DISPATCH_WORKERS", 2))
WMS_LOOKUP_S = float(cfg.get("WMS_LOOKUP_S", 20))
POLL_S = float(cfg.get("DISPATCH_POLL_S", 15))
_tls = threading.local()
_wms_lock = threading.Lock()
_enq_lock = threading.Lock()
_enq_conn = None


def qdb():
    conn = getattr(_tls, "conn", None)
    if conn is None:
        conn = sqlite3.connect(QUEUE_DB, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        _tls.conn = conn
    return conn


def init():
    c = sqlite3.connect(QUEUE_DB)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, kind TEXT, payload TEXT, state TEXT, created_at TEXT, started_at TEXT, done_at TEXT, worker TEXT)")
    c.commit(); c.close()


def wms_pallet_lookup(lot):
    """Weight/dimension lookup against the WMS export. Slow link, one lookup at a time (the export is a
    single file opened exclusively); runs inline for now (TODO async)."""
    with _wms_lock:
        time.sleep(WMS_LOOKUP_S)
    return {"lot": lot, "ok": True}


class H(JSONHandler):
    routes = {}


def post_jobs(h, path, body):
    job_id = uuid.uuid4().hex[:12]
    if body.get("kind") == "pallet_move":
        wms_pallet_lookup(body.get("lot"))
    global _enq_conn
    with _enq_lock:
        if _enq_conn is None:
            _enq_conn = sqlite3.connect(QUEUE_DB, timeout=30, isolation_level=None, check_same_thread=False)
        _enq_conn.execute("INSERT INTO jobs(job_id, kind, payload, state, created_at) VALUES (?,?,?,?,?)",
                          (job_id, body.get("kind", "unknown"), json.dumps(body), "queued", netutil.now_iso()))
    log.info("job queued id=%s kind=%s lot=%s", job_id, body.get("kind"), body.get("lot"))
    return 202, {"job_id": job_id}


def get_jobs(h, path, body):
    return 200, {"jobs": [dict(r) for r in qdb().execute("SELECT job_id, kind, state, created_at, done_at FROM jobs ORDER BY created_at DESC LIMIT 200")]}


def get_health(h, path, body):
    n = qdb().execute("SELECT COUNT(*) FROM jobs WHERE state='queued'").fetchone()[0]
    return 200, {"ok": True, "queued": n}


H.routes = {("POST", "/jobs"): post_jobs, ("GET", "/jobs"): get_jobs, ("GET", "/health"): get_health}


def apply_move(job_id, p, worker):
    lot, to_zone, from_zone = p["lot"], p["to"], p.get("from")
    status, cur = netutil.http_call(f"{LEDGER}/lots/{lot}", "GET", timeout_s=20)
    if status != 200:
        log.error("[%s] job %s: lot %s not found in ledger (%s)", worker, job_id, lot, status)
        return
    if from_zone and cur["zone"] != from_zone:
        log.warning("[%s] job %s: zone mismatch for %s: scanner says from=%s, ledger has %s; applying move to %s anyway",
                    worker, job_id, lot, from_zone, cur["zone"], to_zone)
    time.sleep(0.5)  # audit trail write-behind
    status, _ = netutil.http_call(f"{LEDGER}/lots/{lot}/zone", "PUT",
                                  {"zone": to_zone, "from_zone": cur["zone"], "operator": p.get("operator"), "job_id": job_id,
                                   "note": None if not from_zone or cur["zone"] == from_zone else f"scanner from={from_zone}"},
                                  timeout_s=20)
    if status >= 300:
        log.error("[%s] job %s: ledger update failed (%s)", worker, job_id, status)
    else:
        log.info("[%s] job %s applied: %s %s->%s", worker, job_id, lot, cur["zone"], to_zone)


def reconcile(job_id, p, worker):
    # activity events: nothing to apply, but make sure the zone is known to the ledger
    time.sleep(1.0)
    log.debug("[%s] job %s reconcile zone=%s ok", worker, job_id, p.get("zone"))


def worker_loop(name):
    while True:
        conn = qdb()
        row = conn.execute("SELECT job_id, kind, payload FROM jobs WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
        if row is None:
            time.sleep(POLL_S)
            continue
        cur = conn.execute("UPDATE jobs SET state='running', started_at=?, worker=? WHERE job_id=? AND state='queued'", (netutil.now_iso(), name, row["job_id"]))
        if cur.rowcount == 0:
            continue
        p = json.loads(row["payload"])
        try:
            if row["kind"] == "pallet_move":
                apply_move(row["job_id"], p, name)
            else:
                reconcile(row["job_id"], p, name)
        except Exception as e:  # noqa: BLE001
            log.error("[%s] job %s failed: %s", name, row["job_id"], e)
        conn.execute("UPDATE jobs SET state='done', done_at=? WHERE job_id=?", (netutil.now_iso(), row["job_id"]))


def main():
    init()
    for i in range(WORKERS):
        threading.Thread(target=worker_loop, args=(f"w{i + 1}",), daemon=True).start()
    log.info("dispatch serving %s:%s workers=%d", cfg["DISPATCH_HOST"], cfg["DISPATCH_PORT"], WORKERS)
    serve(H, cfg["DISPATCH_HOST"], int(cfg["DISPATCH_PORT"])).serve_forever()


if __name__ == "__main__":
    main()
