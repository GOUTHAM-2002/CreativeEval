import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gen import leakcheck  # noqa: E402

INSTANCES = sorted(p for p in (ROOT / "instances").glob("s*_*") if (p / "truth.json").exists())


@pytest.mark.parametrize("inst", INSTANCES, ids=[p.name for p in INSTANCES])
def test_instance_has_no_leaks(inst):
    truth = json.load(open(inst / "truth.json"))
    problems = leakcheck.scan(inst / "evidence", truth)
    assert problems == [], problems
    assert oct(os.stat(inst / "truth.json").st_mode & 0o777) == "0o600"
    ev = inst / "evidence"
    for fact, files in truth["evidence_index"].items():
        assert len(files) >= 2, (fact, files)
        for f in files:
            assert (ev / f).exists(), (fact, f)


def test_at_least_one_instance_built():
    assert INSTANCES, "build an instance first: .venv/bin/python -m gen.assemble --seed 1"
