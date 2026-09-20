"""Controller gateway: accepts KW-7 telegram links over TCP, decodes what we know, forwards to ledger,
and notifies dispatch about door/move activity.

Protocol (per controller link): one telegram per line, newline terminated. We answer each line with
"ACK <seq>\n" once the ledger has stored it; the units resend nothing, so a missed ACK is a lost frame
(they keep a small diagnostic buffer, see docs/rh7_integration_note_v2.txt).
"""
import json
import os
import queue
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import netutil  # noqa: E402
from common.config import load  # noqa: E402
from common.logutil import setup  # noqa: E402
from gateway import rh7_decode  # noqa: E402

cfg = load()
log = setup("gateway", cfg.get("LOG_LEVEL", "INFO"))
LEDGER = cfg["LEDGER_URL"]
DISPATCH = cfg["DISPATCH_URL"]
WEBHOOK_TIMEOUT_S = float(cfg.get("WEBHOOK_TIMEOUT_S", 30))
WEBHOOK_RETRIES = int(cfg.get("WEBHOOK_RETRIES", 1))
WEBHOOK_RETRY_BACKOFF_S = float(cfg.get("WEBHOOK_RETRY_BACKOFF_S", 120))
LEDGER_TIMEOUT_S = float(cfg.get("LEDGER_TIMEOUT_S", 20))
STALE_AFTER_S = int(cfg.get("STALE_AFTER_S", 900))
SETPOINTS = {z: float(v) for z, v in cfg["ZONES"]["setpoints"].items()}
_last_seen = {}
_lock = threading.Lock()


_notify_q = queue.Queue()


def notify_dispatch(event):
    """Door/move activity feeds the pallet reconciliation queue (posted from a background thread)."""
    _notify_q.put(event)


def _notify_worker():
    while True:
        event = _notify_q.get()
        _post_dispatch(event)


def _post_dispatch(event):
    """Retried once on timeout."""
    attempt = 0
    while True:
        try:
            status, body = netutil.http_call(DISPATCH + "/jobs", "POST", event, timeout_s=WEBHOOK_TIMEOUT_S)
            if status >= 300:
                log.warning("dispatch webhook rejected (%s): %s", status, body)
            else:
                log.debug("dispatch webhook ok job=%s", (body or {}).get("job_id"))
            return
        except netutil.CallTimeout:
            attempt += 1
            log.warning("dispatch webhook timeout after %.0fs (attempt %d) event=%s", WEBHOOK_TIMEOUT_S, attempt, event.get("kind"))
            if attempt > WEBHOOK_RETRIES:
                return
            time.sleep(WEBHOOK_RETRY_BACKOFF_S)   # give dispatch time to drain before retrying
        except (ConnectionError, OSError) as e:
            log.error("dispatch webhook failed: %s", e)
            return


def store_reading(rec):
    status, body = netutil.http_call(LEDGER + "/readings", "POST", rec, timeout_s=LEDGER_TIMEOUT_S)
    if status >= 300:
        raise RuntimeError(f"ledger {status}: {body}")


def handle_line(line, peer):
    recv = netutil.now_iso()
    try:
        d = rh7_decode.decode_line(line, SETPOINTS)
    except Exception as e:  # noqa: BLE001
        log.error("undecodable frame from %s: %r (%s)", peer, line[:120], e)
        return None
    ctrl, seq = d["ctrl_id"], d["seq"]
    with _lock:
        _last_seen[ctrl] = time.time()
    rec = {"ctrl_id": ctrl, "seq": seq, "recv": recv, "raw": line}
    zone = None
    for c in d["clauses"]:
        zone = c.get("zone") or zone
        if c.get("head") == "AIR_TEMP" and c.get("value") is not None:
            rec["zone"] = c["zone"]
            rec["air_temp"] = c["value"]
        elif c.get("head") in ("RUN", "IDLE"):
            rec["zone"] = c["zone"]
            rec["comp_state"] = c["head"]
        elif c.get("head") == "SETPOINT":
            rec["zone"] = c["zone"]
            rec["setpoint"] = c["value"]
    rec["zone"] = rec.get("zone") or zone
    rec["unknown"] = d["unknown"]
    decoded = {k: rec[k] for k in ("zone", "air_temp", "comp_state", "setpoint") if k in rec}
    log.info("recv=%s ctrl=%s seq=%s raw=%s decoded=%s unk=%s", recv, ctrl, seq, json.dumps(line), json.dumps(decoded), json.dumps(d["unknown"]))
    try:
        store_reading(rec)
    except (RuntimeError, netutil.CallTimeout, ConnectionError, OSError) as e:
        log.error("ledger write failed ctrl=%s seq=%s: %s (frame not acked)", ctrl, seq, e)
        return None
    if "air_temp" not in rec and "comp_state" not in rec:
        # frames without a reading are activity events (doors etc): let dispatch reconcile pallet positions
        notify_dispatch({"kind": "controller_event", "ctrl_id": ctrl, "zone": rec["zone"], "seq": seq, "recv": recv})
    return seq


