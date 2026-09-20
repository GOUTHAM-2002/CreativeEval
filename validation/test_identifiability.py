import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from grader import oracle_solver  # noqa: E402

INSTANCES = sorted(p for p in (ROOT / "instances").glob("s*_*") if (p / "truth.json").exists())
CRITICAL = ["defrost.R_hours", "defrost.len_min", "trip.d_min", "lockout.N", "lockout.L_min", "lockout.W_min"]


@pytest.mark.parametrize("inst", INSTANCES, ids=[p.name for p in INSTANCES])
def test_oracle_recovers_mechanism(inst):
    if (inst / "ORACLE_PARTIAL.md").exists():
        pytest.xfail("oracle known partial on this instance: see ORACLE_PARTIAL.md")
    truth = json.load(open(inst / "truth.json"))
    rep = oracle_solver.estimate(inst / "evidence", truth)
    frac = rep["within_tol"] / rep["n"]
    bad = [f for f in rep["failures"] if f[0] in CRITICAL]
    assert not bad, bad
    assert frac >= 0.85, (frac, rep["failures"])


@pytest.mark.parametrize("inst", INSTANCES, ids=[p.name for p in INSTANCES])
def test_unknown_roots_attested(inst):
    truth = json.load(open(inst / "truth.json"))
    ev = inst / "evidence"
    text = (ev / "deploy" / "logs" / "gateway.log").read_text(errors="replace")
    snap = "".join(p.read_text() for p in (ev / "controller").glob("*.txt"))
    proto = truth.get("protocol") or {}
    if "types" in proto:
        known = {k.split(":")[1] for k in proto.get("known", []) if k.startswith("type:")} | set(proto.get("unscored_types", []))
        for code, label in proto["types"].items():
            if code in known:
                continue
            pat = f",{code.upper()},"
            n = text.count(pat) + snap.count(pat) + text.count(pat.lower()) + snap.count(pat.lower())
            assert n >= 2, (code, label, n)
        return
    for root, label in truth["notation"]["glossary"].items():
        if root in truth["notation"]["known_roots"] or label.startswith("DIGIT") or root in truth["notation"].get("unscored_roots", []):
            continue
        n = text.count(root) + snap.count(root)
        assert n >= 2, (root, label, n)
    assert len(truth["notation"].get("unscored_roots", [])) <= 8
    for h in truth["notation"]["heldout"]:
        assert h["seq"] is not None


@pytest.mark.parametrize("inst", INSTANCES, ids=[p.name for p in INSTANCES])
def test_lots_wrong_present(inst):
    truth = json.load(open(inst / "truth.json"))
    assert len(truth["build"]["lots_wrong"]) >= 3, truth["build"]["lots_wrong"]
    assert len(truth["causal"]["affected_lots"]) >= 3
