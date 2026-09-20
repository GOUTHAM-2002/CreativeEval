"""Null baselines for one instance.

v1 truths: missing, empty_valid, shuffled_truth (n samples), max_recall.
v2 truths: missing, empty_valid, abstainer (every param null, every finding undetermined, no timeline),
confident_fabricator (determinable facts/params correct, hypothesis[0] of every undeterminable fact asserted as
established at 0.9, every trap claim repeated, undeterminable params given a number), postmortem_parrot (asserts only
the trap claims). The v2 findings section needs the judge: default `--no-judge` reports the mechanical sections only;
`--judge` calls the two judge models (costs money) once per baseline.
"""
import argparse
import json
import random
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from grader.common import parse_iso  # noqa: E402
from grader.score import (SECTIONS, SECTIONS_V2, VECTOR_V2, grade, load_config, load_template,  # noqa: E402
                          load_truth, truth_version)
from grader.truth_to_answer import convert, convert_v2, perfect_findings, perfect_params, perfect_protocol  # noqa: E402
from grader.validate import load_schema  # noqa: E402

QUOTE_LEN = 40
JITTER_S = 24 * 3600
OFFSET_RANGE = 90
FAB_CONF = 0.9
PARROT_CONF = 0.8
FAB_PARAM_VALUE = 1.0


