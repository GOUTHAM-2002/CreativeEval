#!/usr/bin/env python3
"""One episode: stage the run dir, quick containment selftest, dispatch to a route, pick the last valid-JSON
answer snapshot as answer.json, write episode.json (contract §8), then call the grader if present.

  .venv/bin/python harness/run.py --model haiku4.5 --instance instances/s0001_xxxx --tag smoke --max-tool-calls 60 --budget-usd 5
  .venv/bin/python harness/run.py --fake --instance contract/stub_instance --tag test"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from harness import prices  # noqa: E402
from harness.tools import Executor  # noqa: E402
from sandbox import exec as sbx  # noqa: E402

VENV_PY = PROJECT / ".venv" / "bin" / "python"
END_REASONS = ("stopped", "tool_cap", "wall_cap", "budget_cap", "context_limit", "content_filter", "api_error", "harness_error")


def load_dotenv(path=PROJECT / ".env") -> dict:
    out = {}
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def run_dir_for(runs_root: Path, tag: str, model_key: str, inst_id: str, tier: str) -> Path:
    return runs_root / tag / model_key / (inst_id if tier == "default" else f"{inst_id}+{tier}")


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def write_json(path: Path, obj) -> None:
    tmp = str(path) + ".tmp"
    Path(tmp).write_text(json.dumps(obj, indent=1, default=str))
    os.replace(tmp, path)


def finalize_answer(run_dir: Path, tier: str) -> dict:
    ex = Executor(run_dir, tier)
    try:
        ex.snapshot()
    except Exception:  # noqa: BLE001
        pass
    snaps = sorted(ex.hist.glob("[0-9][0-9][0-9][0-9].json"))
    chosen = None
    for s in reversed(snaps):
        try:
            json.loads(s.read_bytes())
            chosen = s
            break
        except ValueError:
            continue
    final = run_dir / "answer.json"
    if chosen:
        shutil.copyfile(chosen, final)
    elif final.exists():
        final.unlink()
    return {"n_snapshots": len(snaps), "answer_from": chosen.name if chosen else None, "answer_present": chosen is not None,
            "n_tool_calls": ex.n_calls, "n_validate_calls": ex.n_validate}


def grade(run_dir: Path, inst_dir: Path) -> dict:
    score_py = PROJECT / "grader" / "score.py"
    if not score_py.exists():
        return {"ran": False, "note": "grader/score.py not present"}
    cmd = [str(VENV_PY), "-m", "grader.score", "--run", str(run_dir), "--truth", str(inst_dir / "truth.json")]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900, cwd=str(PROJECT))
    except (subprocess.SubprocessError, OSError) as e:
        return {"ran": True, "rc": None, "note": f"grader failed to run: {e}"}
    if p.returncode != 0:
        (run_dir / "grader_stderr.txt").write_text(p.stderr[-8000:])
        return {"ran": True, "rc": p.returncode, "note": "grader exited non-zero; see grader_stderr.txt"}
    return {"ran": True, "rc": 0, "note": "ok" if (run_dir / "score.json").exists() else "grader ok but no score.json"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="key in harness/prices.py MODELS")
    ap.add_argument("--instance", required=True, help="instance dir containing evidence/ (+ host-only truth.json)")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--tier", default="default", choices=sbx.TIERS)
    ap.add_argument("--max-tool-calls", type=int, default=600)
    ap.add_argument("--wall-s", type=float, default=18000)
    ap.add_argument("--budget-usd", type=float, default=150)
    ap.add_argument("--via", default="openrouter", choices=["openrouter", "api", "subscription"])
    ap.add_argument("--effort", default=None)
    ap.add_argument("--fake", action="store_true", help="scripted zero-API agent")
    ap.add_argument("--runs-root", default=str(PROJECT / "runs"))
    ap.add_argument("--skip-selftest", action="store_true")
    ap.add_argument("--no-grade", action="store_true")
    a = ap.parse_args(argv)

    model_key = a.model or ("fake" if a.fake else None)
    if not model_key:
        ap.error("--model is required unless --fake")
    m = prices.resolve(model_key)
    route = "fake" if a.fake else m["route"]
    slug = m["slug"] if a.via != "api" or "api_id" not in m else m["api_id"]
    inst_dir = Path(a.instance).resolve()
    inst_id = inst_dir.name
    run_dir = run_dir_for(Path(a.runs_root).resolve(), a.tag, model_key, inst_id, a.tier)
    if (run_dir / "episode.json").exists():
        print(json.dumps({"skipped": True, "run_dir": str(run_dir), "reason": "episode.json exists"}))
        return 0
    started = now()
    t0 = time.time()
    store = sbx.prepare_run_dir(run_dir, inst_dir / "evidence")
    caps = {"max_tool_calls": a.max_tool_calls, "wall_s": a.wall_s, "budget_usd": a.budget_usd}
    write_json(run_dir / "run_meta.json", {"model": model_key, "model_slug": slug, "route": route, "inst_id": inst_id, "inst_dir": str(inst_dir),
                                           "tier": a.tier, "via": a.via, "effort": a.effort, "caps": caps, "started": started, "store": str(store)})
    ep = {"model": model_key, "model_slug": slug, "model_id_observed": None, "route": route, "inst_id": inst_id, "tier": a.tier,
          "end_reason": None, "end_detail": "", "n_tool_calls": 0, "n_validate_calls": 0, "wall_s": 0.0, "cost_usd": 0.0,
          "cost_source": "none", "cost_estimate_usd": 0.0, "invalid_markers": [], "started": started, "ended": None,
          "via": a.via, "effort": a.effort, "caps": caps, "store": str(store)}
    if not a.skip_selftest:
        p = subprocess.run([sys.executable, str(PROJECT / "sandbox" / "selftest.py"), "--run-dir", str(run_dir), "--tier", a.tier, "--quick"],
                           capture_output=True, text=True, timeout=600)
        (run_dir / "selftest.txt").write_text(p.stdout + p.stderr)
        if p.returncode != 0:
            ep.update(end_reason="harness_error", end_detail="sandbox selftest failed; see selftest.txt", ended=now(), wall_s=round(time.time() - t0, 1))
            write_json(run_dir / "episode.json", ep)
            print(json.dumps({"run_dir": str(run_dir), "end_reason": ep["end_reason"], "detail": ep["end_detail"]}))
            return 1
    env = load_dotenv()
    res = {}
    try:
        if route == "fake":
            from harness.fake_agent import run_fake
            res = run_fake(run_dir, a.tier, a.max_tool_calls)
        elif route == "cc":
            from harness.cc_route import run_cc
            res = run_cc(run_dir, slug, a.tier, a.max_tool_calls, a.wall_s, a.budget_usd, via=a.via, effort=a.effort,
                         or_key=env.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY"),
                         api_key=env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
        elif route == "or":
            from harness.or_route import run_or
            res = run_or(run_dir, slug, a.tier, a.max_tool_calls, a.wall_s, a.budget_usd, effort=a.effort,
                         or_key=env.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY"))
        else:
            raise RuntimeError(f"unknown route {route}")
    except Exception as exc:  # noqa: BLE001
        (run_dir / "harness_error.txt").write_text(traceback.format_exc())
        res = {"route": route, "end_reason": "harness_error", "end_detail": f"{type(exc).__name__}: {exc}"[:500],
               "invalid_markers": [{"marker": "harness_exception"}]}
    ep.update({k: v for k, v in res.items() if k not in ("route",)})
    if ep.get("end_reason") not in END_REASONS:
        ep["end_detail"] = f"unmapped end_reason {ep.get('end_reason')!r}; {ep.get('end_detail', '')}"
        ep["end_reason"] = "harness_error"
    ep.update(finalize_answer(run_dir, a.tier))
    ep["wall_s"] = round(time.time() - t0, 1)
    ep["ended"] = now()
    write_json(run_dir / "episode.json", ep)
    if not a.no_grade:
        ep["grader"] = grade(run_dir, inst_dir)
        write_json(run_dir / "episode.json", ep)
    print(json.dumps({"run_dir": str(run_dir), "end_reason": ep["end_reason"], "n_tool_calls": ep["n_tool_calls"],
                      "answer_present": ep["answer_present"], "cost_usd": ep["cost_usd"], "wall_s": ep["wall_s"],
                      "grader": (ep.get("grader") or {}).get("note")}))
    return 0 if ep["end_reason"] != "harness_error" else 1


if __name__ == "__main__":
    sys.exit(main())
