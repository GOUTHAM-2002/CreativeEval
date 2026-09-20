# Identifiability check: recover every mechanism parameter from the EVIDENCE alone, given the truth
# notation mapping, clock epochs and adjacency (i.e. assuming a correct decipherment), and report the
# error against truth and whether it lands inside the graded tolerance. Host-side only.
from __future__ import annotations
import argparse
import csv
import datetime as dt
import json
import math
import random
import re
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gen.notation import Notation  # noqa: E402

LINE_RE = re.compile(r'^(\S+) INFO gateway recv=(\S+) ctrl=(\S+) seq=(\d+) raw="(.*?)" decoded=')


def parse_iso(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def load_frames(ev: Path, nt: Notation, sp: dict, epochs: dict, ctrl_zone: dict):
    """Decode every gateway frame (+ the fault snapshot) with the truth decoder. Time = controller clock mapped
    through the epochs (minutes, wall-clock UTC)."""
    def wall(ctrl, t_ctrl):
        eps = epochs[ctrl]
        for i, e in enumerate(eps):
            cand = parse_iso(e["epoch"]) + dt.timedelta(minutes=t_ctrl)
            lo = parse_iso(e["from"]) - dt.timedelta(minutes=1)
            hi = parse_iso(eps[i + 1]["from"]) if i + 1 < len(eps) else None
            if cand >= lo and (hi is None or cand < hi):
                return cand
        return None

    frames = []
    def add(raw, recv=None):
        try:
            d = nt.decode(raw, setpoint=None)
        except ValueError:
            return
        z = ctrl_zone[d["ctrl_id"]]
        if any(c.get("kind") == "READ" and c.get("value") is None for c in d["clauses"]):
            try:
                d = nt.decode(raw, setpoint=sp[z])
            except ValueError:
                return
        t = wall(d["ctrl_id"], d["t_ctrl_min"])
        if t is None:
            return
        frames.append({"zone": z, "t": t, "seq": d["seq"], "fw": d["fw"], "clauses": d["clauses"], "recv": recv})
    for line in open(ev / "deploy" / "logs" / "gateway.log", errors="replace"):
        m = LINE_RE.match(line)
        if m:
            add(m.group(5).encode().decode("unicode_escape"), parse_iso(m.group(2)))
    for p in (ev / "controller").glob("*_fault_snapshot.txt"):
        for line in open(p):
            if line.startswith("#") or not line.strip():
                continue
            add(line.split(" ", 1)[1].strip())
    # de-duplicate (snapshot overlaps the log) and sort
    seen = set()
    out = []
    for f in frames:
        key = (f["zone"], f["seq"], f["t"])
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    out.sort(key=lambda f: (f["t"], f["zone"]))
    return out


def temp_of(clause, fw, setpoint):
    v = clause.get("value")
    raw = clause.get("raw")
    if v is not None:
        return v
    if raw is None:
        return None
    return setpoint + (raw - 500) / 10.0


def series(frames, sp):
    """Per zone: list of (t_min, reported_air_temp, comp_on, state) from periodic frames; events list."""
    per = defaultdict(list)
    events = defaultdict(list)
    t0 = min(f["t"] for f in frames)
    for f in frames:
        tm = (f["t"] - t0).total_seconds() / 60.0
        z = f["zone"]
        air, state = None, None
        for c in f["clauses"]:
            if c["kind"] == "READ" and c["sensor"] == "AIR_TEMP":
                air = c.get("value")
                if air is None:
                    continue
            elif c["kind"] == "STATE":
                state = c["state"]
            elif c["kind"] == "EVENT":
                events[z].append((tm, c["event"], c.get("value")))
        if air is not None and state is not None:
            per[z].append((tm, air, 1 if state in ("RUN", "RECOVERY") else 0, state))
    for z in per:
        per[z].sort()
    return per, events, t0


def door_state(events, zone, total, max_open=45):
    # 0 closed, 1 open, -1 ambiguous (an open with no close within max_open minutes: a lost frame or a long prop)
    d = [0] * (total + 2)
    cur, last = 0, 0
    for tm, ev, _ in sorted(events[zone]):
        if ev in ("DOOR_OPEN", "DOOR_CLOSE"):
            for k in range(int(last), min(int(tm), total + 1)):
                d[k] = cur if (cur == 0 or k - last <= max_open) else -1
            cur, last = (1 if ev == "DOOR_OPEN" else 0), tm
    for k in range(int(last), total + 1):
        d[k] = cur if (cur == 0 or k - last <= max_open) else -1
    return d


def heater_state(events, zone, total):
    h = [0] * (total + 2)
    cur, last = 0, 0
    for tm, ev, _ in sorted(events[zone]):
        if ev in ("HEATER_ON", "HEATER_OFF"):
            for k in range(int(last), min(int(tm), total + 1)):
                h[k] = cur
            cur, last = (1 if ev == "HEATER_ON" else 0), tm
    for k in range(int(last), total + 1):
        h[k] = cur
    return h


def lstsq(X, y):
    import itertools
    n, p = len(X), len(X[0])
    A = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(p)] for a in range(p)]
    B = [sum(X[i][a] * y[i] for i in range(n)) for a in range(p)]
    # gaussian elimination
    M = [row[:] + [B[i]] for i, row in enumerate(A)]
    for c in range(p):
        piv = max(range(c, p), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        if abs(M[c][c]) < 1e-12:
            return None
        for r in range(p):
            if r != c:
                f = M[r][c] / M[c][c]
                for k in range(c, p + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][p] / M[i][i] for i in range(p)]


