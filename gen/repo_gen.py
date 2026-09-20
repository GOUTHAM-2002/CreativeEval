# Materialise the services repo for one world: substitutions, generated decoder/docs, backdated git history.
from __future__ import annotations
import datetime as dt
import json
import os
import random
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "services_src"

PRE_COMMITS = [
    # (days before start, author_role, message, files-or-callable)
    (270, "former", "initial import: ledger service and shared http/config helpers", ["common", "ledger", "README.md", ".gitignore", "deploy/config.json", "deploy/run_all.sh"]),
    (262, "former", "ledger: probe_checks and audit tables", ["ledger/schema.sql"]),
    (240, "former", "gateway: partial {{VENDOR}} telemetry decoder from unit 01 bench captures", ["gateway/rh7_decode.py"]),
    (238, "former", "gateway: tcp link handler, ack after ledger write", ["gateway/__init__.py", "gateway/server.py"]),
    (221, "ops", "dispatch: reconciliation queue with worker pool", ["dispatch"]),
    (205, "ops", "alerting: per-zone thresholds, chat notifier, routes.json", ["alerting"]),
    (188, "sre", "billing: nightly zone-hours rollup (exclusive snapshot of the ledger file)", ["billing"]),
    (170, "manager", "docs: vendor quick reference card and floor plan", ["docs/rh7_integration_note_v2.txt", "docs/floor_plan.md"]),
    (151, "ops", "gateway: notify dispatch on controller activity frames", ["gateway/server.py"]),
    (133, "ops", "dispatch: inline WMS pallet lookup before queueing (temporary until the async export lands)", ["dispatch/server.py"]),
    (120, "sre", "common: deadline-based http client, socket timeouts unreliable on the gateway box (T-0188)", ["common/netutil.py"]),
    (96, "ops", "gateway: retry dispatch webhook once on timeout", ["gateway/server.py"]),
    (74, "manager", "docs: runbook for alerts and defrost schedule", ["docs/runbook.md"]),
    (55, "ops", "alerting: re-read routes.json on change (no restart for hotfixes)", ["alerting/server.py"]),
    (41, "sre", "gateway: stale-controller watchdog posts ledger events", ["gateway/server.py"]),
    (33, "sre", "ledger: WAL journal and longer busy timeout, writers were tripping over each other", ["ledger/server.py", "deploy/config.json"]),
    (17, "ops", "ledger: latest_readings table, the alerting poll was scanning the whole readings table", ["ledger/server.py", "ledger/schema.sql"]),
    (23, "ops", "config: raise webhook timeout to 30s, WMS lookup is slow", ["deploy/config.json"]),
    (9, "manager", "docs: inventory import procedure", ["docs/runbook.md", "ledger/seed_inventory.py", "deploy/inventory_import.csv", "deploy/zones.json"]),
]


def _git(repo: Path, *args, env=None, check=True):
    e = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(repo.parent)}
    if env:
        e.update(env)
    return subprocess.run(["git", "-C", str(repo), *args], env=e, check=check, capture_output=True, text=True)


