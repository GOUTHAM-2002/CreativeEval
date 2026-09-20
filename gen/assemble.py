# Build one instance: seed -> world/sim -> repo -> replay in the build sandbox -> collect -> docs -> truth -> evidence/.
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

from gen import seed as seedmod
from gen import repo_gen

ROOT = Path(__file__).resolve().parent.parent
FAKETIME_LIB = ROOT / "tools" / "faketime" / "lib" / "libfaketimeMT.so.1"
SPEED = int(os.environ.get("EVAL_IMP_SPEED", "2000"))
WIRE = os.environ.get("EVAL_IMP_WIRE", "protocol")      # "protocol" (v2 hex telemetry) or "notation" (v1 language)


def make_wire(world):
    rng = random.Random(f"notation:{world['seed']}:{world['tier']}")
    if WIRE == "protocol":
        from gen.protocol import Protocol
        return Protocol(rng, zones=world["zones"]["order"], controllers=world["zones"]["controller"])
    from gen.notation import Notation
    return Notation(rng, zones=world["zones"]["order"], controllers=world["zones"]["controller"])
FAULT_BUFFER_LEN = 45


def sim_start_dt(world):
    return dt.datetime.strptime(world["sim"]["start_iso"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def prepare_replay(build: Path, world: dict, sim: dict, nt: Notation, info: dict):
    rng = random.Random(f"replay:{world['seed']}:{world['tier']}")
    zones = world["zones"]["order"]
    inc = world["zones"]["incident_zone"]
    start = sim_start_dt(world)
    # frames
    with open(build / "frames.jsonl", "w") as f:
        for fr in sim["frames"]:
            encoded = nt.encode(fr, fr["setpoint"])
            c0 = fr["clauses"][0]
            periodic = c0["kind"] == "READ"
            base_sec = fr["t_min"] * 60 + (rng.randrange(0, 25) if periodic else rng.randrange(0, 8))
            for k, line in enumerate(encoded.split("\n")):
                rec = {"t_sec": base_sec + k, "zone": fr["zone"], "seq": fr["seq"], "line": line, "droppable": periodic,
                       "event": c0.get("event") if c0["kind"] == "EVENT" else None}
                f.write(json.dumps(rec) + "\n")
    # schedule
    sched = []
    offs = world["distortion"]["clock_offsets_min"]
    for mv in world["ledger"]["moves"]:
        sched.append({"kind": "move", "t_sec": mv["t_sec"], "lot": mv["lot"], "from": mv["from"], "to": mv["to"],
                      "actor": mv["actor"], "forklift": mv["forklift"], "pallet": mv["pallet"]})
    for pc in world["ledger"]["probe_checks"]:
        t = pc["t"]
        reading = round(sim["T_true"][pc["zone"]][t] + pc["hh_bias"] + rng.gauss(0, 0.15), 1)
        pc["reading"] = reading
        sched.append({"kind": "probe", "t_sec": t * 60 + rng.randrange(30, 600), "zone": pc["zone"], "handheld": pc["handheld"],
                      "actor": pc["actor"], "reading": reading, "taken_at": seedmod.world_iso(world, t + offs["probe"])})
    for d in world["ledger"]["props"]:
        sched.append({"kind": "link_down", "t_sec": d["t0"] * 60 + rng.randrange(20, 90), "zone": inc, "why": "peer reset"})
        sched.append({"kind": "link_up", "t_sec": d["t1"] * 60 + rng.randrange(30, 120), "zone": inc})
    people = info["people"]
    plan = world["plan"]
    flashed = [e["zone"] for e in world["ledger"]["firmware_flash"]]
    routes = json.loads((build / "repo" / "alerting" / "routes.json").read_text())
    for z in flashed:
        routes["zones"][z]["channel"] = "#alerts-coldchain-old"
    sched.append({"kind": "edit_commit", "t_sec": plan["hotfix_t"] * 60,
                  "files": {"alerting/routes.json": json.dumps(routes, indent=2) + "\n"},
                  "message": f"hotfix: silence flapping zone {'/'.join(flashed)} low-temp alerts (route to legacy channel; sensor fault confirmed by vendor)",
                  "author_name": people["ops"][0], "author_email": people["ops"][1]})
    billing_src = (build / "repo" / "billing" / "nightly.py").read_text().replace("hours = (1440 - mins)\n", "hours = (1440 - mins) / 60.0\n")
    decoy_t = (3 * 1440 + 11 * 60 + rng.randrange(0, 120)) * 60
    sched.append({"kind": "edit_commit", "t_sec": decoy_t, "files": {"billing/nightly.py": billing_src},
                  "message": "billing: fix zone-hours unit conversion (minutes were billed as hours)",
                  "author_name": people["ops"][0], "author_email": people["ops"][1]})
    for po in world["ledger"].get("power_outages", []):
        sched.append({"kind": "power_outage", "t_sec": po["t0"] * 60, "minutes": po["t1"] - po["t0"]})
    sched.append({"kind": "write_file", "t_sec": plan["override_t"] * 60, "path": "deploy/config.override.json",
                  "content": json.dumps({"ALERT_MIN_SEVERITY": "critical"}, indent=2) + "\n"})
    sched.sort(key=lambda x: x["t_sec"])
    with open(build / "schedule.jsonl", "w") as f:
        for it in sched:
            f.write(json.dumps(it) + "\n")
    inc_prop = [d for d in world["ledger"]["props"] if d.get("incident")][0]
    cfgd = {"sim_start_epoch": start.timestamp(), "sim_end_sec": world["sim"]["days"] * 86400,
            "gateway_tcp_port": 7001, "gateway_api_port": 8102, "ledger_port": 8101,
            "controllers": {z: world["zones"]["controller"][z] for z in zones},
            "fault_buffer_len": FAULT_BUFFER_LEN, "ack_deadline_s": 40, "frame_dropout": world["params"]["frame_dropout"],
            "driver_seed": f"driver:{world['seed']}:{world['tier']}", "vendor_model": world["names"]["vendor_model"],
            "snapshot": {"zone": inc, "t_sec_lo": inc_prop["t0"] * 60, "t_sec_hi": (inc_prop["t1"] + 300) * 60}}
    (build / "driver_config.json").write_text(json.dumps(cfgd, indent=1))
    return {"decoy_commit_t": decoy_t // 60, "n_sched": len(sched)}


def run_replay(build: Path, world: dict, log) -> dict:
    start = sim_start_dt(world) - dt.timedelta(minutes=40)
    shutil.copy(FAKETIME_LIB, build / "libfaketimeMT.so.1")
    shutil.copy(ROOT / "runtime" / "driver.py", build / "driver.py")
    (build / "var").mkdir(exist_ok=True)
    ft = start.strftime("@%Y-%m-%d %H:%M:%S") + f" x{SPEED}"
    argv = ["bwrap", "--unshare-user", "--unshare-net", "--unshare-pid", "--unshare-uts", "--uid", "0", "--gid", "0",
            "--cap-add", "CAP_NET_ADMIN", "--hostname", "coldchain-01",
            "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/sbin", "/sbin",
            "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64", "--ro-bind", "/etc", "/etc",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/root",
            "--bind", str(build), "/build", "--bind", str(build / "repo"), "/opt/coldchain", "--bind", str(build / "var"), "/var/lib/coldchain",
            "--die-with-parent", "--clearenv",
            "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", "--setenv", "HOME", "/root", "--setenv", "TZ", "UTC",
            "--setenv", "LANG", "C.UTF-8", "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
            "--setenv", "LD_PRELOAD", "/build/libfaketimeMT.so.1", "--setenv", "FAKETIME", ft, "--setenv", "FAKETIME_DONT_RESET", "1",
            "--setenv", "FAKETIME_NO_CACHE", "1",
            "--", "bash", "-c", "ip link set lo up && exec python3 /build/driver.py"]
    t0 = time.time()
    log(f"replay: {ft} (speed x{SPEED})")
    with open(build / "driver.out", "w") as out:
        r = subprocess.run(argv, stdout=out, stderr=subprocess.STDOUT, timeout=int(os.environ.get("EVAL_IMP_REPLAY_TIMEOUT", "3600")))
    log(f"replay finished rc={r.returncode} in {time.time() - t0:.0f}s")
    if r.returncode != 0 or not (build / "driver_report.json").exists():
        raise RuntimeError(f"replay failed rc={r.returncode}: see {build / 'driver.out'}")
    return json.loads((build / "driver_report.json").read_text())


def collect_evidence(build: Path, world: dict, ev: Path):
    if ev.exists():
        shutil.rmtree(ev)
    ev.mkdir(parents=True)
    repo_src, repo_dst = build / "repo", ev / "repo"
    shutil.copytree(repo_src, repo_dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "logs", "billing"))
    (ev / "deploy" / "logs").mkdir(parents=True)
    gap = world.get("plan", {}).get("diskfull")
    lo = seedmod.world_iso(world, gap["t0"]) if gap else None
    hi = seedmod.world_iso(world, gap["t1"]) if gap else None
    for p in (repo_src / "deploy" / "logs").glob("*.log*"):
        text = p.read_text(errors="replace")
        if gap:
            # the host's disk was full for this window: nothing could be appended to any log file
            kept = [l for l in text.splitlines(keepends=True) if not (lo <= l[:20] < hi)]
            text = "".join(kept)
        (ev / "deploy" / "logs" / p.name).write_text(text)
    if (repo_src / "deploy" / "billing").exists():
        shutil.copytree(repo_src / "deploy" / "billing", ev / "deploy" / "billing")
    (ev / "db").mkdir()
    shutil.copy(build / "ledger.sql", ev / "db" / "ledger.sql")
    shutil.copy(build / "queue.sql", ev / "db" / "queue.sql")
    (ev / "controller").mkdir()
    ctrl = world["zones"]["controller"][world["zones"]["incident_zone"]]
    if (build / "ringbuffer.txt").exists():
        shutil.copy(build / "ringbuffer.txt", ev / "controller" / f"{ctrl}_fault_snapshot.txt")
    subprocess.run(["git", "-C", str(repo_dst), "gc", "-q", "--prune=now"], check=False, capture_output=True)


def normalise_tree(ev: Path):
    epoch = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp()
    for p in sorted(ev.rglob("*")):
        try:
            os.utime(p, (epoch, epoch), follow_symlinks=False)
        except OSError:
            pass
        if p.is_file():
            p.chmod(0o644 if not os.access(p, os.X_OK) else 0o755)
        elif p.is_dir():
            p.chmod(0o755)
    os.utime(ev, (epoch, epoch))


def build_instance(seed: int, tier: str, out_root: Path, stop_after: str | None = None, resume: bool = False) -> Path:
    t_all = time.time()
    tmp = out_root / f"_build_s{seed:04d}_{tier}"
    if resume and (tmp / "driver_report.json").exists() and (tmp / "world.json").exists():
        logf = open(tmp / "build.log", "a")

        def log(msg):
            line = f"{time.strftime('%H:%M:%S')} {msg}"
            print(line, flush=True); logf.write(line + "\n"); logf.flush()

        world = json.load(open(tmp / "world.json"))
        sim = seedmod.run_sim(world)
        nt = make_wire(world)
        info = repo_gen.info_for(tmp, world)
        report = json.loads((tmp / "driver_report.json").read_text())
        log("resume: world/sim/notation/info reloaded")
        ev = tmp / "evidence"
        collect_evidence(tmp, world, ev)
        return finish_instance(seed, tmp, world, sim, nt, info, report, ev, out_root, log, logf, t_all)
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    logf = open(tmp / "build.log", "a")

    def log(msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True); logf.write(line + "\n"); logf.flush()

    world, sim, k = seedmod.find_world(seed, tier)
    log(f"world found (sub_seed={k}) incident_zone={world['zones']['incident_zone']} frames={len(sim['frames'])} checks={ {k2: v for k2, v in sim['checks'].items() if k2 in ('n_lockouts','n_near_misses','n_collisions','incident_window')} }")
    nt = make_wire(world)
    info = repo_gen.materialise(tmp, world, nt)
    log("repo materialised")
    prep = prepare_replay(tmp, world, sim, nt, info)
    world["plan"]["decoy_commit_t"] = prep["decoy_commit_t"]
    json.dump(world, open(tmp / "world.json", "w"), indent=1)
    json.dump({k2: v for k2, v in sim.items() if k2 in ("events", "collisions", "lockouts", "trips", "checks", "clock_epochs")}, open(tmp / "sim_events.json", "w"), indent=1)
    with open(tmp / "sim_series.csv", "w") as f:
        zones = world["zones"]["order"]
        f.write("t_min," + ",".join(f"T_true_{z},T_rep_{z},state_{z},comp_{z},heat_{z},door_{z}" for z in zones) + "\n")
        for t in range(len(sim["T_true"][zones[0]])):
            f.write(str(t) + "," + ",".join(f"{sim['T_true'][z][t]:.3f},{sim['T_rep'][z][t]:.2f},{sim['state'][z][t]},{sim['comp'][z][t]},{sim['heat'][z][t]},{sim['door_open'][z][t]}" for z in zones) + "\n")
    if stop_after == "prepare":
        return tmp
    report = run_replay(tmp, world, log)
    log(f"driver report: sent={report['sent']} unacked={report['unacked']} dropped={report['dropped_radio']} linkdown={report['unsent_linkdown']} late_max={report['late_max_s']}s moves={report['moves_posted']} probes={report['probes_posted']} commits={len(report['commits'])} snapshot={report['snapshot']} errors={len(report['errors'])}")
    ev = tmp / "evidence"
    collect_evidence(tmp, world, ev)
    log("evidence collected")
    if stop_after == "driver":
        return tmp
    return finish_instance(seed, tmp, world, sim, nt, info, report, ev, out_root, log, logf, t_all)


def finish_instance(seed, tmp, world, sim, nt, info, report, ev, out_root, log, logf, t_all):
    from gen import docs_gen2, truth as truthmod, leakcheck
    meta = docs_gen2.render(tmp, world, sim, nt, info, report, ev, log)
    if os.environ.get("EVAL_IMP_LLM_DOCS", "1") == "1":
        try:
            from gen import docs_llm
            res = docs_llm.render_all(tmp / "fact_sheets", ev, tmp / "docs_llm_log.jsonl")
            log(f"docs_llm: {res}")
            spans = res.get("spans") or {}
            for fc in meta["false_claims"]:
                if fc["claim_id"] in spans:
                    fc["span"] = spans[fc["claim_id"]]
                else:
                    body = (ev / fc["path"]).read_text() if (ev / fc["path"]).exists() else ""
                    i = body.find(fc["text"])
                    fc["span"] = [i, i + len(fc["text"])] if i >= 0 else [0, 0]
            json.dump(meta, open(tmp / "docs_meta.json", "w"), indent=1)
        except ImportError:
            log("docs_llm not available: template fallbacks kept")
        except Exception as e:  # noqa: BLE001
            log(f"docs_llm failed ({e}): template fallbacks kept")
    truth = truthmod.build_v2(tmp, world, sim, nt, info, report, ev, log)
    import jsonschema
    schema = json.loads((ROOT / "contract" / "truth_schema_v2.json").read_text())
    errs = list(jsonschema.Draft202012Validator(schema).iter_errors(truth))
    if errs:
        log(f"TRUTH SCHEMA ERRORS: {[(list(e.path)[:4], e.message[:100]) for e in errs[:5]]}")
        raise RuntimeError("truth does not match contract/truth_schema_v2.json")
    shutil.copy(ROOT / "contract" / "answer_schema_v2.template.json", ev / "ANSWER_SCHEMA.json")
    normalise_tree(ev)
    problems = leakcheck.scan(ev, truth)
    if problems:
        log(f"LEAKCHECK FAILED: {problems[:10]}")
        raise RuntimeError("leakcheck failed")
    from gen.gitbundle import bundle_repo
    bundle_repo(ev)
    h = hashlib.sha256()
    for p in sorted(ev.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(ev).as_posix().encode()); h.update(p.read_bytes())
    inst_id = f"s{seed:04d}_{h.hexdigest()[:8]}"
    truth["instance"] = inst_id
    q = json.loads((ev / "questions.json").read_text()); q["instance"] = inst_id
    (ev / "questions.json").write_text(json.dumps(q, indent=1) + "\n")
    normalise_tree(ev)
    final = out_root / inst_id
    if final.exists():
        shutil.rmtree(final)
    final.mkdir()
    shutil.move(str(ev), str(final / "evidence"))
    json.dump(truth, open(final / "truth.json", "w"), indent=1)
    shutil.copy(tmp / "world.json", final / "world.json")
    shutil.copy(tmp / "build.log", final / "build.log")
    for name in ("driver_report.json", "sim_events.json", "sim_series.csv"):
        shutil.copy(tmp / name, final / name)
    os.chmod(final / "truth.json", 0o600)
    log(f"instance {inst_id} built in {time.time() - t_all:.0f}s")
    logf.close()
    shutil.copy(tmp / "build.log", final / "build.log")
    if os.environ.get("EVAL_IMP_KEEP_BUILD") != "1":
        shutil.rmtree(tmp)
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--tier", default="default")
    ap.add_argument("--out", default=str(ROOT / "instances"))
    ap.add_argument("--stop-after", choices=["prepare", "driver"], default=None)
    ap.add_argument("--resume", action="store_true", help="finish an existing _build_* dir (skip world search and replay)")
    a = ap.parse_args()
    p = build_instance(a.seed, a.tier, Path(a.out), a.stop_after, a.resume)
    print(p)


if __name__ == "__main__":
    main()
