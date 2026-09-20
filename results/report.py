# Summarise runs/<tag>: one row per model x tier, plus null-baseline rows per instance. No interpretation.
# v1 score.json rows keep the v1 columns; v2 rows (measured.schema_version == "2") get the v2 columns: det_acc k/n,
# fabrication k/n, honest k/n, illposed k/n, trap_repeat k/n, judge agreement, params_abstained, params_fabricated,
# protocol score and the aggregate vector.
from __future__ import annotations
import argparse
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

V2_VECTOR = ("mechanism", "protocol", "det_acc", "honesty", "timeline")


def kn(hits, n):
    return f"{hits}/{n}"


def load_runs(tag_dir: Path):
    rows = []
    for ep in sorted(tag_dir.glob("*/*/episode.json")):
        run_dir = ep.parent
        e = json.load(open(ep))
        sc = json.load(open(run_dir / "score.json")) if (run_dir / "score.json").exists() else None
        rows.append((run_dir, e, sc))
    return rows


def _is_v2(sc):
    return bool(sc) and (sc.get("measured") or {}).get("schema_version") == "2"


def _mean(vals, nd=3):
    vals = [v for v in vals if v is not None]
    return round(st.mean(vals), nd) if vals else "-"


def _common(model, tier, items, scored):
    n = len(items)
    calls = [e.get("n_tool_calls", 0) for _, e, _ in items]
    cost = [e.get("cost_usd") or 0.0 for _, e, _ in items]
    ends = defaultdict(int)
    for _, e, _ in items:
        ends[e.get("end_reason")] += 1
    submitted = sum(1 for sc in scored if sc.get("submission_status") == "ok")
    invalid = sum(1 for sc in scored if any(v == "invalid" for v in sc.get("section_status", {}).values()))
    head = {"model": model, "tier": tier, "n": n, "submitted": kn(submitted, n), "invalid_sections": kn(invalid, n)}
    tail = {"tool_calls": f"{int(st.median(calls))} ({min(calls)}-{max(calls)})" if calls else "-",
            "cost_usd": f"{st.median(cost):.2f} (sum {sum(cost):.2f})" if cost else "-",
            "end_reasons": dict(ends)}
    return head, tail


def _row_v1(model, tier, items, scored):
    head, tail = _common(model, tier, items, scored)
    m = [sc["measured"] for sc in scored]

    def sum_kn(s, hits_key, n_key):
        h = sum(x["sections"][s].get(hits_key, 0) for x in m if s in x["sections"])
        d = sum(x["sections"][s].get(n_key, 0) for x in m if s in x["sections"])
        return kn(h, d)

    agg = [x["aggregate"] for x in m]
    solved_all = sum(1 for x in m if x.get("solved_all"))
    brier = [x["calibration"]["brier"] for x in m if x.get("calibration", {}).get("brier") is not None]
    return {
        **head,
        "mech_params": sum_kn("mechanism", "params_hits", "n_params"),
        "rules_ok": kn(sum(1 for x in m if x["sections"].get("mechanism", {}).get("rules_all_correct")), len(m)),
        "glossary": sum_kn("notation", "glossary_hits", "n_unknown"), "heldout_full": sum_kn("notation", "heldout_frames_full", "n_heldout"),
        "node_f1": _mean([x["sections"]["causal_chain"]["nodes"]["f1"] for x in m if "nodes" in x["sections"].get("causal_chain", {})] or [0]),
        "edge_f1": _mean([x["sections"]["causal_chain"]["edges"]["f1"] for x in m if "edges" in x["sections"].get("causal_chain", {})] or [0]),
        "roots": sum_kn("causal_chain", "roots_hits", "n_roots"), "decoys_in": sum_kn("causal_chain", "decoys_included", "n_decoys"),
        "lots_f1": _mean([x["sections"]["causal_chain"]["affected_lots"]["f1"] for x in m if "affected_lots" in x["sections"].get("causal_chain", {})] or [0]),
        "timeline_f1": _mean([x["sections"]["timeline"]["events"]["f1"] for x in m if "events" in x["sections"].get("timeline", {})] or [0]),
        "offsets": kn(sum(x["sections"]["timeline"]["offsets"]["hits"] for x in m if "offsets" in x["sections"].get("timeline", {})),
                      sum(x["sections"]["timeline"]["offsets"]["n_channels"] for x in m if "offsets" in x["sections"].get("timeline", {}))),
        "claims_f1": _mean([x["sections"]["timeline"]["claims"]["f1"] for x in m if "claims" in x["sections"].get("timeline", {})] or [0]),
        "aggregate": f"{st.mean(agg):.3f} [{min(agg):.3f},{max(agg):.3f}]" if agg else "-",
        "solved_all": kn(solved_all, len(m)), "brier": round(st.mean(brier), 3) if brier else "-",
        **tail,
    }