def render_text(text: str, subs: dict) -> str:
    for k, v in subs.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def write_tree(repo: Path, world: dict, notation, subs: dict):
    zones = world["zones"]["order"]
    for src in SRC.rglob("*"):
        if src.is_dir() or "__pycache__" in src.parts:
            continue
        rel = src.relative_to(SRC)
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text()
        dst.write_text(render_text(text, subs))
        if src.suffix == ".sh":
            dst.chmod(0o755)
    (repo / "gateway" / "rh7_decode.py").write_text(notation.render_partial_decoder())
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "rh7_integration_note_v2.txt").write_text(notation.render_quickref())
    cfg = json.loads((repo / "deploy" / "config.json").read_text())
    cfg["ZONES"] = {"setpoints": {z: world["zones"]["setpoint"][z] for z in zones},
                    "controllers": {z: world["zones"]["controller"][z] for z in zones}}
    (repo / "deploy" / "config.json").write_text(json.dumps(cfg, indent=2) + "\n")
    routes = {"default_channel": "#alerts-coldchain", "min_severity": "warning", "zones": {}}
    for z in zones:
        sp, kind = world["zones"]["setpoint"][z], world["zones"]["kind"][z]
        hi, lo = (8.5, 0.5) if kind == "chill" else (round(sp + 7.0, 1), round(sp - 7.0, 1))
        routes["zones"][z] = {"high": hi, "low": lo, "channel": "#alerts-coldchain"}
    (repo / "alerting" / "routes.json").write_text(json.dumps(routes, indent=2) + "\n")
    (repo / ".gitignore").write_text("deploy/config.override.json\ndeploy/logs/\ndeploy/billing/\n*.db\n__pycache__/\n*.pyc\n")
    (repo / "ledger" / "seed_inventory.py").write_text('''"""One-off: import the WMS inventory export into the ledger (lots + zone_config)."""
import csv
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import load  # noqa: E402

cfg = load()


def main(lots_csv, zones_json):
    conn = sqlite3.connect(cfg["LEDGER_DB"], timeout=30)
    with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
        conn.executescript(f.read())
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(lots_csv) as f:
        for r in csv.DictReader(f):
            conn.execute("INSERT OR REPLACE INTO lots(lot_id, product, pallet_id, zone, qty, updated_at) VALUES (?,?,?,?,?,?)",
                         (r["lot_id"], r["product"], r["pallet_id"], r["zone"], int(r["qty"]), now))
    with open(zones_json) as f:
        for z, v in json.load(f).items():
            conn.execute("INSERT OR REPLACE INTO zone_config(zone, ctrl_id, setpoint, panel, kind) VALUES (?,?,?,?,?)",
                         (z, v["ctrl_id"], v["setpoint"], v["panel"], v["kind"]))
    conn.commit()
    print("imported", conn.execute("SELECT COUNT(*) FROM lots").fetchone()[0], "lots")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
''')
    with open(repo / "deploy" / "inventory_import.csv", "w") as f:
        f.write("lot_id,product,pallet_id,zone,qty\n")
        for l in world["lots_initial"]:
            f.write(f"{l['lot_id']},{l['product']},{l['pallet_id']},{l['zone']},{l['qty']}\n")
    zj = {z: {"ctrl_id": world["zones"]["controller"][z], "setpoint": world["zones"]["setpoint"][z],
              "panel": world["zones"]["panel"][z], "kind": world["zones"]["kind"][z]} for z in world["zones"]["order"]}
    (repo / "deploy" / "zones.json").write_text(json.dumps(zj, indent=1) + "\n")
    write_docs(repo, world, subs)


def write_docs(repo: Path, world: dict, subs: dict):
    zones = world["zones"]["order"]
    grid = world["params"]["grid"]
    cell = {v: k for k, v in grid.items()}
    rows = [[cell[i] for i in range(0, 3)], [cell[i] for i in range(3, 6)]]
    # outdated: the plan shows one wall that no longer matches (a pair toggled)
    rng = random.Random(f"floorplan:{world['seed']}")
    pairs = {tuple(p) for p in world["params"]["adjacency"]}
    all_pairs = {(a, b) for a in zones for b in zones if a < b}
    toggled = rng.choice(sorted(all_pairs - pairs))
    fp = f"""# Site floor plan ({subs['SITE']})

Cold rooms as built (2 x 3 block, doors on the south corridor). Shared walls are marked with `|` and `-`.

```
 {rows[0][0]}  |  {rows[0][1]}  |  {rows[0][2]}
----+-----+----
 {rows[1][0]}  |  {rows[1][1]}  |  {rows[1][2]}
```

Notes
- Rooms {toggled[0]} and {toggled[1]} are connected through the old pass-through hatch (sealed {rng.choice(['2021', '2022', '2023'])}, but still counts as a shared wall for the thermal survey).
- Dock doors serve {', '.join(world['plan']['receiving_zones'])}.
- Electrical: panels P1-P3 each feed two rooms (see the utility submeter export for the pairing).
- Controller ids: {', '.join(f'{z}={world["zones"]["controller"][z]}' for z in zones)}.
"""
    (repo / "docs" / "floor_plan.md").write_text(fp)
    rb = f"""# Runbook: coldchain-stack

## Alerts
- Warning = low temperature (a room colder than its band). Critical = high temperature. Pages go out through the ledger
  `alerts` table; the chat post is informational.
- If a room flaps, fix the sensor before muting anything. Muting is done in `alerting/routes.json` (channel per zone) and
  requires a PR; `ALERT_MIN_SEVERITY` in the config is for maintenance windows only and must be reverted the same day.

## Controllers ({subs['VENDOR']})
- Defrost runs on a fixed schedule every 6 hours per room; the rooms take turns so the heaters never overlap.
- A room that stops cooling after repeated compressor trips restarts on its own after the lockout timer; call the vendor
  if it happens more than once a week.
- Firmware updates are vendor-only. Keep the quick reference card (`docs/rh7_integration_note_v2.txt`) with the unit.

## Inventory
- Initial import: `python3 ledger/seed_inventory.py deploy/inventory_import.csv deploy/zones.json` (done once at go-live).
- Moves come from the handheld scanners via the gateway `/api/move`; never edit `lots` by hand.

## Nightly billing
- `billing/nightly.py` runs at 01:00 site time and writes `deploy/billing/zone_hours_<day>.csv`.
"""
    (repo / "docs" / "runbook.md").write_text(rb)


