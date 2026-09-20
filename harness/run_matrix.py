#!/usr/bin/env python3
"""Matrix runner: instances x tiers x models, instance-major round robin, N parallel, flock'd ledger with a hard
tag cap, skip cells with episode.json, --retry-errors re-runs api_error/harness_error cells from scratch.

  .venv/bin/python harness/run_matrix.py --tag pilot --models fable5.1,astra --instances 'instances/s000*' --par 4 --cap-usd 600"""
from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from harness import prices  # noqa: E402
from harness.ledger import Ledger  # noqa: E402
from harness.run import run_dir_for  # noqa: E402

RETRYABLE = ("api_error", "harness_error")


def expand_instances(spec: str) -> list[Path]:
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        hits = sorted(glob.glob(part)) or [part]
        for h in hits:
            p = Path(h).resolve()
            if (p / "evidence" / "TASK.md").exists():
                out.append(p)
    if not out:
        raise SystemExit(f"no instance dirs with evidence/TASK.md in {spec!r}")
    return out


def run_cell(a, runs_root: Path, ledger: Ledger, inst: Path, tier: str, model: str) -> dict:
    run_dir = run_dir_for(runs_root, a.tag, model, inst.name, tier)
    cell = f"{model}/{run_dir.name}"
    ep_path = run_dir / "episode.json"
    base = {"cell": cell, "model": model, "inst": inst.name, "tier": tier}
    if ep_path.exists():
        rec = json.loads(ep_path.read_text())
        if not (a.retry_errors and rec.get("end_reason") in RETRYABLE):
            return {**base, "skipped": "done", "end_reason": rec.get("end_reason"), "cost": 0.0}
        n = 1
        while (run_dir.parent / f"{run_dir.name}.failed{n}").exists():
            n += 1
        run_dir.rename(run_dir.parent / f"{run_dir.name}.failed{n}")
    if not ledger.reserve(cell, 0.0 if a.fake else a.budget_usd):
        return {**base, "skipped": "cap", "cost": 0.0}
    cmd = [sys.executable, str(PROJECT / "harness" / "run.py"), "--model", model, "--instance", str(inst), "--tag", a.tag, "--tier", tier,
           "--max-tool-calls", str(a.max_tool_calls), "--wall-s", str(a.wall_s), "--budget-usd", str(a.budget_usd), "--via", a.via,
           "--runs-root", str(runs_root)]
    if a.effort:
        cmd += ["--effort", a.effort]
    if a.fake:
        cmd.append("--fake")
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT))
    rec = json.loads(ep_path.read_text()) if ep_path.exists() else {"end_reason": "harness_error", "end_detail": f"no episode.json rc={p.returncode}: {p.stderr[-500:]}"}
    cost = max(float(rec.get("cost_usd") or 0.0), float(rec.get("cost_estimate_usd") or 0.0))
    ledger.settle(cell, cost, rec.get("end_reason") or "")
    return {**base, "end_reason": rec.get("end_reason"), "detail": (rec.get("end_detail") or "")[:120], "cost": round(cost, 4),
            "n_tool_calls": rec.get("n_tool_calls"), "answer": rec.get("answer_present"), "wall_s": round(time.time() - t0)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--models", required=True, help="comma-separated keys from harness/prices.py")
    ap.add_argument("--instances", required=True, help="comma-separated instance dirs or globs")
    ap.add_argument("--tiers", default="default")
    ap.add_argument("--par", type=int, default=2)
    ap.add_argument("--cap-usd", type=float, default=500.0, help="hard cap for this tag (ledger)")
    ap.add_argument("--retry-errors", action="store_true")
    ap.add_argument("--max-tool-calls", type=int, default=600)
    ap.add_argument("--wall-s", type=float, default=18000)
    ap.add_argument("--budget-usd", type=float, default=150.0, help="per-episode backstop, reserved in the ledger before launch")
    ap.add_argument("--via", default="openrouter", choices=["openrouter", "api", "subscription"])
    ap.add_argument("--effort", default=None)
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--runs-root", default=str(PROJECT / "runs"))
    a = ap.parse_args(argv)

    models = [m.strip() for m in a.models.split(",") if m.strip()]
    for m in models:
        prices.resolve(m)
    tiers = [t.strip() for t in a.tiers.split(",") if t.strip()]
    instances = expand_instances(a.instances)
    runs_root = Path(a.runs_root).resolve()
    root = runs_root / a.tag
    root.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(root / "ledger.json", a.cap_usd)
    (root / "matrix_args.json").write_text(json.dumps({**vars(a), "instances_resolved": [str(i) for i in instances], "started": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=1))
    cells = [(inst, tier, model) for inst in instances for tier in tiers for model in models]
    print(f"{len(cells)} cells, par={a.par}, cap=${a.cap_usd:.2f}, ledger={ledger.snapshot()}", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=max(1, a.par)) as pool:
        futs = [pool.submit(run_cell, a, runs_root, ledger, *c) for c in cells]
        for fut in as_completed(futs):
            try:
                r = fut.result()
            except Exception as exc:  # noqa: BLE001
                r = {"cell": "?", "model": "?", "end_reason": "harness_error", "detail": repr(exc)[:200], "cost": 0.0}
            results.append(r)
            print(time.strftime("%H:%M:%S"), json.dumps(r, default=str), f"| spent ${ledger.snapshot()['spent_usd']:.2f}", flush=True)
    by_model = defaultdict(list)
    for r in results:
        by_model[r.get("model")].append(r)
    print("\nmodel        n   cost_usd  end_reason counts (skipped: done/cap)")
    for m in sorted(by_model):
        rs = by_model[m]
        ran = [r for r in rs if not r.get("skipped")]
        ends = Counter(r.get("end_reason") for r in ran)
        skipped = Counter(r.get("skipped") for r in rs if r.get("skipped"))
        print(f"{m:<12} {len(ran):>2}  {sum(r['cost'] for r in ran):>9.2f}  {dict(ends)}  skipped={dict(skipped)}")
    print("ledger:", json.dumps(ledger.snapshot()))


if __name__ == "__main__":
    main()
