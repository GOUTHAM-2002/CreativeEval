#!/usr/bin/env python3
# Replays one world into the live coldchain stack. Runs INSIDE the build sandbox under libfaketime.
# Inputs (in /build): driver_config.json, frames.jsonl, schedule.jsonl. Outputs: logs, DB dumps, report.
import json
import os
import random
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections import deque

BUILD = "/build"
REPO = "/opt/coldchain"
VAR = "/var/lib/coldchain"
cfg = json.load(open(f"{BUILD}/driver_config.json"))
SIM0 = cfg["sim_start_epoch"]
GW = ("127.0.0.1", cfg["gateway_tcp_port"])
GW_API = f"http://127.0.0.1:{cfg['gateway_api_port']}"
LEDGER = f"http://127.0.0.1:{cfg['ledger_port']}"
rng = random.Random(cfg["driver_seed"])
report = {"unacked": 0, "dropped_radio": 0, "unsent_linkdown": 0, "sent": 0, "late_max_s": 0.0, "late_over_60s": 0,
          "link_events": [], "moves_posted": 0, "probes_posted": 0, "audits_posted": 0, "commits": [], "snapshot": None, "errors": []}


def now():
    return time.time()


def iso(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts if ts is not None else now()))


def wait_until(t_abs):
    while True:
        d = t_abs - now()
        if d <= 0:
            return -d
        time.sleep(min(d, 30.0))


def http(url, method="GET", body=None, timeout_s=60.0):
    import urllib.request
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    deadline = now() + timeout_s
    while True:
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                text = r.read().decode()
                return r.status, (json.loads(text) if text else None)
        except Exception as e:  # noqa: BLE001
            if now() > deadline:
                raise
            time.sleep(2)


class Link:
    """One controller uplink: send lines, collect ACKs on a reader thread."""

    def __init__(self, zone, ctrl):
        self.zone, self.ctrl = zone, ctrl
        self.sock = None
        self.acked = set()
        self.pending = {}
        self.lock = threading.Lock()
        self.buffer = deque(maxlen=cfg["fault_buffer_len"])
        self.up = False
        self.scheduled_down = False

    def connect(self):
        for _ in range(50):
            try:
                self.sock = socket.create_connection(GW, timeout=5)
                break
            except OSError:
                time.sleep(5)
        else:
            raise RuntimeError("gateway not reachable")
        self.up = True
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        s = self.sock
        buf = b""
        s.setblocking(False)
        while self.sock is s:
            try:
                chunk = s.recv(65536)
                if not chunk:
                    if self.sock is s:
                        self.up = False
                        report["link_events"].append({"t": iso(), "zone": self.zone, "ctrl": self.ctrl, "event": "down", "why": "closed by gateway"})
                    break
                buf += chunk
                while b"\n" in buf:
                    line, _, buf = buf.partition(b"\n")
                    parts = line.decode(errors="replace").split()
                    if len(parts) == 2 and parts[0] == "ACK":
                        with self.lock:
                            self.acked.add(int(parts[1]))
                            self.pending.pop(int(parts[1]), None)
            except BlockingIOError:
                time.sleep(1.0)
            except OSError:
                break

    def close(self, why):
        self.scheduled_down = why in ("peer reset", "power loss", "end of run")
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()
        self.sock = None
        self.up = False
        report["link_events"].append({"t": iso(), "zone": self.zone, "ctrl": self.ctrl, "event": "down", "why": why})

    def reopen(self):
        self.scheduled_down = False
        self.connect()
        report["link_events"].append({"t": iso(), "zone": self.zone, "ctrl": self.ctrl, "event": "up"})

    def send(self, seq, line):
        self.buffer.append(line)
        if not self.up:
            if not self.scheduled_down:
                try:
                    self.connect()
                    report["reconnects"] = report.get("reconnects", 0) + 1
                    report["link_events"].append({"t": iso(), "zone": self.zone, "ctrl": self.ctrl, "event": "up"})
                except Exception as e2:  # noqa: BLE001
                    report["errors"].append(f"reconnect {self.ctrl}: {e2}")
                    return "linkdown"
            else:
                report["unsent_linkdown"] += 1
                return "linkdown"
        try:
            self.sock.sendall((line + "\n").encode())
        except OSError as e:
            # a real unit reconnects when its uplink drops; the frame in flight is lost
            report["errors"].append(f"send {self.ctrl} seq={seq}: {e}")
            report.setdefault("reconnects", 0)
            try:
                self.close("send failed: %s" % e)
                self.connect()
                report["reconnects"] += 1
                report["link_events"].append({"t": iso(), "zone": self.zone, "ctrl": self.ctrl, "event": "up"})
            except Exception as e2:  # noqa: BLE001
                report["errors"].append(f"reconnect {self.ctrl}: {e2}")
            return "senderr"
        with self.lock:
            self.pending[seq] = now()
        report["sent"] += 1
        return "sent"

    def sweep_unacked(self):
        cutoff = now() - cfg["ack_deadline_s"]
        with self.lock:
            stale = [s for s, t in self.pending.items() if t < cutoff]
            for s in stale:
                self.pending.pop(s, None)
        report["unacked"] += len(stale)


