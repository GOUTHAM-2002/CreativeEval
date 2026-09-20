"""Calibration: per-run Brier over sections with a confidence value; pooled ECE helper."""
from grader.common import is_num, r9

SECTIONS = ("mechanism", "notation", "causal_chain", "timeline")


def score(confidence, solved, cfg, sections=SECTIONS):
    confidence = confidence if isinstance(confidence, dict) else {}
    per, sq, missing = {}, [], 0
    for s in sections:
        c = confidence.get(s)
        c_s = 1.0 if solved.get(s) else 0.0
        if is_num(c) and 0.0 <= c <= 1.0:
            sq.append((c - c_s) ** 2)
            per[s] = {"confidence": c, "solved": bool(solved.get(s)), "sq_err": (c - c_s) ** 2}
        else:
            missing += 1
            per[s] = {"confidence": None, "solved": bool(solved.get(s)), "sq_err": None}
    return {"sections": per, "brier": r9(sum(sq) / len(sq)) if sq else None,
            "n_scored": len(sq), "confidence_missing": missing}


def pool(score_jsons, bins=5):
    pairs = []
    for sj in score_jsons:
        for d in sj.get("measured", {}).get("calibration", {}).get("sections", {}).values():
            if d.get("confidence") is not None:
                pairs.append((float(d["confidence"]), 1.0 if d["solved"] else 0.0))
    n = len(pairs)
    if n == 0:
        return {"ece": None, "mean_conf": None, "mean_solved": None, "n": 0, "bins": []}
    buckets = [[] for _ in range(bins)]
    for c, s in pairs:
        buckets[min(int(c * bins), bins - 1)].append((c, s))
    ece, rows = 0.0, []
    for i, b in enumerate(buckets):
        if not b:
            continue
        mc, ms = sum(c for c, _ in b) / len(b), sum(s for _, s in b) / len(b)
        ece += len(b) / n * abs(mc - ms)
        rows.append({"lo": i / bins, "hi": (i + 1) / bins, "n": len(b), "mean_conf": mc, "mean_solved": ms})
    return {"ece": r9(ece), "mean_conf": sum(c for c, _ in pairs) / n,
            "mean_solved": sum(s for _, s in pairs) / n, "n": n, "bins": rows}
