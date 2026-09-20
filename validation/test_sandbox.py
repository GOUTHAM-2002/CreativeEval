"""$0 containment tests: selftest on both tiers, host-only files unreachable, redaction, tool semantics, snapshots."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
STUB = PROJECT / "contract" / "stub_instance"
sys.path.insert(0, str(PROJECT))
from harness.tools import Executor, mcp_tool_list, openai_tool_list  # noqa: E402
from sandbox import exec as sbx  # noqa: E402

TRUTH_ONLY = ("canaries", "abs_tol", "evidence_index", '"seed"')


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("EVAL_STORE", str(tmp_path / "store"))
    rd = tmp_path / "run"
    sbx.prepare_run_dir(rd, STUB / "evidence", store_root_dir=tmp_path / "store")
    return rd


@pytest.mark.parametrize("tier", ["default", "no_compute"])
def test_selftest_passes(run_dir, tier):
    p = subprocess.run([sys.executable, str(PROJECT / "sandbox" / "selftest.py"), "--run-dir", str(run_dir), "--tier", tier],
                       capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stdout + p.stderr
    last = p.stdout.strip().splitlines()[-1]
    n, total = last.split()[0].split("/")
    assert n == total


def test_truth_unreachable_via_bash(run_dir):
    ex = Executor(run_dir, "default")
    r = ex.call("bash", {"cmd": "cat /evidence/../truth.json /work/../truth.json /evidence/../../truth.json 2>&1; "
                                "find / -name truth.json -o -name world.json -o -name tool_log.jsonl 2>/dev/null; echo done"})
    assert "done" in r["text"]
    for s in TRUTH_ONLY:
        assert s not in r["text"]
    assert "truth.json" not in r["text"].replace("cat: /evidence/../truth.json", "").replace("cat: /work/../truth.json", "").replace("cat: /evidence/../../truth.json", "")


def test_read_file_refuses_escape(run_dir):
    ex = Executor(run_dir, "default")
    for p in ("../truth.json", "/evidence/../truth.json", "/etc/passwd", "/proc/self/mountinfo"):
        r = ex.call("read_file", {"path": p})
        assert r["is_error"] and "must be under" in r["text"], (p, r)


def test_redaction_of_host_paths(run_dir):
    ex = Executor(run_dir, "default")
    home = Path.home()
    r = ex.call("bash", {"cmd": f"echo {run_dir}/work; echo {PROJECT}/gen; echo {home}/.ssh; cat /proc/self/mountinfo"})
    assert str(run_dir) not in r["text"]
    assert str(PROJECT) not in r["text"]
    assert str(home) not in r["text"]
    assert "[run]/work" in r["text"] and "[project]/gen" in r["text"]


def test_tools_and_schemas(run_dir):
    assert [t["name"] for t in mcp_tool_list()] == [t["function"]["name"] for t in openai_tool_list()] == ["read_file", "grep", "bash", "validate_answer"]
    ex = Executor(run_dir, "default")
    r = ex.call("read_file", {"path": "TASK.md", "start_line": 1, "end_line": 2})
    assert not r["is_error"] and r["text"].startswith("1\t# Incident") and "\n3\t" not in r["text"]
    r = ex.call("grep", {"pattern": "validate_answer", "path": "/evidence", "flags": "-l"})
    assert "/evidence/TASK.md" in r["text"]
    r = ex.call("grep", {"pattern": "x", "flags": "-f /etc/passwd; id"})
    assert r["is_error"] and "unsupported" in r["text"]
    r = ex.call("bash", {"cmd": "pwd; id -u; python3 -c 'print(6*7)'"})
    assert "exit=0" in r["text"] and "/work" in r["text"] and "1000" in r["text"] and "42" in r["text"]
    r = ex.call("bash", {"cmd": "sleep 30", "timeout_s": 2})
    assert "exit=124" in r["text"]
    log = [json.loads(l) for l in (run_dir / "tool_log.jsonl").read_text().splitlines()]
    assert [x["tool"] for x in log][:5] == ["read_file", "grep", "grep", "bash", "bash"]


def test_snapshots_and_validate(run_dir):
    ex = Executor(run_dir, "default")
    assert ex.call("validate_answer", {})["text"].startswith('{"schema_valid": false')
    ex.call("bash", {"cmd": "printf '{bad' > /work/answer.json"})
    ex.call("bash", {"cmd": "printf '{bad' > /work/answer.json"})
    ex.call("bash", {"cmd": "printf '{\"schema_version\": \"1\"}' > /work/answer.json"})
    names = sorted(p.name for p in (run_dir / "answer_history").glob("*.json"))
    assert names == ["0001.json", "0002.json"]
    res = json.loads(ex.call("validate_answer", {})["text"])
    assert res["schema_valid"] is False and any("mechanism" in e for e in res["errors"])
    ex.call("bash", {"cmd": "rm /work/answer.json; ln -s /evidence/questions.json /work/answer.json"})
    res = json.loads(ex.call("validate_answer", {})["text"])
    assert res["schema_valid"] is False and "not found" in res["errors"][0]
    assert sorted(p.name for p in (run_dir / "answer_history").glob("*.json")) == names
    snaps = [json.loads(l) for l in (run_dir / "tool_log.jsonl").read_text().splitlines() if '"snapshot"' in l]
    assert len(snaps) == 2 and snaps[0]["args"]["valid_json"] is False and snaps[1]["args"]["valid_json"] is True
    assert ex.n_validate == 3


def test_no_compute_hides_interpreters(run_dir):
    ex = Executor(run_dir, "no_compute")
    r = ex.call("bash", {"cmd": "python3 -c 1; perl -e 1; ruby -e 1; node -e 1; echo shell-ok; grep -c . /evidence/TASK.md"})
    assert "shell-ok" in r["text"] and "command not found" in r["text"]
    assert r["text"].count("command not found") == 4
