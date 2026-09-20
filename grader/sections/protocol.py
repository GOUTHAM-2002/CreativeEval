"""Protocol section: unknown type codes, STATUS word order, scales, flag bits, v3.4 change, held-out frames."""
from grader.common import acc, is_num, r9

try:
    from grader.sections.decipher import _heldout
except ImportError:  # pragma: no cover
    from grader.common import delta_s, norm_zone, parse_iso

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


DEFAULT_MIX = {"types_acc": 0.30, "status_words": 0.10, "scales": 0.15, "flag_bits": 0.10, "v34": 0.05, "heldout_mean": 0.30}
SCALE_KEYS = ("temp_scale", "temp_offset", "press_scale")


def _hex(k):
    s = str(k).strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    s = s.lstrip("0")
    return s.zfill(2) if s else "00"


def _lab(v):
    return str(v).strip().upper() if isinstance(v, str) else v


def score(ans, truth, cfg):
    missing = not isinstance(ans, dict) or not ans
    ans = ans if isinstance(ans, dict) else {}
    vac = cfg.get("vacuous_component_score", 1.0)
    mix = dict(DEFAULT_MIX, **(cfg.get("section_mix", {}).get("protocol") or {}))

    known = {_hex(k.split(":", 1)[1]) for k in truth.get("known", []) if str(k).startswith("type:")}
    known |= {_hex(k) for k in truth.get("unscored_types", [])}
    tt = {_hex(k): v for k, v in truth["types"].items()}
    pt = {_hex(k): _lab(v) for k, v in (ans.get("types") or {}).items()} if isinstance(ans.get("types"), dict) else {}
    types = {}
    for code, label in tt.items():
        if code in known:
            continue
        types[code] = {"pred": pt.get(code), "value": label, "hit": pt.get(code) == label}
    t_hits, n_types = sum(v["hit"] for v in types.values()), len(types)
    extra = sorted(c for c in pt if c not in tt)

    sw_pred = ans.get("status_words")
    sw_norm = [_lab(x) for x in sw_pred] if isinstance(sw_pred, list) else None
    sw_hit = sw_norm == list(truth["status_words"])
    sw_pts = 1.0 if sw_hit else 0.0

    scales = {}
    for k in SCALE_KEYS:
        pv = ans.get(k)
        scales[k] = {"pred": pv, "value": truth[k], "hit": bool(is_num(pv) and abs(pv - truth[k]) < 1e-9)}
    s_hits, n_scales = sum(v["hit"] for v in scales.values()), len(scales)

    pf = ans.get("flag_bits") if isinstance(ans.get("flag_bits"), dict) else {}
    pf = {_lab(k): v for k, v in pf.items()}
    flags = {}
    for label, bit in truth["flag_bits"].items():
        pv = pf.get(label)
        flags[label] = {"pred": pv, "value": bit, "hit": bool(is_num(pv) and pv == int(pv) and int(pv) == bit)}
    f_hits, n_flags = sum(v["hit"] for v in flags.values()), len(flags)

    v34_pred = ans.get("v34_change")
    v34 = 1.0 if v34_pred == truth["v34_change"] else 0.0

    frames, full, n_held, held_total, dup = _heldout(ans.get("heldout"), truth.get("heldout", []))
    t_acc, s_acc, f_acc, h_mean = acc(t_hits, n_types, vac), acc(s_hits, n_scales, vac), acc(f_hits, n_flags, vac), acc(held_total, n_held, vac)
    total = (mix["types_acc"] * t_acc + mix["status_words"] * sw_pts + mix["scales"] * s_acc
             + mix["flag_bits"] * f_acc + mix["v34"] * v34 + mix["heldout_mean"] * h_mean)
    if missing:
        total = 0.0
    return {
        "score": r9(total), "missing": missing,
        "types": types, "types_hits": t_hits, "n_unknown_types": n_types, "types_acc": t_acc,
        "extra_types": len(extra), "extra_types_list": extra,
        "status_words": {"pred": sw_pred, "value": list(truth["status_words"]), "hit": sw_hit}, "status_words_pts": sw_pts,
        "scales": scales, "scales_hits": s_hits, "n_scales": n_scales, "scales_acc": s_acc,
        "flag_bits": flags, "flag_hits": f_hits, "n_flags": n_flags, "flag_acc": f_acc,
        "v34": {"pred": v34_pred, "value": truth["v34_change"], "pts": v34},
        "heldout": frames, "heldout_frames_full": full, "n_heldout": n_held, "heldout_mean": h_mean,
        "heldout_duplicate_seq": dup,
    }
