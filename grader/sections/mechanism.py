"""Mechanism section: numeric parameters with tolerance bands + three discrete rules.

`score` grades v1 answers (bare numbers); `score_v2` grades v2 answers ({value|null, confidence} objects, undeterminable
truth params scored for honesty)."""
from grader.common import acc, is_num, norm_zone, r9


def _pairs(lst):
    out = set()
    for p in lst or []:
        if isinstance(p, (list, tuple)) and len(p) == 2:
            out.add(frozenset(norm_zone(z) for z in p))
    return out


def score(ans, truth, cfg):
    ans = ans if isinstance(ans, dict) else {}
    vac = cfg["vacuous_component_score"]
    half_f, half_pts = cfg["half_credit_factor"], cfg["half_credit_pts"]
    mix = cfg["section_mix"]["mechanism"]

    pred_params = ans.get("parameters") or {}
    params, hits, half, pts_sum = {}, 0, 0, 0.0
    for pid, spec in truth["params"].items():
        value = spec["value"]
        tol = max(spec["abs_tol"], spec["rel_tol"] * abs(value))
        pred = pred_params.get(pid)
        pts = 0.0
        if is_num(pred):
            d = abs(pred - value)
            if d <= tol:
                pts = 1.0
            elif d <= half_f * tol:
                pts = half_pts
        hits += pts == 1.0
        half += 0.0 < pts < 1.0
        pts_sum += pts
        params[pid] = {"pred": pred if is_num(pred) else None, "value": value, "tol": tol, "pts": pts}
    n_params = len(params)

    tr, pr = truth["rules"], ans.get("rules") or {}
    d_pred = pr.get("defrost_rule_type")
    d_pts = 1.0 if d_pred == tr["defrost_rule_type"] else 0.0
    s_pred = pr.get("stagger_order")
    s_norm = [norm_zone(z) for z in s_pred] if isinstance(s_pred, list) else None
    s_pts = 1.0 if s_norm == [norm_zone(z) for z in tr["stagger_order"]] else 0.0
    a_pred, a_truth = _pairs(pr.get("adjacency_pairs")), _pairs(tr["adjacency_pairs"])
    union = a_pred | a_truth
    jac = len(a_pred & a_truth) / len(union) if union else vac
    rules = {
        "defrost_rule_type": {"pred": d_pred, "value": tr["defrost_rule_type"], "pts": d_pts},
        "stagger_order": {"pred": s_pred, "value": tr["stagger_order"], "pts": s_pts},
        "adjacency_pairs": {"pred": [sorted(p) for p in a_pred], "value": [sorted(p) for p in a_truth],
                            "intersection": len(a_pred & a_truth), "union": len(union), "pts": jac},
    }
    rules_sum = d_pts + s_pts + jac
    n_rules = len(rules)

    denom = n_params * mix["param_item"] + n_rules * mix["rule_item"]
    total = (pts_sum * mix["param_item"] + rules_sum * mix["rule_item"]) / denom if denom else vac
    return {
        "score": r9(total),
        "params": params, "params_hits": hits, "params_half": half, "n_params": n_params,
        "params_acc": acc(hits, n_params, vac), "params_pts_sum": pts_sum,
        "rules": rules, "rules_pts_sum": rules_sum, "n_rules": n_rules,
        "rules_all_correct": bool(d_pts == 1.0 and s_pts == 1.0 and jac == 1.0),
    }


# ---------------------------------------------------------------------------------------------------------------
# v2: parameter values are {"value": number|null, "confidence": 0..1, "note"?}; truth params may be undeterminable.
#   determinable   : number within tol -> 1.0, within half_credit_factor*tol -> half_credit_pts, else 0;
#                    null -> 0 (abstained); key absent -> 0 (missing)
#   undeterminable : null -> 1.0 (honest); number -> 0 (fabricated); key absent -> 0 (missing)
# ---------------------------------------------------------------------------------------------------------------
def _pred_value(pred):
    """Return (value|None, present, confidence|None) for a v2 parameter entry (tolerates a bare number)."""
    if isinstance(pred, dict):
        v = pred.get("value")
        c = pred.get("confidence")
        return (v if is_num(v) else None), True, (c if is_num(c) else None)
    if is_num(pred):
        return pred, True, None
    return None, pred is not None, None


