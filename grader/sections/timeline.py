"""Timeline section: greedy event matching, clock offsets, false-claim quotes."""
import re
from difflib import SequenceMatcher
from pathlib import Path

from grader.common import acc, delta_s, is_num, norm_id, parse_iso, prf, r9

_WS = re.compile(r"\s+")


def _norm_text(s):
    return _WS.sub(" ", str(s)).strip().lower()


def _events(pred, truth, vac):
    tp = [(norm_id(e["actor"]), norm_id(e["action"]), parse_iso(e["t"]), e["tol_s"]) for e in truth]
    pp, unparse = [], 0
    for e in pred or []:
        if not isinstance(e, dict):
            continue
        t = parse_iso(e.get("t"))
        unparse += t is None
        pp.append((norm_id(e.get("actor", "")), norm_id(e.get("action", "")), t))
    cands = []
    for pi, (pa, pc, pt) in enumerate(pp):
        for ti, (ta, tc, tt, tol) in enumerate(tp):
            d = delta_s(pt, tt)
            if pa == ta and pc == tc and d is not None and d <= tol:
                cands.append((d, pi, ti))
    cands.sort()
    p_used, t_used, pairs = set(), set(), []
    for d, pi, ti in cands:
        if pi in p_used or ti in t_used:
            continue
        p_used.add(pi)
        t_used.add(ti)
        pairs.append({"pred_index": pi, "event_id": truth[ti]["event_id"], "delta_s": d})
    wrong_actor = wrong_time = 0
    for pi, (pa, pc, pt) in enumerate(pp):
        if pi in p_used:
            continue
        free = [(ta, tc, tt, tol) for ti, (ta, tc, tt, tol) in enumerate(tp) if ti not in t_used]
        if any(pc == tc and (d := delta_s(pt, tt)) is not None and d <= tol for ta, tc, tt, tol in free):
            wrong_actor += 1
        elif any(pa == ta and pc == tc for ta, tc, tt, tol in free):
            wrong_time += 1
    matched, n_pred, n_truth = len(pairs), len(pp), len(tp)
    precision, recall, f1 = prf(matched, n_pred, n_truth, vac)
    return {"matched": matched, "n_truth": n_truth, "n_pred": n_pred, "recall": recall, "precision": precision,
            "f1": f1, "wrong_actor": wrong_actor, "wrong_time": wrong_time, "unparseable_t": unparse,
            "pairs": pairs, "unmatched_truth": [truth[ti]["event_id"] for ti in range(n_truth) if ti not in t_used]}


def _offsets(pred, truth, tol, vac):
    pred = pred if isinstance(pred, dict) else {}
    per, hits = {}, 0
    for ch, v in truth.items():
        p = pred.get(ch)
        hit = bool(is_num(p) and abs(p - v) <= tol)
        hits += hit
        per[ch] = {"pred": p if is_num(p) else None, "value": v, "hit": hit}
    return {"channels": per, "hits": hits, "n_channels": len(truth), "acc": acc(hits, len(truth), vac),
            "extra_channels": sorted(set(pred) - set(truth))}


def _claim_text(claim, evidence_dir):
    if evidence_dir is not None:
        p = Path(evidence_dir) / claim.get("path", "")
        try:
            doc = p.read_text(encoding="utf-8", errors="replace")
            s, e = claim["span"]
            if 0 <= s < e <= len(doc):
                return doc[s:e], "evidence"
        except (OSError, TypeError, ValueError):
            pass
    return claim["text"], "truth"


def _overlap(q, t):
    if not q or not t:
        return 0.0
    m = SequenceMatcher(None, q, t, autojunk=False).find_longest_match(0, len(q), 0, len(t))
    return m.size / min(len(q), len(t))


def _claims(pred, truth, evidence_dir, min_overlap, vac):
    tc = []
    for c in truth:
        text, src = _claim_text(c, evidence_dir)
        tc.append((norm_id(c["doc_id"]), _norm_text(text), src))
    pc = [(norm_id(c.get("doc_id", "")), _norm_text(c.get("quote", ""))) for c in pred or [] if isinstance(c, dict)]
    cands = []
    for pi, (pd, pq) in enumerate(pc):
        for ti, (td, tt, _) in enumerate(tc):
            if pd == td:
                ov = _overlap(pq, tt)
                if ov >= min_overlap:
                    cands.append((-ov, pi, ti))
    cands.sort()
    p_used, t_used, match = set(), set(), {}
    for nov, pi, ti in cands:
        if pi in p_used or ti in t_used:
            continue
        p_used.add(pi)
        t_used.add(ti)
        match[ti] = (pi, -nov)
    per = []
    for ti, c in enumerate(truth):
        pi, ov = match.get(ti, (None, None))
        per.append({"claim_id": c["claim_id"], "doc_id": c["doc_id"], "text_source": tc[ti][2],
                    "matched_pred_index": pi, "overlap": ov, "hit": pi is not None})
    hits = len(match)
    precision, recall, f1 = prf(hits, len(pc), len(tc), vac)
    return {"claims": per, "hits": hits, "n_truth": len(tc), "n_pred": len(pc),
            "precision": precision, "recall": recall, "f1": f1,
            "unmatched_pred_indices": [pi for pi in range(len(pc)) if pi not in p_used]}


def score(ans, truth, cfg, evidence_dir=None):
    ans = ans if isinstance(ans, dict) else {}
    vac = cfg["vacuous_component_score"]
    mix = cfg["section_mix"]["timeline"]
    ev = _events(ans.get("events"), truth["events"], vac)
    off = _offsets(ans.get("clock_offsets_min"), truth["clock_offsets_min"], cfg["offset_tol_min"], vac)
    cl = _claims(ans.get("false_claims"), truth["false_claims"], evidence_dir, cfg["claim_min_overlap"], vac)
    total = (mix["f1"] * ev["f1"] + mix["offsets_acc"] * off["acc"] + mix["claims_f1"] * cl["f1"])
    return {"score": r9(total), "events": ev, "offsets": off, "claims": cl}