def serve_link(conn, addr):
    peer = f"{addr[0]}:{addr[1]}"
    log.info("controller link accepted from %s", peer)
    buf = b""
    try:
        conn.setblocking(False)
        while True:
            try:
                chunk = conn.recv(65536)
            except BlockingIOError:
                time.sleep(0.2)
                continue
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                text = line.decode(errors="replace").strip()
                if not text:
                    continue
                try:
                    seq = handle_line(text, peer)
                except Exception as e:  # noqa: BLE001
                    log.error("frame handling error from %s: %s", peer, e)
                    seq = None
                if seq is not None:
                    try:
                        conn.sendall(f"ACK {seq}\n".encode())
                    except OSError:
                        break
    except ConnectionResetError:
        log.warning("controller link reset by peer %s", peer)
    finally:
        log.info("controller link closed %s", peer)
        conn.close()


def api_thread():
    """Handheld scanner endpoint: pallet moves come in here and go straight to dispatch."""
    from common.httpd import JSONHandler, serve

    class H(JSONHandler):
        routes = {}

    def post_move(h, path, body):
        body = dict(body)
        body["kind"] = "pallet_move"
        body["recv"] = netutil.now_iso()
        log.info("scanner move lot=%s from=%s to=%s by=%s", body.get("lot"), body.get("from"), body.get("to"), body.get("operator"))
        notify_dispatch(body)
        return 202, {"queued": True}

    def get_health(h, path, body):
        with _lock:
            stale = [c for c, t in _last_seen.items() if time.time() - t > STALE_AFTER_S]
        return 200, {"ok": True, "stale": stale}

    H.routes = {("POST", "/api/move"): post_move, ("GET", "/health"): get_health}
    serve(H, cfg["GATEWAY_API_HOST"], int(cfg["GATEWAY_API_PORT"])).serve_forever()


def stale_watch():
    while True:
        time.sleep(60)
        now = time.time()
        with _lock:
            items = list(_last_seen.items())
        for ctrl, t in items:
            if now - t > STALE_AFTER_S:
                log.warning("controller %s stale: no frames for %d s", ctrl, int(now - t))
                try:
                    netutil.http_call(LEDGER + "/events", "POST", {"kind": "controller_stale", "ctrl_id": ctrl, "t": netutil.now_iso(), "age_s": int(now - t)}, timeout_s=LEDGER_TIMEOUT_S)
                except Exception:  # noqa: BLE001
                    pass


def main():
    threading.Thread(target=api_thread, daemon=True).start()
    threading.Thread(target=_notify_worker, daemon=True).start()
    threading.Thread(target=stale_watch, daemon=True).start()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((cfg["GATEWAY_TCP_HOST"], int(cfg["GATEWAY_TCP_PORT"])))
    srv.listen(16)
    log.info("gateway listening tcp=%s:%s api=%s:%s decoder=%s", cfg["GATEWAY_TCP_HOST"], cfg["GATEWAY_TCP_PORT"], cfg["GATEWAY_API_HOST"], cfg["GATEWAY_API_PORT"], rh7_decode.__name__)
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=serve_link, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()