def make_history(repo: Path, world: dict, subs: dict):
    start = dt.datetime.strptime(world["sim"]["start_iso"], "%Y-%m-%dT%H:%M:%SZ")
    people = people_for(world, subs)
    rng = random.Random(f"history:{world['seed']}")
    final = {p.relative_to(repo).as_posix(): p.read_text() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts}
    # older versions of a few files so the history has real diffs
    older = {}
    older["deploy/config.json"] = final["deploy/config.json"].replace('"WEBHOOK_TIMEOUT_S": 30', '"WEBHOOK_TIMEOUT_S": 10')
    older["gateway/server.py"] = (final["gateway/server.py"]
                                  .replace("WEBHOOK_RETRIES = int(cfg.get(\"WEBHOOK_RETRIES\", 1))\nWEBHOOK_RETRY_BACKOFF_S = float(cfg.get(\"WEBHOOK_RETRY_BACKOFF_S\", 120))", "WEBHOOK_RETRIES = 0")
                                  .replace("def stale_watch():", "def stale_watch_unused():"))
    older["billing/nightly.py"] = final["billing/nightly.py"].replace("hours = (1440 - mins) / 60.0", "hours = (1440 - mins)")
    older["dispatch/server.py"] = final["dispatch/server.py"].replace("        wms_pallet_lookup(body.get(\"lot\"))\n", "")
    older["alerting/server.py"] = final["alerting/server.py"].replace("    if m != _routes_mtime:", "    if not _routes:")
    older["common/netutil.py"] = "import json\nimport urllib.request\n\n\ndef http_call(url, method='GET', body=None, timeout_s=10.0, headers=None):\n    data = json.dumps(body).encode() if body is not None else None\n    req = urllib.request.Request(url, data=data, method=method, headers={'Content-Type': 'application/json', **(headers or {})})\n    with urllib.request.urlopen(req, timeout=timeout_s) as r:\n        text = r.read().decode()\n    return r.status, (json.loads(text) if text else None)\n\n\ndef now_iso():\n    import time\n    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())\n"
    older["docs/runbook.md"] = final["docs/runbook.md"].split("## Inventory")[0]
    older["gateway/server.py"] = older["gateway/server.py"].replace("    threading.Thread(target=_notify_worker, daemon=True).start()\n", "")
    older["ledger/server.py"] = final["ledger/server.py"].replace('    conn.execute("PRAGMA journal_mode=WAL")\n', "")
    older["ledger/schema.sql"] = "\n".join(l for l in final["ledger/schema.sql"].splitlines() if "probe_checks" not in l and "audit" not in l and "operator TEXT NOT NULL," not in l and "id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT" not in l and "latest_readings" not in l and "zone TEXT PRIMARY KEY, recv" not in l) + "\n"
    for k, v in older.items():
        assert v != final[k], f"older variant identical for {k}"
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "coldchain-bot")
    _git(repo, "config", "user.email", f"bot@{subs['DOMAIN']}")
    written = set()
    for days_before, who, msg, files in PRE_COMMITS:
        when = start - dt.timedelta(days=days_before, hours=rng.randrange(0, 9), minutes=rng.randrange(0, 60))
        # the 9-day-old runbook commit writes the final runbook; earlier ones write older versions
        for f in files:
            paths = [k for k in final if k == f or k.startswith(f.rstrip("/") + "/")]
            for k in paths:
                is_latest_touch = not any(f2 == f or k.startswith(f2.rstrip("/") + "/") or f2 == k
                                          for (_d, _w, _m, fs) in PRE_COMMITS if _d < days_before for f2 in fs)
                body = final[k] if is_latest_touch or k not in older else older[k]
                (repo / k).parent.mkdir(parents=True, exist_ok=True)
                (repo / k).write_text(body)
                written.add(k)
        name, email = people[who]
        env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
               "GIT_AUTHOR_DATE": when.strftime("%Y-%m-%dT%H:%M:%S+0000"), "GIT_COMMITTER_DATE": when.strftime("%Y-%m-%dT%H:%M:%S+0000")}
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", render_text(msg, subs), "--allow-empty", env=env)
    # anything not covered by the commit plan goes in with the last commit's author as a follow-up
    for k, body in final.items():
        if k not in written:
            (repo / k).write_text(body)
    _git(repo, "add", "-A")
    st = _git(repo, "status", "--porcelain").stdout.strip()
    if st:
        when = start - dt.timedelta(days=5, hours=3)
        name, email = people["ops"]
        env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
               "GIT_AUTHOR_DATE": when.strftime("%Y-%m-%dT%H:%M:%S+0000"), "GIT_COMMITTER_DATE": when.strftime("%Y-%m-%dT%H:%M:%S+0000")}
        _git(repo, "commit", "-q", "-m", "housekeeping: sync deploy scripts and docs", env=env)
    # the decoy is prepared here: billing still has the pre-fix line at go-live; the in-window commit fixes it
    (repo / "billing" / "nightly.py").write_text(older["billing/nightly.py"])
    _git(repo, "add", "-A")
    when = start - dt.timedelta(days=3, hours=1)
    name, email = people["sre"]
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
           "GIT_AUTHOR_DATE": when.strftime("%Y-%m-%dT%H:%M:%S+0000"), "GIT_COMMITTER_DATE": when.strftime("%Y-%m-%dT%H:%M:%S+0000")}
    _git(repo, "commit", "-q", "-m", "billing: rollup timing tweak", env=env)
    return people


