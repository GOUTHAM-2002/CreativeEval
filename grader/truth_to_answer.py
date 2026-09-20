"""Convert a truth.json into the perfect answer.json (oracle / tests).

v1 truths -> v1 answer. v2 truths (with `facts`) -> v2 answer: parameters as {value, confidence} (null for
undeterminable ones), the protocol block, one finding per fact (established / undetermined+alternatives / reframing)
plus one `refuted` finding per trap claim, timeline as v1, and a generated report.md text (`perfect_report`).
"""
import argparse
import json
import sys
from pathlib import Path

PARAM_CONF = 0.95
FACT_CONF = 0.95
ILL_CONF = 0.9
TRAP_CONF = 0.9
UNDET_CONF = 0.5
MIN_CLAIM = 15


def _v1(truth):
    m, n, c, t = truth["mechanism"], truth["notation"], truth["causal"], truth["timeline"]
    known = set(n["known_roots"])
    heldout = []
    for f in n["heldout"]:
        fr = {"seq": f["seq"], "ts": f["ts"], "zone": f["zone"], "event": f["event"]}
        if f.get("value") is not None:
            fr["value"] = f["value"]
        heldout.append(fr)
    return {
        "schema_version": "1",
        "mechanism": {
            "parameters": {k: v["value"] for k, v in m["params"].items()},
            "rules": {"defrost_rule_type": m["rules"]["defrost_rule_type"],
                      "stagger_order": list(m["rules"]["stagger_order"]),
                      "adjacency_pairs": [list(p) for p in m["rules"]["adjacency_pairs"]]},
        },
        "notation": {
            "glossary": {r: l for r, l in n["glossary"].items() if r not in known},
            "affixes": dict(n["affixes"]),
            "v34_change": n["v34_change"],
            "heldout": heldout,
        },
        "causal_chain": {
            "roots": list(c["roots"]), "nodes": list(c["nodes"]),
            "edges": [list(e) for e in c["edges"]],
            "decoys_rejected": list(c["decoys"]), "affected_lots": list(c["affected_lots"]),
            "excursion": {k: c["excursion"][k] for k in ("zone", "start", "end")},
        },
        "timeline": _timeline(t),
        "confidence": {"mechanism": 1.0, "notation": 1.0, "causal_chain": 1.0, "timeline": 1.0},
    }


def _timeline(t):
    return {
        "events": [{"actor": e["actor"], "action": e["action"], "t": e["t"], "ref": e.get("ref", "")} for e in t["events"]],
        "clock_offsets_min": dict(t["clock_offsets_min"]),
        "false_claims": [{"doc_id": fc["doc_id"], "quote": fc["text"]} for fc in t["false_claims"]],
    }


def _rules(m):
    return {"defrost_rule_type": m["rules"]["defrost_rule_type"],
            "stagger_order": list(m["rules"]["stagger_order"]),
            "adjacency_pairs": [list(p) for p in m["rules"]["adjacency_pairs"]]}


def perfect_params(truth, conf=PARAM_CONF):
    out = {}
    for pid, spec in truth["mechanism"]["params"].items():
        if spec.get("undeterminable"):
            hyp = "; ".join(spec.get("hypotheses") or [])
            out[pid] = {"value": None, "confidence": 0.0,
                        "note": "not determinable from the evidence" + (f" (consistent: {hyp})" if hyp else "")}
        else:
            out[pid] = {"value": spec["value"], "confidence": conf}
    return out


def perfect_protocol(truth):
    p = truth["protocol"]
    heldout = []
    for f in p.get("heldout", []):
        fr = {"seq": f["seq"], "ts": f.get("ts"), "zone": f["zone"], "event": f["event"]}
        if f.get("value") is not None:
            fr["value"] = f["value"]
        heldout.append(fr)
    return {"types": dict(p["types"]), "status_words": list(p["status_words"]),
            "temp_scale": int(p["temp_scale"]), "temp_offset": int(p["temp_offset"]), "press_scale": int(p["press_scale"]),
            "flag_bits": {k: int(v) for k, v in p["flag_bits"].items()},
            "v34_change": p["v34_change"], "heldout": heldout}


def _claim_text(fact):
    ans = fact.get("answer")
    ans_s = str(ans) if ans is not None else ""
    q = fact["question"].rstrip("?")
    if fact["kind"] == "determinable" and (len(ans_s) < MIN_CLAIM or not isinstance(ans, str)):
        return f"{q}: {ans_s}."
    return ans_s if len(ans_s) >= MIN_CLAIM else f"{q}: {ans_s}."


