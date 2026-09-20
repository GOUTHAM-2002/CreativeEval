"""Shared helpers for the grader sections."""
from datetime import datetime, timezone


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def norm_id(s):
    return str(s).strip().lower()


def norm_zone(z):
    return str(z).strip().upper()


def parse_iso(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t[-1:] in ("Z", "z"):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def delta_s(a, b):
    if a is None or b is None:
        return None
    return abs((a - b).total_seconds())


def acc(hits, n, vacuous):
    return hits / n if n else vacuous


def prf(hits, n_pred, n_truth, vacuous):
    if n_pred == 0 and n_truth == 0:
        return vacuous, vacuous, vacuous
    p = hits / n_pred if n_pred else 0.0
    r = hits / n_truth if n_truth else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def set_report(pred, truth, vacuous):
    hits = len(pred & truth)
    p, r, f = prf(hits, len(pred), len(truth), vacuous)
    return {"hits": hits, "n_pred": len(pred), "n_truth": len(truth),
            "precision": p, "recall": r, "f1": f,
            "missing": sorted(truth - pred), "extra": sorted(pred - truth)}


def r9(x):
    return None if x is None else round(x, 9)