def subs_for(world: dict) -> dict:
    names = world["names"]
    domain = names["company"].split()[0].lower() + "-cold.example"
    return {"COMPANY": names["company"], "SITE": names["site_code"], "VENDOR": names["vendor_model"], "DOMAIN": domain}


def people_for(world: dict, subs: dict) -> dict:
    actors = world["actors"]
    former_first, former_last = "Dana", "Whitcombe"
    return {
        "former": (f"{former_first} {former_last}", f"{former_first[0].lower()}.{former_last.lower()}@{subs['DOMAIN']}"),
        "ops": (actors["ops_engineer"]["name"], f"{actors['ops_engineer']['handle']}@{subs['DOMAIN']}"),
        "sre": (actors["sre_oncall"]["name"], f"{actors['sre_oncall']['handle']}@{subs['DOMAIN']}"),
        "manager": (actors["warehouse_manager"]["name"], f"{actors['warehouse_manager']['handle']}@{subs['DOMAIN']}"),
    }


def info_for(build: Path, world: dict) -> dict:
    subs = subs_for(world)
    log = _git(build / "repo", "log", "--format=%h %ad %an %s", "--date=short", check=False).stdout
    return {"subs": subs, "people": people_for(world, subs), "git_log": log}


def materialise(build: Path, world: dict, notation) -> dict:
    repo = build / "repo"
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    subs = subs_for(world)
    write_tree(repo, world, notation, subs)
    people = make_history(repo, world, subs)
    # inventory export + zones json used by seed_inventory.py (committed with the housekeeping commit already? no: written now, untracked until the driver imports them)
    inv = build / "inventory_import.csv"
    with open(inv, "w") as f:
        f.write("lot_id,product,pallet_id,zone,qty\n")
        for l in world["lots_initial"]:
            f.write(f"{l['lot_id']},{l['product']},{l['pallet_id']},{l['zone']},{l['qty']}\n")
    zj = {z: {"ctrl_id": world["zones"]["controller"][z], "setpoint": world["zones"]["setpoint"][z],
              "panel": world["zones"]["panel"][z], "kind": world["zones"]["kind"][z]} for z in world["zones"]["order"]}
    (build / "zones.json").write_text(json.dumps(zj, indent=1))
    log = _git(repo, "log", "--format=%h %ad %an %s", "--date=short").stdout
    return {"subs": subs, "people": people, "git_log": log}
