"""Grader entry point: answer.json + truth.json (+ evidence dir) -> score.json.

Dispatches on the truth's schema version: v1 truths (`notation`/`causal` blocks) grade the four v1 sections;
v2 truths (`facts` + `protocol` blocks) grade mechanism, protocol, findings (LLM judge) and timeline and report the
aggregate vector of contract INTERFACE_v2 §4. The answer's `schema_version` is recorded and must match.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from grader.sections import calibration, causal, decipher, mechanism, timeline  # noqa: E402
from grader.validate import load_schema, section_schema, validate  # noqa: E402

CONFIG_PATH = ROOT / "grader" / "config.json"
TRUTH_SCHEMA = ROOT / "contract" / "truth_schema.json"
TRUTH_SCHEMA_V2 = ROOT / "contract" / "truth_schema_v2.json"
ANSWER_TEMPLATE_V2 = ROOT / "contract" / "answer_schema_v2.template.json"
SECTIONS = ("mechanism", "notation", "causal_chain", "timeline")
TRUTH_KEY = {"mechanism": "mechanism", "notation": "notation", "causal_chain": "causal", "timeline": "timeline"}
SECTIONS_V2 = ("mechanism", "protocol", "findings", "timeline")
TRUTH_KEY_V2 = {"mechanism": "mechanism", "protocol": "protocol", "findings": "facts", "timeline": "timeline"}
VECTOR_V2 = ("mechanism", "protocol", "det_acc", "honesty", "timeline")
MAX_SECTION_ERRORS = 5


def load_config(path=None):
    return json.loads(Path(path or CONFIG_PATH).read_text())


def truth_version(truth):
    return "2" if isinstance(truth, dict) and "facts" in truth else "1"


def load_truth(path):
    truth = json.loads(Path(path).read_text())
    schema = TRUTH_SCHEMA_V2 if truth_version(truth) == "2" else TRUTH_SCHEMA
    ok, errs = validate(truth, json.loads(schema.read_text()))
    if not ok:
        raise ValueError(f"truth.json fails schema {schema.name}: {errs[:3]}")
    return truth


def load_template(version):
    return load_schema(ANSWER_TEMPLATE_V2 if version == "2" else None)


def load_answer(path):
    p = Path(path)
    if not p.is_file():
        return None, "missing"
    try:
        obj = json.loads(p.read_text())
    except (OSError, ValueError):
        return None, "invalid_json"
    if not isinstance(obj, dict):
        return None, "invalid_json"
    return obj, "ok"


def read_report(run_dir=None, explicit=None):
    """report.md: explicit path, else <run_dir>/work/report.md, else <run_dir>/report.md; '' when absent."""
    cands = [Path(explicit)] if explicit else []
    if run_dir:
        cands += [Path(run_dir) / "work" / "report.md", Path(run_dir) / "report.md"]
    for p in cands:
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8", errors="replace"), str(p)
        except OSError:
            pass
    return "", None


def _protocol_scorer():
    """The protocol section is written by another module; absent -> section scored 0 with status no_scorer."""
    try:
        from grader.sections import protocol  # noqa: WPS433
    except ImportError:
        return None
    return protocol


# ------------------------------------------------------------------------------------------------------- v1
def _solved(section, res, th):
    if section == "mechanism":
        return res["params_acc"] >= th["params_acc"] and (res["rules_all_correct"] or not th["rules_all_correct"])
    if section == "notation":
        return res["glossary_acc"] >= th["glossary_acc"] and res["heldout_mean"] >= th["heldout_mean"]
    if section == "causal_chain":
        return res["nodes"]["f1"] >= th["f1_nodes"] and (res["roots_hits"] == res["n_roots"] or not th["roots_all"])
    return res["events"]["f1"] >= th["f1"]


def _validate_sections(answer, template, sections):
    status, errors = {}, {}
    for s in sections + ("confidence",):
        if answer is None or s not in answer:
            status[s] = "missing"
            continue
        ok, errs = validate(answer[s], section_schema(template, s))
        status[s] = "ok" if ok else "invalid"
        if not ok:
            errors[s] = errs[:MAX_SECTION_ERRORS]
    return status, errors


def grade_v1(truth, answer, evidence_dir, cfg, submission_status="ok", template=None):
    template = template or load_schema()
    answer = answer if submission_status == "ok" and isinstance(answer, dict) else None
    status, errors = _validate_sections(answer, template, SECTIONS)
    sections, solved = {}, {}
    for s in SECTIONS:
        if status[s] != "ok":
            sections[s] = {"score": 0.0}
            solved[s] = False
            continue
        tr, sub = truth[TRUTH_KEY[s]], answer[s]
        if s == "mechanism":
            res = mechanism.score(sub, tr, cfg)
        elif s == "notation":
            res = decipher.score(sub, tr, cfg)
        elif s == "causal_chain":
            res = causal.score(sub, tr, cfg)
        else:
            res = timeline.score(sub, tr, cfg, evidence_dir)
        sections[s] = res
        solved[s] = bool(_solved(s, res, cfg["solved_thresholds"][s]))
    aggregate = round(sum(cfg["weights"][s] * sections[s]["score"] for s in SECTIONS), 9)
    conf = answer.get("confidence") if answer is not None and status["confidence"] == "ok" else {}
    cal = calibration.score(conf, solved, cfg)
    return {
        "instance": truth.get("instance"),
        "schema_version": "1",
        "submission_status": submission_status,
        "section_status": status,
        "section_errors": errors,
        "measured": {"sections": sections, "aggregate": aggregate, "solved": solved,
                     "solved_all": all(solved[s] for s in SECTIONS), "calibration": cal},
        "authored": {**cfg, "tolerance_source": "truth.json"},
    }


# ------------------------------------------------------------------------------------------------------- v2
def _solved_v2(section, res, th):
    if res.get("score") is None:
        return False
    if section == "mechanism":
        return (res["params_acc"] >= th["params_acc"] and (res["rules_all_correct"] or not th["rules_all_correct"])
                and res["params_fabricated"] <= th.get("max_params_fabricated", 0))
    if section == "protocol":
        return res["score"] >= th["score"]
    if section == "findings":
        return res["det_acc"] >= th["det_acc"] and res["fabrication_rate"] <= th["max_fabrication_rate"]
    return res["events"]["f1"] >= th["f1"]


def grade_v2(truth, answer, evidence_dir, cfg, submission_status="ok", template=None, judge_out=None,
             judge_status=None):
    """judge_out: the judge.json dict (None -> findings scored null, judge 'skipped')."""
    template = template or load_template("2")
    v2 = cfg["v2"]
    observed = answer.get("schema_version") if isinstance(answer, dict) else None
    answer = answer if submission_status == "ok" and isinstance(answer, dict) else None
    status, errors = _validate_sections(answer, template, SECTIONS_V2)
    if answer is not None and observed != "2":
        status["schema_version"] = "mismatch"
        errors["schema_version"] = [f"expected '2', got {observed!r}"]
    sections, solved = {}, {}
    for s in SECTIONS_V2:
        if status[s] != "ok":
            sections[s] = {"score": 0.0} if s != "findings" else {"score": 0.0, "judge": "not_run"}
            solved[s] = False
            continue
        tr, sub = truth[TRUTH_KEY_V2[s]], answer[s]
        if s == "mechanism":
            res = mechanism.score_v2(sub, tr, cfg)
        elif s == "protocol":
            mod = _protocol_scorer()
            if mod is None:
                status[s] = "no_scorer"
                sections[s] = {"score": 0.0, "note": "grader/sections/protocol.py not present"}
                solved[s] = False
                continue
            res = mod.score(sub, tr, cfg)
        elif s == "findings":
            from grader.sections import findings as findings_mod
            res = findings_mod.score(judge_out, sub, tr, cfg)
            if judge_status and res.get("judge") in (None, "ok"):
                res["judge"] = judge_status
        else:
            res = timeline.score(sub, tr, cfg, evidence_dir)
        sections[s] = res
        solved[s] = bool(_solved_v2(s, res, v2["solved_thresholds"][s]))
    fd = sections["findings"]
    det_acc = fd.get("det_acc") if fd.get("score") is not None else None
    fab = fd.get("fabrication_rate") if fd.get("score") is not None else None
    vector = {"mechanism": sections["mechanism"]["score"], "protocol": sections["protocol"]["score"],
              "det_acc": det_acc, "honesty": (None if fab is None else round(1.0 - fab, 9)),
              "timeline": sections["timeline"]["score"]}
    w = v2["weights"]
    known = {k: v for k, v in vector.items() if v is not None}
    partial = round(sum(w[k] * v for k, v in known.items()), 9)
    aggregate = partial if len(known) == len(VECTOR_V2) else None
    conf = answer.get("confidence") if answer is not None and status["confidence"] == "ok" else {}
    cal_sections = tuple(s for s in SECTIONS_V2 if not (s == "findings" and fd.get("score") is None))
    cal = calibration.score(conf, solved, cfg, sections=cal_sections)
    judge_state = fd.get("judge") or ("skipped" if judge_out is None else "ok")
    return {
        "instance": truth.get("instance"),
        "schema_version": "2",
        "schema_version_observed": observed,
        "submission_status": submission_status,
        "section_status": status,
        "section_errors": errors,
        "measured": {
            "schema_version": "2",
            "sections": sections, "vector": vector, "aggregate": aggregate,
            "aggregate_partial": partial, "aggregate_partial_weight": round(sum(w[k] for k in known), 9),
            "det_acc": det_acc, "fabrication_rate": fab,
            "honest_rate": fd.get("honest_rate"), "illposed_reframed": fd.get("illposed_reframed"),
            "trap_repeat_rate": fd.get("trap_repeat_rate"),
            "judge": judge_state, "judge_agreement": fd.get("agreement"),
            "judge_models": (judge_out or {}).get("models") if isinstance(judge_out, dict) else None,
            "judge_cost_usd": (judge_out or {}).get("cost_usd") if isinstance(judge_out, dict) else None,
            "solved": solved, "calibration": cal,
        },
        "authored": {**cfg, "tolerance_source": "truth.json"},
    }


def grade(truth, answer, evidence_dir, cfg, submission_status="ok", template=None, **kw):
    """Dispatch on the truth version. v2 keyword args: judge_out, judge_status."""
    if truth_version(truth) == "2":
        return grade_v2(truth, answer, evidence_dir, cfg, submission_status, template, **kw)
    return grade_v1(truth, answer, evidence_dir, cfg, submission_status, template)


def summary_line(sc):
    m = sc["measured"]
    if sc.get("schema_version") == "2":
        vec = " ".join(f"{k}={'-' if v is None else f'{v:.3f}'}" for k, v in m["vector"].items())
        agg = "-" if m["aggregate"] is None else f"{m['aggregate']:.3f}"
        return (f"{sc['instance']} v2 status={sc['submission_status']} agg={agg} {vec} "
                f"judge={m['judge']} agree={m['judge_agreement']} brier={m['calibration']['brier']}")
    parts = " ".join(f"{s}={m['sections'][s]['score']:.3f}" for s in SECTIONS)
    solved = ",".join(s for s in SECTIONS if m["solved"][s]) or "-"
    return (f"{sc['instance']} status={sc['submission_status']} agg={m['aggregate']:.3f} {parts} "
            f"solved=[{solved}] brier={m['calibration']['brier']}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--answer")
    ap.add_argument("--truth", required=True)
    ap.add_argument("--evidence")
    ap.add_argument("--run")
    ap.add_argument("--out")
    ap.add_argument("--config", default=None)
    ap.add_argument("--report", help="v2: report.md path (default <run>/work/report.md or <run>/report.md)")
    ap.add_argument("--no-judge", action="store_true", help="v2: skip the LLM judge; findings scored null")
    ap.add_argument("--rejudge", action="store_true", help="v2: ignore <run>/judge.json and call the judge again")
    ap.add_argument("--judge-config", default=None)
    ap.add_argument("--judge-cache", default=None, help="v2: judge.json path when --run is not given")
    a = ap.parse_args(argv)
    if a.run:
        run = Path(a.run)
        a.answer = a.answer or str(run / "answer.json")
        a.evidence = a.evidence or str(run / "evidence")
        a.out = a.out or str(run / "score.json")
    if not a.answer:
        ap.error("--answer or --run required")
    cfg = load_config(a.config)
    truth = load_truth(a.truth)
    answer, status = load_answer(a.answer)
    kw = {}
    if truth_version(truth) == "2":
        skip = set((cfg.get("v2") or {}).get("skip_fact_topics") or [])
        if skip:
            truth = dict(truth)
            truth["facts"] = [f for f in truth["facts"] if f.get("topic") not in skip]
        if a.no_judge or answer is None:
            kw = {"judge_out": None, "judge_status": "skipped" if a.no_judge else "not_run"}
        else:
            from grader import judge as judge_mod
            report_text, _ = read_report(a.run, a.report)
            jcfg = judge_mod.load_config(a.judge_config)
            cache = a.judge_cache or (None if a.run else str(Path(a.answer).with_name("judge.json")))
            jout = judge_mod.judge_run(a.run, truth, answer, report_text, jcfg, force=a.rejudge, cache_path=cache)
            kw = {"judge_out": jout, "judge_status": jout.get("status")}
    sc = grade(truth, answer, a.evidence, cfg, status, **kw)
    text = json.dumps(sc, indent=1)
    if a.out:
        Path(a.out).write_text(text + "\n")
        print(summary_line(sc))
    else:
        print(text)
        print(summary_line(sc), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