def _row_v2(model, tier, items, scored):
    head, tail = _common(model, tier, items, scored)
    m = [sc["measured"] for sc in scored]
    mech = [x["sections"].get("mechanism", {}) for x in m]
    fds = [x["sections"].get("findings", {}) for x in m]
    judged = [f for f in fds if f.get("score") is not None]

    def sum_kn_fd(bucket, key, n_key):
        return kn(sum(f[bucket].get(key, 0) for f in judged if bucket in f), sum(f.get(n_key, 0) for f in judged))

    agg = [x["aggregate"] for x in m if x.get("aggregate") is not None]
    vec = {k: _mean([(x.get("vector") or {}).get(k) for x in m]) for k in V2_VECTOR}
    brier = [x["calibration"]["brier"] for x in m if x.get("calibration", {}).get("brier") is not None]
    jcost = [x.get("judge_cost_usd") or 0.0 for x in m]
    return {
        **head,
        "mech_params": kn(sum(x.get("params_hits", 0) for x in mech), sum(x.get("n_params_det", 0) for x in mech)),
        "params_abstained": kn(sum(x.get("params_abstained", 0) for x in mech), sum(x.get("n_params_det", 0) for x in mech)),
        "params_fabricated": kn(sum(x.get("params_fabricated", 0) for x in mech), sum(x.get("n_params_undet", 0) for x in mech)),
        "rules_ok": kn(sum(1 for x in mech if x.get("rules_all_correct")), len(m)),
        "protocol": _mean([x["sections"].get("protocol", {}).get("score") for x in m]),
        "protocol_status": dict(defaultdict(int, {s: sum(1 for sc in scored if sc["section_status"].get("protocol") == s)
                                                  for s in {sc["section_status"].get("protocol") for sc in scored}})),
        "det_acc": sum_kn_fd("det", "correct", "n_det"),
        "fabrication": sum_kn_fd("undet", "fabricated", "n_undet"),
        "honest": sum_kn_fd("undet", "honest", "n_undet"),
        "illposed_reframed": sum_kn_fd("illposed", "reframed", "n_illposed"),
        "trap_repeat": sum_kn_fd("traps", "repeated", "n_traps"),
        "fabricated_confident": sum(f.get("fabricated_confident", 0) for f in judged),
        "judge": kn(len(judged), len(fds)), "judge_agreement": _mean([f.get("agreement") for f in judged]),
        "judge_cost_usd": f"{sum(jcost):.2f}",
        "timeline_f1": _mean([x["sections"]["timeline"]["events"]["f1"] for x in m if "events" in x["sections"].get("timeline", {})] or [0]),
        "offsets": kn(sum(x["sections"]["timeline"]["offsets"]["hits"] for x in m if "offsets" in x["sections"].get("timeline", {})),
                      sum(x["sections"]["timeline"]["offsets"]["n_channels"] for x in m if "offsets" in x["sections"].get("timeline", {}))),
        "vector": " ".join(f"{k}={v}" for k, v in vec.items()),
        "aggregate": f"{st.mean(agg):.3f} [{min(agg):.3f},{max(agg):.3f}]" if agg else "-",
        "aggregate_partial": _mean([x.get("aggregate_partial") for x in m]),
        "brier": round(st.mean(brier), 3) if brier else "-",
        **tail,
    }


def summarise(rows):
    by = defaultdict(list)
    for run_dir, e, sc in rows:
        by[(e.get("model"), e.get("tier", "default"), "2" if _is_v2(sc) else "1")].append((run_dir, e, sc))
    out = []
    for (model, tier, ver), items in sorted(by.items()):
        scored = [sc for _, _, sc in items if sc]
        out.append((_row_v2 if ver == "2" else _row_v1)(model, tier, items, scored))
    return out


def md_table(rows):
    if not rows:
        return "(no runs)"
    keys = list(rows[0].keys())
    lines = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(k, "-")) for k in keys) + " |")
    return "\n".join(lines)


def _per_run(run_dir, e, sc):
    row = {"run": run_dir.relative_to(ROOT).as_posix(), "model": e.get("model"), "end_reason": e.get("end_reason"),
           "tool_calls": e.get("n_tool_calls"), "cost_usd": e.get("cost_usd"), "invalid_markers": e.get("invalid_markers"),
           "aggregate": sc["measured"]["aggregate"] if sc else None,
           "sections": {k: (round(v["score"], 3) if v.get("score") is not None else None)
                        for k, v in sc["measured"]["sections"].items()} if sc else None,
           "solved": sc["measured"].get("solved") if sc else None,
           "confidence": sc["measured"]["calibration"].get("sections") if sc else None}
    if _is_v2(sc):
        m = sc["measured"]
        fd = m["sections"].get("findings", {})
        row.update({"schema_version": "2", "vector": m.get("vector"), "aggregate_partial": m.get("aggregate_partial"),
                    "det_acc": kn(fd.get("det", {}).get("correct", "-"), fd.get("n_det", "-")),
                    "fabrication": kn(fd.get("undet", {}).get("fabricated", "-"), fd.get("n_undet", "-")),
                    "honest": kn(fd.get("undet", {}).get("honest", "-"), fd.get("n_undet", "-")),
                    "illposed": kn(fd.get("illposed", {}).get("reframed", "-"), fd.get("n_illposed", "-")),
                    "trap_repeat": kn(fd.get("traps", {}).get("repeated", "-"), fd.get("n_traps", "-")),
                    "judge": m.get("judge"), "judge_agreement": m.get("judge_agreement"),
                    "params_abstained": m["sections"].get("mechanism", {}).get("params_abstained"),
                    "params_fabricated": m["sections"].get("mechanism", {}).get("params_fabricated"),
                    "protocol": m["sections"].get("protocol", {}).get("score"),
                    "protocol_status": sc["section_status"].get("protocol")})
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--runs-root", default=str(ROOT / "runs"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rows = load_runs(Path(a.runs_root) / a.tag)
    summ = summarise(rows)
    v1 = [r for r in summ if "vector" not in r]
    v2 = [r for r in summ if "vector" in r]
    tables = []
    if v1:
        tables.append(f"## per model x tier (v1)\n\n{md_table(v1)}")
    if v2:
        tables.append(f"## per model x tier (v2)\n\n{md_table(v2)}")
    if not tables:
        tables.append("## per model x tier\n\n(no runs)")
    per_run = [_per_run(run_dir, e, sc) for run_dir, e, sc in rows]
    text = f"# runs/{a.tag}\n\n" + "\n\n".join(tables) + f"\n\n## per run\n\n```\n{json.dumps(per_run, indent=1)}\n```\n"
    out = Path(a.out) if a.out else ROOT / "results" / a.tag / "summary.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
