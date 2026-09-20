# Hidden thermal + controller mechanism. NEVER shipped into an instance's evidence/.
from __future__ import annotations
import math
import random
from collections import deque

STATES = ("IDLE", "RUN", "DEFROST", "RECOVERY", "LOCKOUT")
TRIP_COOL_MIN = 5          # compressor hold-off after a trip (nuisance, unscored)
REPORT_EVERY_MIN = 5       # periodic state-report frame cadence
SENSOR_NOISE_SD = 0.03     # controller-side sensor noise (after the unit's own filtering)
PROCESS_NOISE_SD = 0.02


def ambient(t_min: int, base: float, swing: float, drift: float, days: int) -> float:
    hour = (t_min % 1440) / 60.0
    diurnal = swing * math.sin(2 * math.pi * (hour - 8.0) / 24.0)
    slow = drift * math.sin(2 * math.pi * t_min / (1440.0 * max(days, 1)))
    return base + diurnal + slow


class ZoneCtl:
    def __init__(self, z, sp, p):
        self.z, self.sp = z, sp
        self.k_cool, self.k_leak, self.H, self.bias = p["k_cool"][z], p["k_leak"][z], p["H"][z], p["bias"][z]
        self.T = sp
        self.calling = False
        self.state = "IDLE"
        self.runtime_min = 0
        self.defrost_req = False
        self.defrost_until = -1
        self.recovery = False
        self.trip_hold_until = -1
        self.trips: deque[int] = deque()
        self.lockout_until = -1
        self.door_run = 0
        self.comp_on = False
        self.heater = False
        self.fw = "3.2"
        self.P0 = 0.0


