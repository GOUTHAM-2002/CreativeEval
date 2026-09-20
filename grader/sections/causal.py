"""Causal-chain section: node/edge/lot set overlap, roots, decoys, excursion window."""
import re

from grader.common import delta_s, norm_id, norm_zone, parse_iso, r9, set_report


def _ids(lst, pat, bad):
    out = set()
    for x in lst or []:
        if isinstance(x, (list, tuple, dict)):
            continue
        i = norm_id(x)
        (out.add if pat.match(i) else bad.append)(i)
    return out


def _edges(lst, pat, bad):
    out = set()
    for e in lst or []:
        if isinstance(e, (list, tuple)) and len(e) == 2:
            a, b = norm_id(e[0]), norm_id(e[1])
            if pat.match(a) and pat.match(b):
                out.add((a, b))
            else:
                bad.extend(i for i in (a, b) if not pat.match(i))
    return out


def _excursion(pred, truth, one_bound_pts):
    pred = pred if isinstance(pred, dict) else {}
    tol = truth.get("tol_s", 0)
    zone_ok = norm_zone(pred.get("zone", "")) == norm_zone(truth["zone"])
    ds = delta_s(parse_iso(pred.get("start")), parse_iso(truth["start"]))
    de = delta_s(parse_iso(pred.get("end")), parse_iso(truth["end"]))
    start_ok = bool(ds is not None and ds <= tol)
    end_ok = bool(de is not None and de <= tol)
    pts = 0.0
    if zone_ok and start_ok and end_ok:
        pts = 1.0
    elif zone_ok and (start_ok or end_ok):
        pts = one_bound_pts
    return {"pred": pred, "value": {k: truth[k] for k in ("zone", "start", "end")}, "tol_s": tol,
            "zone_ok": zone_ok, "start_ok": start_ok, "end_ok": end_ok,
            "start_delta_s": ds, "end_delta_s": de, "pts": pts}


def score(ans, truth, cfg):
    ans = ans if isinstance(ans, dict) else {}
    vac = cfg["vacuous_component_score"]
    mix = cfg["section_mix"]["causal_chain"]
    pat = re.compile(cfg["id_prefix_pattern"])
    bad = []

    t_nodes = {norm_id(x) for x in truth["nodes"]}
    t_edges = {(norm_id(a), norm_id(b)) for a, b in truth["edges"]}
    t_roots = {norm_id(x) for x in truth["roots"]}
    t_decoys = {norm_id(x) for x in truth["decoys"]}
    t_lots = {norm_id(x) for x in truth["affected_lots"]}

    p_nodes = _ids(ans.get("nodes"), pat, bad)
    p_edges = _edges(ans.get("edges"), pat, bad)
    p_roots = _ids(ans.get("roots"), pat, bad)
    p_rej = _ids(ans.get("decoys_rejected"), pat, bad)
    p_lots = _ids(ans.get("affected_lots"), pat, bad)

    nodes, edges, lots = (set_report(p_nodes, t_nodes, vac), set_report(p_edges, t_edges, vac),
                          set_report(p_lots, t_lots, vac))
    edges["missing"] = [list(e) for e in edges["missing"]]
    edges["extra"] = [list(e) for e in edges["extra"]]
    exc = _excursion(ans.get("excursion"), truth["excursion"], cfg["excursion_one_bound_pts"])
    decoys_in = sorted(p_nodes & t_decoys)

    total = (mix["f1_nodes"] * nodes["f1"] + mix["f1_edges"] * edges["f1"]
             + mix["f1_lots"] * lots["f1"] + mix["excursion"] * exc["pts"])
    return {
        "score": r9(total),
        "nodes": nodes, "edges": edges, "affected_lots": lots,
        "roots_hits": len(p_roots & t_roots), "n_roots": len(t_roots), "n_roots_pred": len(p_roots),
        "roots_missing": sorted(t_roots - p_roots), "roots_extra": sorted(p_roots - t_roots),
        "decoys_included": len(decoys_in), "decoys_included_list": decoys_in,
        "decoys_rejected_hits": len(p_rej & t_decoys), "n_decoys": len(t_decoys),
        "excursion": exc, "unmatched_ids": sorted(set(bad)),
    }
