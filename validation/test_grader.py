"""Grader tests against contract/stub_instance."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from grader import null_baseline, validate as validate_mod  # noqa: E402
from grader import score as score_mod  # noqa: E402
from grader.sections import calibration  # noqa: E402
from grader.truth_to_answer import convert  # noqa: E402

STUB = ROOT / "contract" / "stub_instance"
TRUTH_PATH = STUB / "truth.json"
EVID = STUB / "evidence"
TRUTH = score_mod.load_truth(TRUTH_PATH)
CFG = score_mod.load_config()
SECTIONS = score_mod.SECTIONS


def grade(ans, status="ok"):
    return score_mod.grade(TRUTH, ans, EVID, CFG, status)


def perfect():
    return convert(TRUTH)


def test_perfect_answer_scores_one():
    sc = grade(perfect())
    assert sc["submission_status"] == "ok"
    for s in SECTIONS:
        assert sc["section_status"][s] == "ok"
        assert sc["measured"]["sections"][s]["score"] == pytest.approx(1.0)
        assert sc["measured"]["solved"][s] is True
    assert sc["measured"]["aggregate"] == pytest.approx(1.0)
    assert sc["measured"]["solved_all"] is True
    assert sc["measured"]["calibration"]["brier"] == 0.0
    assert sc["authored"]["tolerance_source"] == "truth.json"
    ok, errs = validate_mod.validate(perfect(), validate_mod.load_schema())
    assert ok, errs


def test_missing_answer_file(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    assert score_mod.main(["--run", str(run), "--truth", str(TRUTH_PATH)]) == 0
    sc = json.loads((run / "score.json").read_text())
    assert sc["submission_status"] == "missing"
    assert sc["measured"]["aggregate"] == 0.0
    assert all(v == "missing" for v in sc["section_status"].values())
    assert all(sc["measured"]["sections"][s]["score"] == 0.0 for s in SECTIONS)
    assert sc["measured"]["calibration"]["brier"] is None
    (run / "answer.json").write_text("{not json")
    score_mod.main(["--run", str(run), "--truth", str(TRUTH_PATH)])
    assert json.loads((run / "score.json").read_text())["submission_status"] == "invalid_json"


def test_empty_valid_scores_zero():
    sc = grade(null_baseline.empty_valid())
    for s in SECTIONS:
        assert sc["section_status"][s] == "ok"
        assert sc["measured"]["sections"][s]["score"] == 0.0
        assert sc["measured"]["solved"][s] is False
    assert sc["measured"]["aggregate"] == 0.0
    assert sc["measured"]["calibration"]["brier"] == pytest.approx(0.25)


def test_params_half_credit():
    ans = perfect()
    n_pos = 0
    for pid, spec in TRUTH["mechanism"]["params"].items():
        tol = max(spec["abs_tol"], spec["rel_tol"] * abs(spec["value"]))
        n_pos += tol > 0
        ans["mechanism"]["parameters"][pid] = spec["value"] + 1.5 * tol
    res = grade(ans)["measured"]["sections"]["mechanism"]
    assert res["params_half"] == n_pos
    assert res["params_hits"] == res["n_params"] - n_pos
    for p in res["params"].values():
        assert p["pts"] == (CFG["half_credit_pts"] if p["tol"] > 0 else 1.0)
    n = res["n_params"]
    assert res["score"] == pytest.approx((0.5 * n_pos + (n - n_pos) + 3) / (n + 3))
    assert res["rules_all_correct"] is True


def test_causal_decoys_as_nodes():
    ans = perfect()
    ans["causal_chain"]["nodes"] += TRUTH["causal"]["decoys"]
    res = grade(ans)["measured"]["sections"]["causal_chain"]
    assert res["decoys_included"] == res["n_decoys"] == len(TRUTH["causal"]["decoys"])
    assert set(res["decoys_included_list"]) == {d.lower() for d in TRUTH["causal"]["decoys"]}
    assert res["nodes"]["recall"] == 1.0
    assert res["nodes"]["precision"] < 1.0
    assert res["nodes"]["f1"] < 1.0
    assert res["score"] < 1.0
    assert res["decoys_rejected_hits"] == res["n_decoys"]


def test_timeline_actor_swap():
    ans = perfect()
    ev = ans["timeline"]["events"]
    actors = [e["actor"] for e in ev]
    assert len(set(actors)) == len(actors)
    for e, a in zip(ev, actors[1:] + actors[:1]):
        e["actor"] = a
    res = grade(ans)["measured"]["sections"]["timeline"]["events"]
    assert res["matched"] == 0
    assert res["recall"] == 0.0
    assert res["precision"] == 0.0
    assert res["wrong_actor"] == res["n_truth"] == len(ev)


def test_false_claim_quote_matching():
    ans = perfect()
    ans["timeline"]["false_claims"] = [{"doc_id": "doc:night_lead", "quote": "nobody opened it aga"}]
    cl = grade(ans)["measured"]["sections"]["timeline"]["claims"]
    assert cl["hits"] == 1 and cl["n_truth"] == 2 and cl["recall"] == 0.5
    assert [c["hit"] for c in cl["claims"]] == [True, False]
    ans["timeline"]["false_claims"] = [
        {"doc_id": "doc:night_lead", "quote": "The compressor alarm was already on when I left."}]
    cl = grade(ans)["measured"]["sections"]["timeline"]["claims"]
    assert cl["hits"] == 0 and cl["f1"] == 0.0
    ans["timeline"]["false_claims"] = [{"doc_id": "doc:postmortem", "quote": "nobody opened it aga"}]
    assert grade(ans)["measured"]["sections"]["timeline"]["claims"]["hits"] == 0


def test_invalid_section_isolated():
    ans = perfect()
    ans["notation"]["v34_change"] = "bogus"
    sc = grade(ans)
    assert sc["section_status"]["notation"] == "invalid"
    assert sc["measured"]["sections"]["notation"]["score"] == 0.0
    assert sc["measured"]["solved"]["notation"] is False
    assert sc["section_errors"]["notation"]
    for s in ("mechanism", "causal_chain", "timeline"):
        assert sc["section_status"][s] == "ok"
        assert sc["measured"]["sections"][s]["score"] == pytest.approx(1.0)
    assert sc["measured"]["aggregate"] == pytest.approx(0.75)


def test_calibration_brier_and_pool():
    ans = perfect()
    ans["timeline"] = {"events": [], "clock_offsets_min": {}, "false_claims": []}
    ans["confidence"] = {"mechanism": 1.0, "timeline": 1.0}
    sc = grade(ans)
    cal = sc["measured"]["calibration"]
    assert sc["measured"]["solved"]["mechanism"] is True
    assert sc["measured"]["solved"]["timeline"] is False
    assert cal["brier"] == pytest.approx(0.5)
    assert cal["n_scored"] == 2 and cal["confidence_missing"] == 2
    pooled = calibration.pool([sc], bins=CFG["calibration_bins"])
    assert pooled["n"] == 2
    assert pooled["mean_conf"] == 1.0 and pooled["mean_solved"] == 0.5
    assert pooled["ece"] == pytest.approx(0.5)


def test_null_baseline_runs():
    out = null_baseline.run(TRUTH, EVID, n=20, seed=0, cfg=CFG)
    assert set(out["baselines"]) == {"missing", "empty_valid", "shuffled_truth", "max_recall"}
    for name, b in out["baselines"].items():
        for k in ("aggregate",) + SECTIONS:
            assert 0.0 <= b[k]["mean"] <= 1.0 and 0.0 <= b[k]["p95"] <= 1.0
    assert out["baselines"]["missing"]["aggregate"]["mean"] == 0.0
    assert out["baselines"]["shuffled_truth"]["n"] == 20
    assert out["baselines"]["max_recall"]["timeline"]["mean"] < 1.0


def test_pinned_rules_offsets_excursion_heldout():
    ans = perfect()
    offs = ans["timeline"]["clock_offsets_min"]
    offs["badge"] = TRUTH["timeline"]["clock_offsets_min"]["badge"] + CFG["offset_tol_min"]
    offs["exif"] = TRUTH["timeline"]["clock_offsets_min"]["exif"] - CFG["offset_tol_min"] - 1
    del offs["cctv"]
    off = grade(ans)["measured"]["sections"]["timeline"]["offsets"]
    assert off["hits"] == off["n_channels"] - 2
    assert off["channels"]["badge"]["hit"] and not off["channels"]["exif"]["hit"]
    assert not off["channels"]["cctv"]["hit"]

    ans = perfect()
    ans["causal_chain"]["excursion"]["end"] = "2026-03-08T09:00:00Z"
    assert grade(ans)["measured"]["sections"]["causal_chain"]["excursion"]["pts"] == CFG["excursion_one_bound_pts"]
    ans["causal_chain"]["excursion"]["zone"] = "A"
    assert grade(ans)["measured"]["sections"]["causal_chain"]["excursion"]["pts"] == 0.0

    ans = perfect()
    for f in ans["notation"]["heldout"]:
        f.pop("ts")
    res = grade(ans)["measured"]["sections"]["notation"]
    assert res["heldout_frames_full"] == 0
    assert all(f["checks"]["ts"] is False for f in res["heldout"])
    assert res["heldout_mean"] == pytest.approx((2 / 3 + 3 / 4) / 2)