def simulate(world: dict, rng: random.Random) -> dict:
    p = world["params"]
    zones = world["zones"]["order"]
    sp = {z: world["zones"]["setpoint"][z] for z in zones}
    days, total = world["sim"]["days"], world["sim"]["days"] * 1440
    adj = {z: set() for z in zones}
    for a, b in p["adjacency"]:
        adj[a].add(b); adj[b].add(a)
    ctl = {z: ZoneCtl(z, sp[z], p) for z in zones}
    for z in zones:
        ctl[z].runtime_min = rng.randrange(0, int(p["defrost"]["R_hours"] * 60 * 0.7))
        ctl[z].P0 = world["nuisance"]["P0"][z]
    stagger_rank = {z: i for i, z in enumerate(p["stagger_order"])}
    R_min = p["defrost"]["R_hours"] * 60
    d_len, d_heat = p["defrost"]["len_min"], p["defrost"]["heat_degC"]
    d_min, N, W, L = p["trip"]["d_min"], p["lockout"]["N"], p["lockout"]["W_min"], p["lockout"]["L_min"]
    door_gain, c_adj = p["door_gain"], p["c_adj"]
    win_starts, win_len = p["defrost"]["window_starts_min"], p["defrost"]["window_len_min"]
    amb = world["nuisance"]["ambient"]

    door_open = {z: [0] * total for z in zones}
    for iv in world["ledger"]["door_intervals"]:
        for t in range(max(0, iv["t0"]), min(total, iv["t1"])):
            door_open[iv["zone"]][t] = 1
    fw_switch = {e["zone"]: e["t"] for e in world["ledger"]["firmware_flash"]}
    boots = {z: [] for z in zones}
    for z, t in fw_switch.items():
        boots[z].append(t)
    for po in world["ledger"].get("power_outages", []):
        for z in zones:
            boots[z].append(po["t1"])          # every unit boots when power returns
    drift = world["ledger"].get("sensor_drift")   # {"zone","t0","t1","rate_per_min","t_fix"} or None
    def bias_at(z, t):
        b = ctl[z].bias
        if drift and drift["zone"] == z and t >= drift["t0"]:
            if t < drift["t_fix"]:
                b += drift["rate_per_min"] * min(t - drift["t0"], drift["t1"] - drift["t0"])
        return b
    setpoint_changes = {(e["zone"], e["t"]): e["value"] for e in world["ledger"].get("setpoint_changes", [])}
    prop_end = {}
    for d in world["ledger"].get("props", []):
        prop_end[(d["zone"], d["t1"] + 4)] = d["t0"]      # reported once the uplink is back (link returns within ~2 min)

    T_true = {z: [0.0] * total for z in zones}
    T_rep = {z: [0.0] * total for z in zones}
    st = {z: [""] * total for z in zones}
    comp = {z: [0] * total for z in zones}
    heat = {z: [0] * total for z in zones}
    pres = {z: [0.0] * total for z in zones}
    events = []            # (t, zone, type, value)
    frames = []            # clause IR frames (see contract §6)
    collisions = []        # (t, requested_zones_sorted_by_rank, winner)
    seq = dict(world["nuisance"]["seq0"])
    ctrl_id = world["zones"]["controller"]
    clock_off = dict(world["nuisance"]["ctrl_clock_offset_min"])
    clock_epochs = {z: [(0, -clock_off[z])] for z in zones}   # (from_t, epoch_t): t_ctrl = t - epoch_t

    def emit(t, z, clauses):
        seq[z] += 1
        frames.append({"ctrl_id": ctrl_id[z], "zone": z, "seq": seq[z], "t_min": t,
                       "t_ctrl_min": t + clock_off[z], "fw": ctl[z].fw, "setpoint": ctl[z].sp, "clauses": clauses})

    outages = [(po["t0"], po["t1"]) for po in world["ledger"].get("power_outages", [])]
    def power_off(t):
        return any(a <= t < b for a, b in outages)
    for t in range(total):
        Ta = ambient(t, amb["base"], amb["swing"], amb["drift"], days)
        if power_off(t):
            for z in zones:
                c = ctl[z]
                c.comp_on = False; c.heater = False
                leak = c.k_leak * (Ta - c.T) * (1.0 + (door_gain - 1.0) * door_open[z][t])
                couple = c_adj * sum(ctl[j].T - c.T for j in adj[z])
                T_true[z][t] = c.T; T_rep[z][t] = c.T + bias_at(z, t); st[z][t] = "OFF"; comp[z][t] = 0; heat[z][t] = 0; pres[z][t] = c.P0
                c.T = c.T + leak + couple + rng.gauss(0, PROCESS_NOISE_SD)
            continue
        # controller decisions use last minute's temperatures
        for z in zones:
            c = ctl[z]
            if (z, t) in setpoint_changes:
                c.sp = setpoint_changes[(z, t)]
                emit(t, z, [{"kind": "EVENT", "event": "SETPOINT_SET", "zone": z, "value": c.sp}])
            if t in boots[z]:
                if t == fw_switch.get(z):
                    c.fw = "3.4"
                seq[z] = 0
                clock_off[z] = -t
                clock_epochs[z].append((t, t))
                emit(t, z, [{"kind": "EVENT", "event": "BOOT", "zone": z, "value": 34.0 if c.fw == "3.4" else 32.0}])
                # cold boot: the controller resumes IDLE with its counters cleared
                c.trips.clear(); c.door_run = 0
                if c.state == "LOCKOUT":
                    c.state = "IDLE"
            sensor = c.T + bias_at(z, t) + rng.gauss(0, SENSOR_NOISE_SD)
            if sensor >= c.sp + c.H / 2:
                c.calling = True
            elif sensor <= c.sp - c.H / 2:
                c.calling = False
                c.recovery = False
            # lockout / defrost state transitions
            if c.state == "LOCKOUT":
                if t >= c.lockout_until:
                    c.state = "IDLE"
                    emit(t, z, [{"kind": "EVENT", "event": "LOCKOUT_EXIT", "zone": z, "value": None}])
            if c.state == "DEFROST" and t >= c.defrost_until:
                c.state = "IDLE"; c.heater = False; c.recovery = True
                emit(t, z, [{"kind": "EVENT", "event": "DEFROST_EXIT", "zone": z, "value": None}])
                emit(t, z, [{"kind": "EVENT", "event": "HEATER_OFF", "zone": z, "value": None}])
            c._sensor = sensor
        # defrost scheduler: only inside the hidden daily windows, one zone at a time, stagger priority
        tod = t % 1440
        in_window = any(ws <= tod < ws + win_len for ws in win_starts)
        if in_window and not any(ctl[z].state == "DEFROST" for z in zones):
            req = [z for z in zones if ctl[z].defrost_req and ctl[z].state != "LOCKOUT"]
            if req:
                req.sort(key=lambda z: stagger_rank[z])
                w = req[0]
                if len(req) > 1:
                    collisions.append({"t": t, "requested": req, "winner": w})
                c = ctl[w]
                c.state = "DEFROST"; c.defrost_until = t + d_len; c.defrost_req = False
                c.runtime_min = 0; c.heater = True; c.comp_on = False
                emit(t, w, [{"kind": "EVENT", "event": "DEFROST_ENTER", "zone": w, "value": None}])
                emit(t, w, [{"kind": "EVENT", "event": "HEATER_ON", "zone": w, "value": None}])
        # compressor, trips, lockouts
        for z in zones:
            c = ctl[z]
            on = c.calling and c.state not in ("DEFROST", "LOCKOUT") and t >= c.trip_hold_until
            if on:
                c.runtime_min += 1
                if c.runtime_min >= R_min and not c.defrost_req:
                    c.defrost_req = True
            if on and door_open[z][t]:
                c.door_run += 1
            else:
                c.door_run = 0
            c.comp_on = on
            if c.state not in ("DEFROST", "LOCKOUT"):
                c.state = ("RECOVERY" if c.recovery else "RUN") if on else "IDLE"
            P = c.P0 + (0.9 if on else 0.0) + 0.12 * c.door_run + 0.02 * (c.T - c.sp) + rng.gauss(0, 0.05)
            pres[z][t] = P
            if c.door_run > d_min:
                c.door_run = 0
                c.trip_hold_until = t + TRIP_COOL_MIN
                c.trips.append(t)
                while c.trips and c.trips[0] <= t - W:
                    c.trips.popleft()
                events.append((t, z, "TRIP", round(P, 2)))
                emit(t, z, [{"kind": "EVENT", "event": "TRIP", "zone": z, "value": None}])
                if len(c.trips) >= N:
                    c.state = "LOCKOUT"; c.lockout_until = t + L; c.trips.clear(); c.comp_on = False
                    events.append((t, z, "LOCKOUT_ENTER", L))
                    emit(t, z, [{"kind": "EVENT", "event": "LOCKOUT_ENTER", "zone": z, "value": None}])
        # physics
        newT = {}
        for z in zones:
            c = ctl[z]
            leak = c.k_leak * (Ta - c.T) * (1.0 + (door_gain - 1.0) * door_open[z][t])
            cool = -c.k_cool if c.comp_on else 0.0
            couple = c_adj * sum(ctl[j].T - c.T for j in adj[z])
            heater = (d_heat / d_len) if c.heater else 0.0
            newT[z] = c.T + cool + leak + couple + heater + rng.gauss(0, PROCESS_NOISE_SD)
        for z in zones:
            c = ctl[z]
            T_true[z][t] = c.T
            T_rep[z][t] = c._sensor + rng.gauss(0, p["noise_sd"])
            st[z][t] = c.state
            comp[z][t] = 1 if c.comp_on else 0
            heat[z][t] = 1 if c.heater else 0
            c.T = newT[z]
        # a unit whose uplink was down while its door stood open reports how many telegrams it could not deliver
        for z in zones:
            if (z, t) in prop_end:
                t0p = prop_end[(z, t)]
                n_lost = sum(1 for f in frames if f["zone"] == z and t0p <= f["t_min"] <= t - 1)
                emit(t, z, [{"kind": "EVENT", "event": "QUEUE_OVERFLOW", "zone": z, "value": float(n_lost)}])
        # door events -> frames
        for z in zones:
            prev = door_open[z][t - 1] if t > 0 else 0
            if door_open[z][t] != prev:
                ev = "DOOR_OPEN" if door_open[z][t] else "DOOR_CLOSE"
                emit(t, z, [{"kind": "EVENT", "event": ev, "zone": z, "value": None}])
        # periodic reports
        if t % REPORT_EVERY_MIN == 0:
            for z in zones:
                c = ctl[z]
                frames_before = len(frames)
                emit(t, z, [
                    {"kind": "READ", "sensor": "AIR_TEMP", "zone": z, "value": round(T_rep[z][t], 1)},
                    {"kind": "READ", "sensor": "COIL_TEMP", "zone": z, "value": round(T_rep[z][t] - (6.0 if c.comp_on else 0.5) + rng.gauss(0, 0.2), 1)},
                    {"kind": "READ", "sensor": "DISCH_PRESSURE", "zone": z, "value": round(max(0.0, pres[z][t]), 1)},
                    {"kind": "STATE", "state": c.state, "zone": z},
                ])
                frames[-1]["door_open"] = bool(door_open[z][t])
    lockouts = [e for e in events if e[2] == "LOCKOUT_ENTER"]
    trips = [e for e in events if e[2] == "TRIP"]
    return {"T_true": T_true, "T_rep": T_rep, "state": st, "comp": comp, "heat": heat, "pres": pres,
            "events": events, "frames": frames, "collisions": collisions, "clock_epochs": clock_epochs,
            "lockouts": lockouts, "trips": trips, "door_open": door_open}