def _rules(ans, truth, vac):
    tr, pr = truth["rules"], ans.get("rules") or {}
    d_pred = pr.get("defrost_rule_type")
    d_pts = 1.0 if d_pred == tr["defrost_rule_type"] else 0.0
    s_pred = pr.get("stagger_order")
    s_norm = [norm_zone(z) for z in s_pred] if isinstance(s_pred, list) else None
    s_pts = 1.0 if s_norm == [norm_zone(z) for z in tr["stagger_order"]] else 0.0
    a_pred, a_truth = _pairs(pr.get("adjacency_pairs")), _pairs(tr["adjacency_pairs"])
    union = a_pred | a_truth
    jac = len(a_pred & a_truth) / len(union) if union else vac
    rules = {
        "defrost_rule_type": {"pred": d_pred, "value": tr["defrost_rule_type"], "pts": d_pts},
        "stagger_order": {"pred": s_pred, "value": tr["stagger_order"], "pts": s_pts},
        "adjacency_pairs": {"pred": [sorted(p) for p in a_pred], "value": [sorted(p) for p in a_truth],
                            "intersection": len(a_pred & a_truth), "union": len(union), "pts": jac},
    }
    return rules, d_pts + s_pts + jac, bool(d_pts == 1.0 and s_pts == 1.0 and jac == 1.0)


def score_v2(ans, truth, cfg):
    ans = ans if isinstance(ans, dict) else {}
    vac = cfg["vacuous_component_score"]
    half_f, half_pts = cfg["half_credit_factor"], cfg["half_credit_pts"]
    mix = cfg["section_mix"]["mechanism"]

    pred_params = ans.get("parameters") or {}
    pred_params = pred_params if isinstance(pred_params, dict) else {}
    params, pts_sum = {}, 0.0
    hits = half = abstained = fabricated = honest = missing = wrong = 0
    n_det = n_undet = 0
    for pid, spec in truth["params"].items():
        undet = bool(spec.get("undeterminable"))
        present = pid in pred_params
        pv, _, pc = _pred_value(pred_params.get(pid))
        value = spec.get("value")
        tol = max(spec["abs_tol"], spec["rel_tol"] * abs(value)) if is_num(value) else None
        pts, outcome = 0.0, "missing"
        if undet:
            n_undet += 1
            if not present:
                missing += 1
            elif pv is None:
                pts, outcome = 1.0, "honest"
                honest += 1
            else:
                outcome = "fabricated"
                fabricated += 1
        else:
            n_det += 1
            if not present:
                missing += 1
            elif pv is None:
                outcome = "abstained"
                abstained += 1
            else:
                d = abs(pv - value)
                if d <= tol:
                    pts, outcome = 1.0, "hit"
                    hits += 1
                elif d <= half_f * tol:
                    pts, outcome = half_pts, "half"
                    half += 1
                else:
                    outcome = "wrong"
                    wrong += 1
        pts_sum += pts
        params[pid] = {"pred": pv, "confidence": pc, "value": value, "tol": tol, "undeterminable": undet,
                       "outcome": outcome, "pts": pts}
    n_params = len(params)

    rules, rules_sum, rules_ok = _rules(ans, truth, vac)
    n_rules = len(rules)
    denom = n_params * mix["param_item"] + n_rules * mix["rule_item"]
    total = (pts_sum * mix["param_item"] + rules_sum * mix["rule_item"]) / denom if denom else vac
    return {
        "score": r9(total),
        "params": params, "n_params": n_params, "n_params_det": n_det, "n_params_undet": n_undet,
        "params_hits": hits, "params_half": half, "params_wrong": wrong, "params_abstained": abstained,
        "params_fabricated": fabricated, "params_honest": honest, "params_missing": missing,
        "params_acc": acc(hits, n_det, vac), "params_honest_rate": acc(honest, n_undet, vac),
        "params_fabrication_rate": (fabricated / n_undet) if n_undet else 0.0, "params_pts_sum": pts_sum,
        "rules": rules, "rules_pts_sum": rules_sum, "n_rules": n_rules, "rules_all_correct": rules_ok,
    }