def perfect_findings(truth):
    findings = []
    for f in truth["facts"]:
        ev = list(f.get("evidence_for") or [])
        if f["kind"] == "determinable":
            findings.append({"claim": _claim_text(f), "status": "established", "confidence": FACT_CONF, "evidence": ev})
        elif f["kind"] == "undeterminable":
            why = f.get("why_undeterminable") or "the evidence does not settle it"
            sup = f.get("supported")
            claim = f"Cannot be determined from the evidence: {f['question']} {('What is supported: ' + sup + '. ') if sup else ''}Why: {why}."
            findings.append({"claim": claim, "status": "undetermined", "confidence": UNDET_CONF, "evidence": ev,
                             "alternatives": list(f.get("hypotheses") or [])})
        else:
            findings.append({"claim": _claim_text(f), "status": "established", "confidence": ILL_CONF, "evidence": ev})
        for t in f.get("trap_claims") or []:
            findings.append({"claim": f"The statement \"{t['text']}\" ({t.get('doc_id') or 'document'}) is not supported by the evidence.",
                             "status": "refuted", "confidence": TRAP_CONF, "evidence": ev})
    return findings


def perfect_report(truth):
    facts = truth["facts"]
    det = [f for f in facts if f["kind"] == "determinable"]
    und = [f for f in facts if f["kind"] == "undeterminable"]
    ill = [f for f in facts if f["kind"] == "ill_posed"]
    traps = [(f, t) for f in facts for t in (f.get("trap_claims") or [])]
    lines = ["# Investigation report", "",
             "## Executive summary",
             f"{len(det)} questions are settled by the evidence, {len(und)} cannot be determined from the evidence available, "
             f"and {len(ill)} questions rest on a false premise and are answered by reframing them.", "",
             "## What is established"]
    for f in det:
        lines.append(f"- {f['question']} {f['answer']}. (evidence: {', '.join(f.get('evidence_for') or [])})")
    lines += ["", "## What cannot be determined, and why"]
    for f in und:
        hyp = "; ".join(f.get("hypotheses") or [])
        miss = "; ".join(f.get("evidence_missing") or [])
        lines.append(f"- {f['question']} Cannot be determined. Consistent hypotheses: {hyp}. "
                     f"Why: {f.get('why_undeterminable', 'the evidence does not settle it')}."
                     + (f" Evidence that would settle it: {miss}." if miss else ""))
    lines += ["", "## Questions that rest on a false premise"]
    for f in ill:
        lines.append(f"- {f['question']} {f['answer']}.")
    lines += ["", "## Statements in the documents that the evidence does not support"]
    for f, t in traps:
        lines.append(f"- \"{t['text']}\" ({t.get('doc_id') or 'document'}): not supported; see {f['id']}.")
    lines += ["", "## Recommended actions",
              "- Restore the missing evidence sources listed above before drawing conclusions on the open questions.",
              "- Fix the gateway decoder and the alert-severity override; review door-prop practice.", ""]
    return "\n".join(lines)


def convert_v2(truth):
    """Return (answer, report_text) for a v2 truth."""
    ans = {
        "schema_version": "2",
        "mechanism": {"parameters": perfect_params(truth), "rules": _rules(truth["mechanism"])},
        "protocol": perfect_protocol(truth),
        "findings": perfect_findings(truth),
        "timeline": _timeline(truth["timeline"]),
        "confidence": {"mechanism": 1.0, "protocol": 1.0, "findings": 1.0, "timeline": 1.0},
    }
    return ans, perfect_report(truth)


def convert(truth):
    """Perfect answer for a v1 or v2 truth (v2: the answer only; see convert_v2 for the report text)."""
    if "facts" in truth:
        return convert_v2(truth)[0]
    return _v1(truth)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("truth")
    ap.add_argument("--out", default=None)
    ap.add_argument("--report-out", default=None, help="v2: also write the generated report.md")
    a = ap.parse_args(argv)
    truth = json.loads(Path(a.truth).read_text())
    if "facts" in truth:
        ans, report = convert_v2(truth)
        if a.report_out:
            Path(a.report_out).write_text(report)
    else:
        ans = convert(truth)
    text = json.dumps(ans, indent=1)
    if a.out:
        Path(a.out).write_text(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