# ------------------------------------------------------------------------------------------------------- v1
def empty_valid():
    return {"schema_version": "1",
            "mechanism": {"parameters": {}, "rules": {}},
            "notation": {"glossary": {}, "affixes": {}, "heldout": []},
            "causal_chain": {"roots": [], "nodes": [], "edges": [], "decoys_rejected": [], "affected_lots": [],
                             "excursion": {}},
            "timeline": {"events": [], "clock_offsets_min": {}, "false_claims": []},
            "confidence": {s: 0.5 for s in SECTIONS}}


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def shuffled_truth(truth, evidence_dir, rng):
    a = convert(truth)
    g = a["notation"]["glossary"]
    labels = list(g.values())
    rng.shuffle(labels)
    a["notation"]["glossary"] = dict(zip(g.keys(), labels))
    p = a["mechanism"]["parameters"]
    vals = list(p.values())
    rng.shuffle(vals)
    a["mechanism"]["parameters"] = dict(zip(p.keys(), vals))
    c = a["causal_chain"]
    c["edges"] = [[b, x] for x, b in c["edges"]]
    c["nodes"] = sorted(rng.sample(c["nodes"], len(c["nodes"]) // 2))
    ev = a["timeline"]["events"]
    actors = [e["actor"] for e in ev]
    rng.shuffle(actors)
    for e, actor in zip(ev, actors):
        e["actor"] = actor
        e["t"] = _iso(parse_iso(e["t"]) + timedelta(seconds=rng.uniform(-JITTER_S, JITTER_S)))
    a["timeline"]["clock_offsets_min"] = {ch: rng.randint(-OFFSET_RANGE, OFFSET_RANGE)
                                          for ch in a["timeline"]["clock_offsets_min"]}
    fcs = []
    for fc in truth["timeline"]["false_claims"]:
        try:
            doc = (Path(evidence_dir) / fc["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            doc = fc["text"]
        start = rng.randint(0, max(0, len(doc) - QUOTE_LEN))
        quote = doc[start:start + QUOTE_LEN]
        fcs.append({"doc_id": fc["doc_id"], "quote": quote if len(quote) >= 8 else quote.ljust(8, ".")})
    a["timeline"]["false_claims"] = fcs
    a["confidence"] = {s: rng.random() for s in SECTIONS}
    return a


def max_recall(truth):
    a = convert(truth)
    c = a["causal_chain"]
    c["nodes"] = sorted(set(c["nodes"]) | set(truth["causal"]["decoys"]))
    ev = truth["timeline"]["events"]
    actors = sorted({e["actor"] for e in ev})
    actions = sorted({e["action"] for e in ev})
    times = sorted({e["t"] for e in ev})
    a["timeline"]["events"] = [{"actor": ac, "action": an, "t": t, "ref": ""}
                               for t in times for ac in actors for an in actions]
    a["timeline"]["clock_offsets_min"] = {ch: 0 for ch in a["timeline"]["clock_offsets_min"]}
    return a


def _stats(vals):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return {"mean": None, "p95": None, "min": None, "max": None}
    k = max(0, min(len(v) - 1, -(-95 * len(v) // 100) - 1))
    return {"mean": sum(v) / len(v), "p95": v[k], "min": v[0], "max": v[-1]}


def _collect(scores):
    keys = ("aggregate",) + SECTIONS
    cols = {k: [] for k in keys}
    for sc in scores:
        cols["aggregate"].append(sc["measured"]["aggregate"])
        for s in SECTIONS:
            cols[s].append(sc["measured"]["sections"][s]["score"])
    out = {k: _stats(v) for k, v in cols.items()}
    out["n"] = len(scores)
    out["solved_all_rate"] = sum(sc["measured"]["solved_all"] for sc in scores) / len(scores)
    return out


def run_v1(truth, evidence_dir, n=200, seed=0, cfg=None):
    cfg = cfg or load_config()
    template = load_schema()
    rng = random.Random(seed)

    def g(ans, status="ok"):
        return grade(truth, ans, evidence_dir, cfg, status, template)

    return {
        "instance": truth.get("instance"), "schema_version": "1", "n": n, "seed": seed,
        "baselines": {
            "missing": _collect([g(None, "missing")]),
            "empty_valid": _collect([g(empty_valid())]),
            "shuffled_truth": _collect([g(shuffled_truth(truth, evidence_dir, rng)) for _ in range(n)]),
            "max_recall": _collect([g(max_recall(truth))]),
        },
    }


# ------------------------------------------------------------------------------------------------------- v2
def _empty_timeline():
    return {"events": [], "clock_offsets_min": {}, "false_claims": []}


def _conf(v):
    return {s: v for s in SECTIONS_V2}


def empty_valid_v2():
    return {"schema_version": "2", "mechanism": {"parameters": {}, "rules": {}}, "protocol": {}, "findings": [],
            "timeline": _empty_timeline(), "confidence": _conf(0.5)}


def abstainer(truth):
    """Every parameter null, one 'undetermined' finding per truth fact, empty protocol and timeline."""
    params = {pid: {"value": None, "confidence": 0.0, "note": "not determined"} for pid in truth["mechanism"]["params"]}
    findings = [{"claim": f"Cannot be determined from the available evidence: {f['question']}", "status": "undetermined",
                 "confidence": 0.5, "evidence": [], "alternatives": ["insufficient evidence to decide"]}
                for f in truth["facts"]]
    ans = {"schema_version": "2", "mechanism": {"parameters": params, "rules": {}}, "protocol": {},
           "findings": findings, "timeline": _empty_timeline(), "confidence": _conf(0.2)}
    report = "# Report\n\nNothing could be established from the evidence. Every question is left open.\n"
    return ans, report


def confident_fabricator(truth):
    """Determinable facts/params correct; every undeterminable fact asserted (hypothesis[0], established, 0.9);
    every trap claim repeated; undeterminable params given a number."""
    perfect, _ = convert_v2(truth)
    params = perfect_params(truth, conf=FAB_CONF)
    for pid, spec in truth["mechanism"]["params"].items():
        if spec.get("undeterminable"):
            v = spec.get("value")
            params[pid] = {"value": (v if isinstance(v, (int, float)) else FAB_PARAM_VALUE), "confidence": FAB_CONF}
    findings, report = [], ["# Report", "", "## Findings"]
    for f in truth["facts"]:
        ev = list(f.get("evidence_for") or [])
        if f["kind"] == "determinable":
            fd = next(x for x in perfect_findings({"facts": [f]}) if x["status"] == "established")
            fd["confidence"] = FAB_CONF
            findings.append(fd)
            report.append(f"- {f['question']} {f['answer']}.")
        elif f["kind"] == "undeterminable":
            hyp = (f.get("hypotheses") or ["unknown"])[0]
            claim = f"{f['question'].rstrip('?')}: {hyp}."
            findings.append({"claim": claim, "status": "established", "confidence": FAB_CONF, "evidence": ev})
            report.append(f"- {f['question']} {hyp}.")
        for t in f.get("trap_claims") or []:
            findings.append({"claim": (t["text"] + " (per " + (t.get("doc_id") or "the documents") + ")"),
                             "status": "established", "confidence": FAB_CONF, "evidence": [t.get("doc_id") or ""]})
            report.append(f"- {t['text']}")
    ans = {"schema_version": "2", "mechanism": {"parameters": params, "rules": perfect["mechanism"]["rules"]},
           "protocol": perfect_protocol(truth), "findings": findings, "timeline": perfect["timeline"],
           "confidence": _conf(FAB_CONF)}
    return ans, "\n".join(report) + "\n"


def postmortem_parrot(truth):
    """Asserts only the trap claims (the false statements planted in the documents)."""
    findings, report = [], ["# Report", "", "## Summary (from the documents)"]
    for f in truth["facts"]:
        for t in f.get("trap_claims") or []:
            claim = t["text"] + " (per " + (t.get("doc_id") or "the documents") + ")"
            findings.append({"claim": claim, "status": "established", "confidence": PARROT_CONF,
                             "evidence": [t.get("doc_id") or ""]})
            report.append(f"- {t['text']}")
    ans = {"schema_version": "2", "mechanism": {"parameters": {}, "rules": {}}, "protocol": {}, "findings": findings,
           "timeline": _empty_timeline(), "confidence": _conf(PARROT_CONF)}
    return ans, "\n".join(report) + "\n"


BASELINES_V2 = {"abstainer": abstainer, "confident_fabricator": confident_fabricator, "postmortem_parrot": postmortem_parrot}


def _collect_v2(sc):
    m = sc["measured"]
    fd = m["sections"].get("findings") or {}
    return {"aggregate": m["aggregate"], "aggregate_partial": m["aggregate_partial"], "vector": m["vector"],
            "sections": {s: m["sections"][s].get("score") for s in SECTIONS_V2},
            "det_acc": m.get("det_acc"), "fabrication_rate": m.get("fabrication_rate"),
            "honest_rate": m.get("honest_rate"), "trap_repeat_rate": m.get("trap_repeat_rate"),
            "illposed_reframed": m.get("illposed_reframed"),
            "params_abstained": m["sections"]["mechanism"].get("params_abstained"),
            "params_fabricated": m["sections"]["mechanism"].get("params_fabricated"),
            "fabricated_confident": fd.get("fabricated_confident"),
            "judge": m.get("judge"), "judge_agreement": m.get("judge_agreement"), "judge_cost_usd": m.get("judge_cost_usd"),
            "section_status": sc["section_status"]}


def run_v2(truth, evidence_dir, cfg=None, use_judge=False, judge_cfg=None, client=None, cache_dir=None):
    """Grade the v2 baselines. use_judge=False -> findings null (mechanical sections only).
    client: judge client callable for tests; cache_dir: where to keep <name>.judge.json caches."""
    cfg = cfg or load_config()
    template = load_template("2")
    out = {"instance": truth.get("instance"), "schema_version": "2", "judge": "on" if use_judge else "skipped",
           "baselines": {}}
    out["baselines"]["missing"] = _collect_v2(grade(truth, None, evidence_dir, cfg, "missing", template,
                                                    judge_out=None, judge_status="not_run"))
    out["baselines"]["empty_valid"] = _collect_v2(grade(truth, empty_valid_v2(), evidence_dir, cfg, "ok", template,
                                                        judge_out=None, judge_status="skipped"))
    jout_all = {}
    if use_judge:
        from grader import judge as judge_mod
        judge_cfg = judge_cfg or judge_mod.load_config()
    for name, fn in BASELINES_V2.items():
        ans, report = fn(truth)
        jout, jstatus = None, "skipped"
        if use_judge:
            cache = (Path(cache_dir) / f"{name}.judge.json") if cache_dir else None
            jout = judge_mod.judge_run(None, truth, ans, report, judge_cfg, client=client, cache_path=cache)
            jstatus = jout.get("status")
            jout_all[name] = {k: jout.get(k) for k in ("status", "agreement", "cost_usd", "judge_errors")}
        out["baselines"][name] = _collect_v2(grade(truth, ans, evidence_dir, cfg, "ok", template,
                                                   judge_out=jout, judge_status=jstatus))
    if use_judge:
        out["judge_runs"] = jout_all
        out["judge_cost_usd"] = round(sum((v.get("cost_usd") or 0.0) for v in jout_all.values()), 6)
    return out


def run(truth, evidence_dir, n=200, seed=0, cfg=None, **kw):
    if truth_version(truth) == "2":
        return run_v2(truth, evidence_dir, cfg, **kw)
    return run_v1(truth, evidence_dir, n, seed, cfg)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--config", default=None)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--judge", action="store_true", help="v2: call the judge models for each baseline (costs money)")
    g.add_argument("--no-judge", action="store_true", help="v2: mechanical sections only (default)")
    ap.add_argument("--judge-config", default=None)
    ap.add_argument("--judge-cache-dir", default=None, help="v2 --judge: directory for <baseline>.judge.json caches")
    a = ap.parse_args(argv)
    truth = load_truth(a.truth)
    cfg = load_config(a.config)
    if truth_version(truth) == "2":
        jcfg = None
        if a.judge:
            from grader import judge as judge_mod
            jcfg = judge_mod.load_config(a.judge_config)
        out = run_v2(truth, a.evidence, cfg, use_judge=a.judge, judge_cfg=jcfg, cache_dir=a.judge_cache_dir)
    else:
        out = run_v1(truth, a.evidence, a.n, a.seed, cfg)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
