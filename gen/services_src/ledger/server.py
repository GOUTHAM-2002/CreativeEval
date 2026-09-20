"""Ledger: the system of record (SQLite). Everything else talks to it over HTTP; billing is the
exception and opens the file directly (historical, see billing/nightly.py)."""
import json
import os
import sqlite3
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import netutil  # noqa: E402
from common.config import load  # noqa: E402
from common.httpd import JSONHandler, serve  # noqa: E402
from common.logutil import setup  # noqa: E402

cfg = load()
log = setup("ledger", cfg.get("LOG_LEVEL", "INFO"))
DB_PATH = cfg["LEDGER_DB"]
BUSY_TIMEOUT_S = float(cfg.get("LEDGER_BUSY_TIMEOUT_S", 5))
_tls = threading.local()
_pool = []
_pool_lock = threading.Lock()


class _Pooled:
    """Borrow a connection from a small pool for the duration of one request (request threads are short-lived)."""

    def __enter__(self):
        with _pool_lock:
            self.conn = _pool.pop() if _pool else None
        if self.conn is None:
            self.conn = sqlite3.connect(DB_PATH, timeout=BUSY_TIMEOUT_S, isolation_level=None, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        return self.conn

    def __exit__(self, *a):
        with _pool_lock:
            if len(_pool) < 8:
                _pool.append(self.conn)
            else:
                self.conn.close()


def db():
    conn = getattr(_tls, "conn", None)
    if conn is None:
        with _pool_lock:
            conn = _pool.pop() if _pool else None
        if conn is None:
            conn = sqlite3.connect(DB_PATH, timeout=BUSY_TIMEOUT_S, isolation_level=None, check_same_thread=False)
            conn.row_factory = sqlite3.Row
        _tls.conn = conn
    return conn


def release():
    conn = getattr(_tls, "conn", None)
    if conn is not None:
        _tls.conn = None
        with _pool_lock:
            if len(_pool) < 8:
                _pool.append(conn)
                return
        conn.close()


def init():
    conn = sqlite3.connect(DB_PATH, timeout=BUSY_TIMEOUT_S)
    conn.execute("PRAGMA journal_mode=WAL")
    with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


class H(JSONHandler):
    routes = {}

    def _dispatch(self, method):
        try:
            return super()._dispatch(method)
        finally:
            release()


def post_readings(h, path, body):
    try:
        conn = db()
        conn.execute(
            "INSERT INTO readings(ctrl_id, seq, recv, zone, air_temp, comp_state, setpoint, unknown_tokens, raw) VALUES (?,?,?,?,?,?,?,?,?)",
            (body["ctrl_id"], body["seq"], body["recv"], body.get("zone"), body.get("air_temp"), body.get("comp_state"),
             body.get("setpoint"), json.dumps(body.get("unknown") or []), body["raw"]))
        if body.get("zone") and body.get("air_temp") is not None:
            conn.execute("INSERT INTO latest_readings(zone, recv, air_temp, comp_state, seq, ctrl_id) VALUES (?,?,?,?,?,?) "
                         "ON CONFLICT(zone) DO UPDATE SET recv=excluded.recv, air_temp=excluded.air_temp, comp_state=excluded.comp_state, seq=excluded.seq, ctrl_id=excluded.ctrl_id",
                         (body["zone"], body["recv"], body["air_temp"], body.get("comp_state"), body["seq"], body["ctrl_id"]))
    except sqlite3.OperationalError as e:
        log.error("readings insert failed ctrl=%s seq=%s: %s", body.get("ctrl_id"), body.get("seq"), e)
        return 503, {"error": str(e)}
    return 201, {"ok": True}


def get_readings_latest(h, path, body):
    out = rows(db().execute("SELECT zone, recv, air_temp, comp_state FROM latest_readings ORDER BY zone"))
    return 200, {"latest": out}


def get_lots(h, path, body):
    return 200, {"lots": rows(db().execute("SELECT * FROM lots ORDER BY lot_id"))}


def get_lot(h, path, body):
    lot = path.rsplit("/", 1)[-1]
    r = rows(db().execute("SELECT * FROM lots WHERE lot_id=?", (lot,)))
    return (200, r[0]) if r else (404, {"error": "no such lot"})


def put_lot_zone(h, path, body):
    lot = path.split("/")[-2]
    try:
        db().execute("UPDATE lots SET zone=?, updated_at=? WHERE lot_id=?", (body["zone"], netutil.now_iso(), lot))
        db().execute("INSERT INTO moves(job_id, lot_id, from_zone, to_zone, operator, applied_at, note) VALUES (?,?,?,?,?,?,?)",
                     (body.get("job_id"), lot, body.get("from_zone"), body["zone"], body.get("operator"), netutil.now_iso(), body.get("note")))
    except sqlite3.OperationalError as e:
        log.error("lot update failed lot=%s: %s", lot, e)
        return 503, {"error": str(e)}
    return 200, {"ok": True}


def post_probe(h, path, body):
    try:
        db().execute("INSERT INTO probe_checks(zone, handheld, operator, reading, taken_at, entered_at) VALUES (?,?,?,?,?,?)",
                     (body["zone"], body["handheld"], body["operator"], body["reading"], body["taken_at"], netutil.now_iso()))
    except sqlite3.OperationalError as e:
        return 503, {"error": str(e)}
    return 201, {"ok": True}


def post_events(h, path, body):
    try:
        db().execute("INSERT INTO events(kind, ctrl_id, zone, t, detail) VALUES (?,?,?,?,?)",
                     (body["kind"], body.get("ctrl_id"), body.get("zone"), body.get("t") or netutil.now_iso(), json.dumps(body.get("detail") or {})))
    except sqlite3.OperationalError as e:
        return 503, {"error": str(e)}
    return 201, {"ok": True}


def post_alerts(h, path, body):
    try:
        if body.get("state") == "cleared":
            db().execute("UPDATE alerts SET state='cleared', cleared_at=? WHERE alert_id=? AND state='active'", (netutil.now_iso(), body["alert_id"]))
        else:
            db().execute("INSERT INTO alerts(alert_id, zone, rule, severity, value, channel, state, raised_at) VALUES (?,?,?,?,?,?,?,?)",
                         (body["alert_id"], body.get("zone"), body["rule"], body["severity"], body.get("value"), body.get("channel"), "active", netutil.now_iso()))
    except sqlite3.OperationalError as e:
        return 503, {"error": str(e)}
    return 201, {"ok": True}


def get_zone_config(h, path, body):
    return 200, {"zones": rows(db().execute("SELECT * FROM zone_config ORDER BY zone"))}


def post_audit(h, path, body):
    db().execute("INSERT INTO audit(at, actor, action, detail) VALUES (?,?,?,?)", (netutil.now_iso(), body["actor"], body["action"], json.dumps(body.get("detail") or {})))
    return 201, {"ok": True}


def get_health(h, path, body):
    return 200, {"ok": True}


H.routes = {("POST", "/readings"): post_readings, ("GET", "/readings/latest"): get_readings_latest,
            ("GET", "/lots"): get_lots, ("PUT", "/lots"): put_lot_zone, ("POST", "/probe_checks"): post_probe,
            ("POST", "/events"): post_events, ("POST", "/alerts"): post_alerts, ("GET", "/zone_config"): get_zone_config,
            ("POST", "/audit"): post_audit, ("GET", "/health"): get_health}
# /lots/<id> GET must be checked after the exact /lots route
H.routes[("GET", "/lots/")] = get_lot


def main():
    init()
    log.info("ledger serving %s:%s db=%s", cfg["LEDGER_HOST"], cfg["LEDGER_PORT"], DB_PATH)
    serve(H, cfg["LEDGER_HOST"], int(cfg["LEDGER_PORT"])).serve_forever()


if __name__ == "__main__":
    main()
