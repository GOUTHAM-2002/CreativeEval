"""Notation section: glossary over unknown roots, affixes, v3.4 change, held-out frames."""
from grader.common import acc, delta_s, is_num, norm_id, norm_zone, parse_iso, r9


def _heldout(pred_frames, truth_frames):
    seen, dup = {}, 0
    for f in pred_frames or []:
        if not isinstance(f, dict):
            continue
        s = f.get("seq")
        if s in seen:
            dup += 1
        else:
            seen[s] = f
    frames, full, total = [], 0, 0.0
    for tf in truth_frames:
        pf = seen.get(tf["seq"])
        checks = {}
        if pf is not None:
            checks["event"] = pf.get("event") == tf["event"]
            checks["zone"] = norm_zone(pf.get("zone", "")) == norm_zone(tf["zone"])
            if tf.get("value") is not None:
                pv = pf.get("value")
                checks["value"] = bool(is_num(pv) and abs(pv - tf["value"]) <= tf.get("tol_value", 0.0))
            if tf.get("ts") is not None:
                d = delta_s(parse_iso(pf.get("ts")), parse_iso(tf["ts"]))
                checks["ts"] = bool(d is not None and d <= tf["tol_s"])
        fs = sum(checks.values()) / len(checks) if checks else 0.0
        full += fs == 1.0
        total += fs
        frames.append({"seq": tf["seq"], "present": pf is not None, "checks": checks, "score": fs})
    n = len(truth_frames)
    return frames, full, n, total, dup


def score(ans, truth, cfg):
    ans = ans if isinstance(ans, dict) else {}
    vac = cfg["vacuous_component_score"]
    mix = cfg["section_mix"]["notation"]

    known = {norm_id(r) for r in truth["known_roots"]} | {norm_id(r) for r in truth.get("unscored_roots", [])}
    tg = {norm_id(k): v for k, v in truth["glossary"].items()}
    pg = {norm_id(k): v for k, v in (ans.get("glossary") or {}).items()}
    glossary = {}
    for r, label in tg.items():
        if r in known:
            continue
        glossary[r] = {"pred": pg.get(r), "value": label, "hit": pg.get(r) == label}
    g_hits, n_unknown = sum(v["hit"] for v in glossary.values()), len(glossary)
    extra = sorted(r for r in pg if r not in tg)

    ta = {norm_id(k).lstrip("-"): v for k, v in truth["affixes"].items()}
    pa = {norm_id(k).lstrip("-"): v for k, v in (ans.get("affixes") or {}).items()}
    affixes = {a: {"pred": pa.get(a), "value": role, "hit": pa.get(a) == role} for a, role in ta.items()}
    a_hits, n_affixes = sum(v["hit"] for v in affixes.values()), len(affixes)

    v34_pred = ans.get("v34_change")
    v34 = 1.0 if v34_pred == truth["v34_change"] else 0.0

    frames, full, n_held, held_total, dup = _heldout(ans.get("heldout"), truth["heldout"])
    g_acc, a_acc, h_mean = acc(g_hits, n_unknown, vac), acc(a_hits, n_affixes, vac), acc(held_total, n_held, vac)
    total = mix["glossary_acc"] * g_acc + mix["affix_acc"] * a_acc + mix["heldout_mean"] * h_mean + mix["v34"] * v34
    return {
        "score": r9(total),
        "glossary": glossary, "glossary_hits": g_hits, "n_unknown": n_unknown, "glossary_acc": g_acc,
        "extra_roots": len(extra), "extra_roots_list": extra,
        "affixes": affixes, "affix_hits": a_hits, "n_affixes": n_affixes, "affix_acc": a_acc,
        "v34": {"pred": v34_pred, "value": truth["v34_change"], "pts": v34},
        "heldout": frames, "heldout_frames_full": full, "n_heldout": n_held, "heldout_mean": h_mean,
        "heldout_duplicate_seq": dup,
    }
