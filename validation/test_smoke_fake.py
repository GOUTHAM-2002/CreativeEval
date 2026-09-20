"""$0 end-to-end: run.py --fake on the stub instance produces a complete, schema-valid run directory."""
import json
import subprocess
import sys
from pathlib import Path

import jsonschema

PROJECT = Path(__file__).resolve().parents[1]
STUB = PROJECT / "contract" / "stub_instance"


def test_fake_episode_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("EVAL_STORE", str(tmp_path / "store"))
    runs = tmp_path / "runs"
    cmd = [sys.executable, str(PROJECT / "harness" / "run.py"), "--fake", "--instance", str(STUB), "--tag", "t", "--runs-root", str(runs)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(PROJECT))
    assert p.returncode == 0, p.stdout + p.stderr
    run_dir = runs / "t" / "fake" / "stub_instance"
    ep = json.loads((run_dir / "episode.json").read_text())
    for k in ("model", "model_id_observed", "route", "inst_id", "tier", "end_reason", "n_tool_calls", "n_validate_calls",
              "wall_s", "cost_usd", "cost_source", "invalid_markers", "started", "ended"):
        assert k in ep, k
    assert ep["end_reason"] == "stopped" and ep["route"] == "fake" and ep["inst_id"] == "stub_instance"
    assert ep["n_tool_calls"] == 7 and ep["n_validate_calls"] == 2 and ep["invalid_markers"] == []
    log = [json.loads(l) for l in (run_dir / "tool_log.jsonl").read_text().splitlines()]
    assert [r["tool"] for r in log if r["tool"] != "snapshot"] == ["read_file", "grep", "bash", "bash", "validate_answer", "bash", "validate_answer"]
    snaps = sorted((run_dir / "answer_history").glob("*.json"))
    assert len(snaps) >= 1 and ep["n_snapshots"] == len(snaps) == 2
    schema = json.loads((STUB / "evidence" / "ANSWER_SCHEMA.json").read_text())
    answer = json.loads((run_dir / "answer.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(answer)
    assert ep["answer_present"] and ep["answer_from"] == "0002.json"
    rows = [json.loads(l) for l in (run_dir / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["role"] == "user" and any(r["role"] == "tool" for r in rows) and all("i" in r and "t" in r for r in rows)
    assert (run_dir / "usage.jsonl").exists() and (run_dir / "selftest.txt").read_text().rstrip().endswith("passed (tier=default, quick)")
    # second invocation is a no-op skip
    p2 = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(PROJECT))
    assert p2.returncode == 0 and '"skipped": true' in p2.stdout
