import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gen import seed as seedmod  # noqa: E402
from gen.notation import Notation  # noqa: E402


def _world_and_frames(seed):
    w, s, k = seedmod.find_world(seed, "default", max_tries=12)
    nt = Notation(random.Random(f"notation:{w['seed']}:{w['tier']}"), zones=w["zones"]["order"], controllers=w["zones"]["controller"])
    lines = [nt.encode(f, f["setpoint"]) for f in s["frames"][:3000]]
    return w, s, lines


def test_same_seed_same_world_and_frames():
    w1, s1, l1 = _world_and_frames(1)
    w2, s2, l2 = _world_and_frames(1)
    assert json.dumps(w1, sort_keys=True) == json.dumps(w2, sort_keys=True)
    assert l1 == l2
    assert s1["checks"] == s2["checks"]


def test_different_seeds_differ():
    w1, s1, l1 = _world_and_frames(1)
    w2, s2, l2 = _world_and_frames(2)
    assert w1["params"] != w2["params"]
    assert w1["names"]["actors"] != w2["names"]["actors"]
    toks1 = {t for line in l1 for t in line.split()}
    toks2 = {t for line in l2 for t in line.split()}
    jacc = len(toks1 & toks2) / max(1, len(toks1 | toks2))
    assert jacc < 0.5, jacc