SERVICES = [("ledger", "ledger/server.py"), ("dispatch", "dispatch/server.py"), ("gateway", "gateway/server.py"),
            ("alerting", "alerting/server.py"), ("billing", "billing/nightly.py")]


def launch_services(procs):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for name, rel in SERVICES:
        out = open(f"{BUILD}/svc_{name}.out", "a")
        procs[name] = subprocess.Popen([sys.executable, f"{REPO}/{rel}"], cwd=REPO, env=env, stdout=out, stderr=subprocess.STDOUT)
        time.sleep(20)
    http(LEDGER + "/health", timeout_s=600)
    http(GW_API + "/health", timeout_s=600)


def stop_services(procs):
    for name, p in procs.items():
        p.send_signal(signal.SIGTERM)
    for name, p in procs.items():
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
    procs.clear()


def start_services():
    procs = {}
    logs = f"{REPO}/deploy/logs"
    os.makedirs(logs, exist_ok=True)
    os.makedirs(VAR, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run([sys.executable, f"{REPO}/ledger/seed_inventory.py", f"{BUILD}/inventory_import.csv", f"{BUILD}/zones.json"],
                   cwd=REPO, env=env, check=True, capture_output=True)
    launch_services(procs)
    return procs


def power_outage(procs, links, minutes):
    # the site loses power: every controller link drops, the host goes down hard, logs rotate on the way back up
    for l in links.values():
        l.close("power loss")
    for name, p in procs.items():
        p.kill()
    procs.clear()
    report.setdefault("outages", []).append({"t": iso(), "minutes": minutes})
    time.sleep(minutes * 60)
    logs = f"{REPO}/deploy/logs"
    for name, _ in SERVICES:
        src = f"{logs}/{name}.log"
        if os.path.exists(src):
            n = 1
            while os.path.exists(f"{src}.{n}"):
                n += 1
            os.rename(src, f"{src}.{n}")
    launch_services(procs)
    for l in links.values():
        l.reopen()


def git(*args, author=None, when=None):
    env = dict(os.environ)
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "HOME": BUILD})
    if author:
        env.update({"GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1], "GIT_COMMITTER_NAME": author[0], "GIT_COMMITTER_EMAIL": author[1]})
    if when:
        env.update({"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when})
    return subprocess.run(["git", "-C", REPO, *args], env=env, capture_output=True, text=True)


_rlock = threading.Lock()


def _post_async(label, url, body):
    def run():
        try:
            http(url, "POST", body, timeout_s=1800)
            with _rlock:
                report[label] += 1
        except Exception as e:  # noqa: BLE001
            with _rlock:
                report["errors"].append(f"{label} {body.get('lot') or body.get('zone')}: {e}")
    threading.Thread(target=run, daemon=True).start()


def apply_schedule_item(it, links):
    k = it["kind"]
    if k == "move":
        _post_async("moves_posted", GW_API + "/api/move", {"lot": it["lot"], "from": it["from"], "to": it["to"], "operator": it["actor"],
                                                           "forklift": it["forklift"], "pallet": it["pallet"]})
    elif k == "probe":
        _post_async("probes_posted", LEDGER + "/probe_checks", {"zone": it["zone"], "handheld": it["handheld"], "operator": it["actor"],
                                                                "reading": it["reading"], "taken_at": it["taken_at"]})
    elif k == "edit_commit":
        for path, content in it["files"].items():
            with open(f"{REPO}/{path}", "w") as f:
                f.write(content)
        git("add", "-A")
        r = git("commit", "-q", "-m", it["message"], author=(it["author_name"], it["author_email"]))
        h = git("rev-parse", "--short", "HEAD").stdout.strip()
        report["commits"].append({"t": iso(), "sha7": h, "message": it["message"], "rc": r.returncode, "err": r.stderr[-200:]})
    elif k == "write_file":
        with open(f"{REPO}/{it['path']}", "w") as f:
            f.write(it["content"])
        report.setdefault("files_written", []).append({"t": iso(), "path": it["path"]})
    elif k == "link_down":
        links[it["zone"]].close(it.get("why", "peer reset"))
    elif k == "link_up":
        links[it["zone"]].reopen()
    elif k == "power_outage":
        power_outage(PROCS, links, it["minutes"])
    elif k == "audit":
        _post_async("audits_posted", LEDGER + "/audit", {"actor": it["actor"], "action": it["action"], "detail": it.get("detail", {})})


PROCS = {}


def main():
    procs = start_services()
    PROCS.update(procs)
    links = {z: Link(z, c) for z, c in cfg["controllers"].items()}
    for l in links.values():
        l.connect()
    frames = [json.loads(l) for l in open(f"{BUILD}/frames.jsonl")]
    sched = [json.loads(l) for l in open(f"{BUILD}/schedule.jsonl")]
    items = [("f", f["t_sec"], i, f) for i, f in enumerate(frames)] + [("s", s["t_sec"], i, s) for i, s in enumerate(sched)]
    items.sort(key=lambda x: (x[1], 0 if x[0] == "s" else 1, x[2]))
    snap_zone, snap_done = cfg["snapshot"]["zone"], False
    snap_lo, snap_hi = cfg["snapshot"]["t_sec_lo"], cfg["snapshot"]["t_sec_hi"]
    last_sweep = 0
    for kind, t_sec, _, it in items:
        late = wait_until(SIM0 + t_sec)
        if late > report["late_max_s"]:
            report["late_max_s"] = round(late, 1)
        if late > 60:
            report["late_over_60s"] += 1
        if kind == "s":
            apply_schedule_item(it, links)
            continue
        link = links[it["zone"]]
        if it["droppable"] and rng.random() < cfg["frame_dropout"]:
            report["dropped_radio"] += 1
            link.buffer.append(it["line"])
            continue
        link.send(it["seq"], it["line"])
        if not snap_done and it["zone"] == snap_zone and it.get("event") == "LOCKOUT_ENTER" and snap_lo <= t_sec <= snap_hi:
            snap = list(link.buffer)
            with open(f"{BUILD}/ringbuffer.txt", "w") as f:
                f.write(f"# {cfg['vendor_model']} fault snapshot  unit={link.ctrl}  entries={len(snap)}  trigger=lockout\n")
                for i, line in enumerate(snap):
                    f.write(f"{i:03d} {line}\n")
            report["snapshot"] = {"t": iso(), "t_sec": t_sec, "entries": len(snap), "zone": snap_zone}
            snap_done = True
        if t_sec - last_sweep > 300:
            for l in links.values():
                l.sweep_unacked()
            last_sweep = t_sec
    wait_until(SIM0 + cfg["sim_end_sec"] + 1800)
    for l in links.values():
        l.sweep_unacked()
        l.close("end of run")
    stop_services(PROCS)
    for name, path in [("ledger", f"{VAR}/ledger.db"), ("queue", f"{VAR}/queue.db")]:
        conn = sqlite3.connect(path)
        with open(f"{BUILD}/{name}.sql", "w") as f:
            for line in conn.iterdump():
                f.write(line + "\n")
        conn.close()
    report["git_log"] = git("log", "--format=%h %ad %an %s", "--date=iso").stdout
    report["git_status"] = git("status", "--porcelain", "--ignored").stdout
    report["ended"] = iso()
    json.dump(report, open(f"{BUILD}/driver_report.json", "w"), indent=1)


if __name__ == "__main__":
    main()
