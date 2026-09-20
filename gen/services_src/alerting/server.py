"""Alerting: polls the ledger, evaluates threshold rules per zone, posts to chat channels via the
notifier and records alerts in the ledger."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import netutil  # noqa: E402
from common.config import load  # noqa: E402
from common.logutil import setup  # noqa: E402

cfg = load()
log = setup("alerting", cfg.get("LOG_LEVEL", "INFO"))
LEDGER = cfg["LEDGER_URL"]
POLL_S = int(cfg.get("ALERT_POLL_S", 60))
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
HERE = os.path.dirname(os.path.abspath(__file__))
_active = {}
_routes_mtime = 0.0
_routes = {}


def routes():
    """alerting/routes.json is re-read when it changes so hotfixes do not need a restart."""
    global _routes, _routes_mtime
    path = os.path.join(HERE, "routes.json")
    try:
        m = os.path.getmtime(path)
    except OSError:
        return _routes
    if m != _routes_mtime:
        with open(path) as f:
            _routes = json.load(f)
        _routes_mtime = m
        log.info("routes loaded: %s", json.dumps({z: v.get("channel") for z, v in _routes.get("zones", {}).items()}))
    return _routes


def notify(channel, text):
    """Chat notifier. Channels that have been archived accept the post but nobody sees it."""
    log.info("POST %s: %s", channel, text)


def evaluate(latest):
    r = routes()
    min_sev = str(load().get("ALERT_MIN_SEVERITY", r.get("min_severity", "warning"))).lower()
    for row in latest:
        zone = row.get("zone")
        if zone is None or zone not in r.get("zones", {}):
            continue
        zr = r["zones"][zone]
        v = row.get("air_temp")
        if v is None:
            continue
        fired = None
        if v > zr["high"]:
            fired = ("high_temp", "critical", v)
        elif v < zr["low"]:
            fired = ("low_temp", "warning", v)
        key = (zone, fired[0]) if fired else None
        for (z, rule), a in list(_active.items()):
            if z == zone and (fired is None or rule != fired[0]):
                log.info("cleared alert=%s zone=%s rule=%s value=%s", a["alert_id"], z, rule, v)
                netutil.http_call(LEDGER + "/alerts", "POST", {"alert_id": a["alert_id"], "state": "cleared"}, timeout_s=20)
                del _active[(z, rule)]
        if fired and key not in _active:
            rule, sev, val = fired
            alert_id = f"AL-{int(time.time()) % 100000:05d}-{zone}"
            channel = zr.get("channel", r.get("default_channel"))
            if SEVERITY_RANK[sev] < SEVERITY_RANK.get(min_sev, 1):
                log.debug("suppressed alert zone=%s rule=%s severity=%s value=%.1f (min_severity=%s)", zone, rule, sev, val, min_sev)
                continue
            _active[key] = {"alert_id": alert_id}
            log.warning("raised alert=%s zone=%s rule=%s severity=%s value=%.1f channel=%s", alert_id, zone, rule, sev, val, channel)
            notify(channel, f"[{sev.upper()}] zone {zone} {rule.replace('_', ' ')}: {val:.1f} C (limits {zr['low']}..{zr['high']})")
            netutil.http_call(LEDGER + "/alerts", "POST", {"alert_id": alert_id, "zone": zone, "rule": rule, "severity": sev, "value": val, "channel": channel}, timeout_s=20)


def main():
    log.info("alerting started poll=%ss", POLL_S)
    while True:
        try:
            status, body = netutil.http_call(LEDGER + "/readings/latest", "GET", timeout_s=20)
            if status == 200:
                evaluate(body.get("latest", []))
            else:
                log.error("ledger poll failed: %s", status)
        except (netutil.CallTimeout, ConnectionError, OSError) as e:
            log.error("ledger poll error: %s", e)
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