def estimate(ev: Path, truth: dict, world_names: dict | None = None) -> dict:
    nt_t = truth["notation"]
    zones = sorted({z for z in truth["mechanism"]["params"] if z.startswith("k_cool.")}, key=lambda s: s)
    zones = [z.split(".")[1] for z in zones]
    q = json.load(open(ev / "questions.json"))
    ctrl = q["controllers"]
    ctrl_zone = {v: k for k, v in ctrl.items()}
    sp = {}
    cfg = json.load(open(ev / "repo" / "deploy" / "config.json"))
    for z, v in cfg["ZONES"]["setpoints"].items():
        sp[z] = float(v)
    # rebuild the truth decoder exactly as the generator did (seeded); verify it matches the recorded glossary
    rng_w = random.Random(f"notation:{truth['seed']}:{truth['tier']}")
    if "types" in (truth.get("protocol") or {}):
        from gen.protocol import Protocol
        nt = Protocol(rng_w, zones=q["zones"], controllers=ctrl)
        assert nt.truth()["types"] == truth["protocol"]["types"], "protocol reconstruction mismatch"
        nt_t = truth["protocol"]
    else:
        nt = Notation(rng_w, zones=q["zones"], controllers=ctrl)
        assert nt.truth()["glossary"] == nt_t["glossary"], "notation reconstruction mismatch"
    frames = load_frames(ev, nt, sp, nt_t["controller_clock_epochs"], ctrl_zone)
    per, events, t0 = series(frames, sp)
    total = int(max(x[0] for z in per for x in per[z])) + 5
    # ambient from the submeter
    amb = {}
    for r in csv.DictReader(open(ev / "people" / "utility_submeter.csv")):
        tm = (parse_iso(r["timestamp"]) - t0).total_seconds() / 60.0
        amb.setdefault(int(tm // 15) * 15, []).append(float(r["panel_room_temp_c"]))
    amb = {k: st.mean(v) for k, v in amb.items()}
    def Ta(tm):
        k = int(tm // 15) * 15
        return amb.get(k, amb.get(k - 15, 18.0))
    adjacency = truth["mechanism"]["rules"]["adjacency_pairs"]
    adj = defaultdict(set)
    for a, b in adjacency:
        adj[a].add(b); adj[b].add(a)
    door = {z: door_state(events, z, total) for z in zones}
    heat = {z: heater_state(events, z, total) for z in zones}
    # quick lookup of neighbour temps by minute (nearest sample)
    samp = {z: {int(round(x[0])): x[1] for x in per[z]} for z in zones}
    def temp_at(z, tm):
        for d in (0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5):
            v = samp[z].get(int(round(tm)) + d)
            if v is not None:
                return v
        return None

    def temp_interp(z, tm):
        import bisect
        ts = [x[0] for x in per[z]]
        i = bisect.bisect_left(ts, tm)
        if i == 0 or i >= len(ts) or ts[i] - ts[i - 1] > 7:
            return None
        (ta, ra), (tb, rb) = per[z][i - 1][:2], per[z][i][:2]
        return ra + (rb - ra) * (tm - ta) / (tb - ta)
    est, detail = {}, {}
    def linefit_at(seg, t_eval):
        # least-squares line through (t, r) samples, evaluated at t_eval
        n = len(seg)
        if n < 3:
            return None
        mt = sum(t for t, _ in seg) / n
        mr = sum(r for _, r in seg) / n
        sxx = sum((t - mt) ** 2 for t, _ in seg)
        if sxx == 0:
            return mr
        b = sum((t - mt) * (r - mr) for t, r in seg) / sxx
        return mr + b * (t_eval - mt)

    # --- bias from probe sheet (HH-1 assumed true per the calibration certificate; HH-2 corrected by the cert offset)
    cert = (ev / "people" / "receipts" / "calibration_certificate_handhelds.txt").read_text()
    m = re.search(r"HH-2.*?offset \+([0-9.]+)", cert)
    hh2 = float(m.group(1)) if m else 0.0
    probe_off = truth["timeline"]["clock_offsets_min"].get("probe", 0)
    diffs = defaultdict(list)
    for r in csv.DictReader(open(ev / "people" / "probe_checks_sheet.csv")):
        if not r["reading_c"]:
            continue
        tm = (parse_iso(r["device_timestamp"]) - t0).total_seconds() / 60.0 - probe_off
        if tm > 7 * 1440:
            continue          # base offset: use the first week only (a sensor may drift later in the window)
        z = r["zone"]
        seg = [(t, rr) for (t, rr, c, stt) in per[z] if abs(t - tm) <= 12]
        # local line through the surrounding samples (same compressor state on both sides), evaluated at the probe time
        if len(seg) >= 3 and len({c for (t, rr, c, stt) in per[z] if abs(t - tm) <= 12}) == 1:
            rep = linefit_at(seg, tm)
        else:
            rep = temp_interp(z, tm)
        if rep is None:
            continue
        true_probe = float(r["reading_c"]) - (hh2 if r["handheld"] == "HH-2" else 0.0)
        diffs[z].append(rep - true_probe)
    for z in zones:
        if diffs[z]:
            est[f"bias.{z}"] = st.median(diffs[z])
            detail[f"bias.{z}"] = {"n": len(diffs[z])}
    # --- H from RUN<->IDLE transitions (reported readings bracket the switching levels)
    for z in zones:
        offs, ons = [], []
        s = per[z]
        for i in range(1, len(s)):
            (t1, r1, c1, s1), (t2, r2, c2, s2) = s[i - 1], s[i]
            if t2 - t1 > 6 or heat[z][int(t1)] or door[z][int(t1)] != 0 or s1 in ("DEFROST", "LOCKOUT", "RECOVERY") or s2 in ("DEFROST", "LOCKOUT", "RECOVERY"):
                continue
            if c1 == c2:
                continue
            # samples of the segment ending at i-1 (same state, contiguous, no door/heater)
            seg = []
            j = i - 1
            while j >= 0 and len(seg) < 8 and s[j][2] == c1 and (j == i - 1 or s[j + 1][0] - s[j][0] <= 6) and not heat[z][int(s[j][0])] and door[z][int(s[j][0])] == 0:
                seg.append((s[j][0], s[j][1])); j -= 1
            v = linefit_at(seg, (t1 + t2) / 2)
            if v is None:
                continue
            (offs if c1 == 1 else ons).append(v)
        if len(offs) > 5 and len(ons) > 5:
            est[f"H.{z}"] = st.mean(ons) - st.mean(offs)
            detail[f"H.{z}"] = {"n_on": len(ons), "n_off": len(offs)}
    # --- k_cool, k_leak, door_gain, c_adj by regression on 5-min differences (pooled c_adj)
    rows_all = []
    per_zone_rows = defaultdict(list)
    for z in zones:
        s = per[z]
        for i in range(3, len(s)):
            (t1, r1, c1, s1), (t2, r2, c2, s2) = s[i - 1], s[i]
            dt_ = t2 - t1
            if not (4 <= dt_ <= 6) or c1 != c2 or heat[z][int(t1)] or heat[z][int(t2)] or s1 == "DEFROST" or s2 == "DEFROST":
                continue
            dd = door[z][int(t1)]
            if dd != door[z][int(t2)] or dd < 0:
                continue
            # regressor temperature from the samples BEFORE the interval (independent noise from r1, r2)
            prev = [s[k] for k in (i - 2, i - 3) if t1 - s[k][0] <= 12]
            if not prev:
                continue
            r_lag = sum(x[1] for x in prev) / len(prev) + (r1 - sum(x[1] for x in prev) / len(prev)) * 0.0
            # extrapolate the lagged mean to t1 using the local slope (unbiased in the noise)
            t_lag = sum(x[0] for x in prev) / len(prev)
            nb = 0.0
            ok = True
            for j in adj[z]:
                tj = temp_at(j, t1)
                if tj is None:
                    ok = False; break
                nb += (tj - r_lag)
            if not ok:
                continue
            y = (r2 - r1) / dt_
            # door-open rows: the level of the warming identifies the gain, and the lag bias during fast warming
            # would dominate, so use the current sample there; closed-door rows keep the lagged regressor
            dT = Ta(t1) - (r1 if dd else r_lag)
            rows_all.append((z, y, c1, dT, dd * dT, nb))
    for z in zones:
        X, Y = [], []
        for zz, y, c, dT, ddT, nb in rows_all:
            if zz == z:
                X.append([float(c), dT, ddT]); Y.append(y)
        # c_adj pooled later; first per-zone fit ignoring coupling but with intercept absorbing it
        Xi = [x + [1.0] for x in X]
        b = lstsq(Xi, Y) if len(Y) > 50 else None
        if b:
            est[f"k_cool.{z}"] = -b[0]
            est[f"k_leak.{z}"] = b[1]
            detail[f"k_cool.{z}"] = {"n": len(Y)}
            detail[f"k_leak.{z}"] = {"n": len(Y), "gain_term": b[2]}
            if b[1] > 1e-6:
                detail[f"door_gain.{z}"] = 1.0 + b[2] / b[1]

    # pooled c_adj: joint fit with per-zone dummies for cool/leak/gain and one shared coupling coefficient
    X, Y = [], []
    zi = {z: i for i, z in enumerate(zones)}
    nz = len(zones)
    for z, y, c, dT, ddT, nb in rows_all:
        row = [0.0] * (3 * nz + 1)
        row[3 * zi[z]] = float(c); row[3 * zi[z] + 1] = dT; row[3 * zi[z] + 2] = ddT; row[3 * nz] = nb
        X.append(row); Y.append(y)
    # stage 1: closed-door samples only, no intercept (the physical model has none): per-zone cool/leak, shared coupling
    X1, Y1 = [], []
    for z, y, c, dT, ddT, nb in rows_all:
        if ddT != 0.0:
            continue
        row = [0.0] * (2 * nz + 1)
        row[2 * zi[z]] = float(c); row[2 * zi[z] + 1] = dT; row[2 * nz] = nb
        X1.append(row); Y1.append(y)
    b = lstsq(X1, Y1) if len(Y1) > 200 else None
    if b:
        est["c_adj"] = b[2 * nz]
        detail["c_adj"] = {"n": len(Y1)}
        for z in zones:
            est[f"k_cool.{z}"] = -b[2 * zi[z]]
            est[f"k_leak.{z}"] = b[2 * zi[z] + 1]
        # stage 2: door-open samples: residual warming relative to the closed-door prediction = k_leak*(g-1)*dT
        num = den = 0.0
        n_open = 0
        for z, y, c, dT, ddT, nb in rows_all:
            if ddT == 0.0:
                continue
            kl = est[f"k_leak.{z}"]
            pred_closed = -est[f"k_cool.{z}"] * c + kl * dT + est["c_adj"] * nb
            num += (y - pred_closed) * (kl * dT)
            den += (kl * dT) ** 2
            n_open += 1
        if den > 0:
            est["door_gain"] = 1.0 + num / den
            detail["door_gain"] = {"n_open_samples": n_open}
    # --- defrost: R (min runtime at DEFROST_ENTER), len, heat
    R_cands, lens, heats = [], [], []
    for z in zones:
        evs = sorted(events[z])
        last_exit = None
        s = per[z]
        for tm, ev_, _ in evs:
            if ev_ == "DEFROST_ENTER":
                if last_exit is not None:
                    seg = [(t, c) for (t, r, c, stt) in s if last_exit <= t < tm]
                    run_min = 0.0
                    for (ta, ca), (tb, cb) in zip(seg, seg[1:]):
                        if ca == 1:
                            run_min += min(tb - ta, 30)
                    R_cands.append(run_min / 60.0)
                enter = tm
                before = [r for (t, r, c, stt) in s if enter - 8 <= t <= enter]
                exit_t = next((t2 for (t2, e2, _) in evs if e2 == "DEFROST_EXIT" and t2 > enter), None)
                if exit_t:
                    lens.append(exit_t - enter)
                    after = [r for (t, r, c, stt) in s if exit_t <= t <= exit_t + 6]
                    if before and after:
                        rise = after[0] - before[-1]
                        kl = est.get(f"k_leak.{z}", 0.001)
                        nb = sum((temp_at(j, enter) or before[-1]) - before[-1] for j in adj[z])
                        heats.append(rise - (kl * (Ta(enter) - before[-1]) + est.get("c_adj", 0.0) * nb) * (exit_t - enter))
            elif ev_ == "DEFROST_EXIT":
                last_exit = tm
    if R_cands:
        R_cands.sort()
        est["defrost.R_hours"] = st.median(R_cands[:max(3, len(R_cands) // 4)])
        detail["defrost.R_hours"] = {"n": len(R_cands), "min": R_cands[0], "median": st.median(R_cands)}
    if lens:
        est["defrost.len_min"] = st.median(lens)
    if heats:
        est["defrost.heat_degC"] = st.median(heats)
        detail["defrost.heat_degC"] = {"n": len(heats)}
    # --- trip d_min, lockout N/W/L
    gaps, Ns, Ls, W_lo, W_hi = [], [], [], [], []
    lock_bouts = []
    for z in zones:
        evs = sorted(events[z])
        opens = [t for t, e, _ in evs if e == "DOOR_OPEN"]
        trips = [t for t, e, _ in evs if e == "TRIP"]
        for tt in trips:
            prev_open = max([t for t in opens if t <= tt], default=None)
            prev_trip = max([t for t in trips if t < tt], default=None)
            if prev_open is not None and (prev_trip is None or prev_trip < prev_open):
                gaps.append(tt - prev_open)
        for t, e, _ in evs:
            if e == "LOCKOUT_ENTER":
                exit_t = next((t2 for (t2, e2, _) in evs if e2 == "LOCKOUT_EXIT" and t2 > t), None)
                if exit_t:
                    Ls.append(exit_t - t)
                # the controller counts trips inside its window (<= 90 min); bouts are far apart, so the trips of the
                # last 95 minutes are the ones that produced this lockout
                bout = [x for x in trips if t - 95 < x <= t]
                Ns.append(len(bout))
                lock_bouts.append(bout)
    if gaps:
        est["trip.d_min"] = min(gaps)
        detail["trip.d_min"] = {"n": len(gaps)}
    if Ns:
        est["lockout.N"] = int(st.mode(Ns))
    if Ls:
        est["lockout.L_min"] = st.median(Ls)
    N = est.get("lockout.N")
    if N:
        for bout in lock_bouts:
            last = sorted(bout)[-N:]
            if len(last) == N:
                W_lo.append(last[-1] - last[0])
        for z in zones:
            trips = sorted(t for t, e, _ in events[z] if e == "TRIP")
            locks = {t for t, e, _ in events[z] if e == "LOCKOUT_ENTER"}
            for i in range(len(trips) - (N - 1)):
                span = trips[i + N - 2] - trips[i]
                nxt = trips[i + N - 1]
                if not any(abs(l - trips[i + N - 2]) < 1 for l in locks) and all(trips[k + 1] - trips[k] <= 30 for k in range(i, i + N - 2)):
                    if nxt - trips[i] > span and not any(abs(l - nxt) < 1 for l in locks):
                        W_hi.append(nxt - trips[i])
        lo = max(W_lo) if W_lo else None
        hi = min(W_hi) if W_hi else None
        detail["lockout.W_min"] = {"bracket": [lo, hi]}
        if lo is not None and hi is not None:
            est["lockout.W_min"] = (lo + hi) / 2
        elif lo is not None:
            est["lockout.W_min"] = lo + 5
    # --- stagger order from back-to-back defrosts in a window
    order_votes = defaultdict(int)
    allde = sorted((t, z) for z in zones for t, e, _ in events[z] if e == "DEFROST_ENTER")
    R_est = est.get("defrost.R_hours", 7) * 60
    def runtime_since_last_exit(z, at):
        exits = [t for t, e, _ in events[z] if e == "DEFROST_EXIT" and t < at]
        if not exits:
            return None
        seg = [(t, c) for (t, r, c, stt) in per[z] if exits[-1] <= t < at]
        return sum(min(tb - ta, 30) for (ta, ca), (tb, cb) in zip(seg, seg[1:]) if ca == 1)
    for (t1, z1), (t2, z2) in zip(allde, allde[1:]):
        if z1 != z2 and t2 - t1 <= (est.get("defrost.len_min", 20) + 3):
            rt = runtime_since_last_exit(z2, t1)
            if rt is not None and rt >= R_est + 10:      # clearly pending before z1 started
                order_votes[(z1, z2)] += 1
    remaining = list(zones)
    order = []
    while remaining:
        def beaten_by(z):
            return sum(1 for x in remaining if x != z and order_votes.get((x, z), 0) > order_votes.get((z, x), 0))
        def net(z):
            return sum(order_votes.get((z, x), 0) - order_votes.get((x, z), 0) for x in remaining if x != z)
        best = min(remaining, key=lambda z: (beaten_by(z), -net(z)))
        order.append(best); remaining.remove(best)
    est["stagger_order"] = order
    detail["stagger_order"] = {"pairs": {f"{a}>{b}": n for (a, b), n in order_votes.items()}}
    # --- compare
    report = {"estimates": {}, "within_tol": 0, "n": 0, "failures": []}
    for pid, tp in truth["mechanism"]["params"].items():
        if pid not in est:
            report["failures"].append((pid, "no estimate"))
            report["n"] += 1
            continue
        tol = max(tp["abs_tol"], tp["rel_tol"] * abs(tp["value"]))
        err = est[pid] - tp["value"]
        ok = abs(err) <= tol
        report["estimates"][pid] = {"est": round(est[pid], 5), "true": tp["value"], "err": round(err, 5), "tol": round(tol, 5), "ok": ok, **({"detail": detail[pid]} if pid in detail else {})}
        report["n"] += 1
        report["within_tol"] += int(ok)
        if not ok:
            report["failures"].append((pid, round(err, 5), round(tol, 5)))
    report["stagger_order"] = {"est": est["stagger_order"], "true": truth["mechanism"]["rules"]["stagger_order"], "votes": detail["stagger_order"]}
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance")
    a = ap.parse_args()
    inst = Path(a.instance)
    truth = json.load(open(inst / "truth.json"))
    rep = estimate(inst / "evidence", truth)
    print(json.dumps(rep, indent=1, default=str))
    print(f"within tolerance: {rep['within_tol']}/{rep['n']}")


if __name__ == "__main__":
    main()