def excursion_windows(sim: dict, zone: str, threshold: float, min_len: int = 30) -> list[tuple[int, int]]:
    T = sim["T_true"][zone]
    out, start = [], None
    for t, v in enumerate(T):
        if v > threshold and start is None:
            start = t
        elif v <= threshold and start is not None:
            if t - start >= min_len:
                out.append((start, t))
            start = None
    if start is not None and len(T) - start >= min_len:
        out.append((start, len(T)))
    return out


def near_misses(sim: dict, N: int, W: int) -> list[dict]:
    # bouts that reached exactly N-1 trips inside a W-minute window without a lockout
    out = []
    by_zone: dict[str, list[int]] = {}
    for t, z, kind, _ in sim["events"]:
        if kind == "TRIP":
            by_zone.setdefault(z, []).append(t)
    lock_t = {(z, t) for t, z, k, _ in sim["events"] if k == "LOCKOUT_ENTER"}
    for z, ts in by_zone.items():
        i = 0
        while i < len(ts):
            j = i
            while j + 1 < len(ts) and ts[j + 1] - ts[i] <= W:
                j += 1
            n = j - i + 1
            if n == N - 1 and not any((z, tt) in lock_t for tt in ts[i:j + 1]):
                out.append({"zone": z, "t0": ts[i], "t1": ts[j], "n_trips": n})
            i = j + 1
    return out


def duty_cycle(sim: dict, zone: str) -> float:
    c = sim["comp"][zone]
    return sum(c) / max(1, len(c))


def w_bracket(sim: dict, N: int) -> tuple:
    """Observable bracket for the lockout window W: lo = widest span of the N trips that produced a lockout;
    hi = narrowest (t_N - t_1) over bouts where N-1 trips were followed by an N-th trip without a lockout."""
    by_zone = {}
    for t, z, kind, _ in sim["events"]:
        by_zone.setdefault(z, []).append((t, kind))
    lo, hi = None, None
    for z, evs in by_zone.items():
        evs.sort()
        trips = [t for t, k in evs if k == "TRIP"]
        locks = [t for t, k in evs if k == "LOCKOUT_ENTER"]
        for L in locks:
            prior = [t for t in trips if t <= L]
            if len(prior) >= N:
                span = prior[-1] - prior[-N]
                lo = span if lo is None else max(lo, span)
        for i in range(len(trips) - N + 1):
            window = trips[i:i + N]
            if any(abs(L - window[-1]) < 1 for L in locks) or any(abs(L - t) < 1 for L in locks for t in window[:-1]):
                continue
            # the first N-1 trips did not lock out, the N-th neither: W < window[-1]-window[0] provided the earlier
            # N-1 were inside W (checked by the sim: no lockout on them means they never reached N)
            span = window[-1] - window[0]
            hi = span if hi is None else min(hi, span)
    return lo, hi
