# seed -> world.json: names, hidden parameters, actors, the true event ledger, distortion table.
from __future__ import annotations
import datetime as dt
import hashlib
import random

from gen import mechanism

TIERS = {
    "easy":    dict(noise_sd=0.15, dropout=0.03, n_decoys=2, p_mislabel=0.10, n_red_herrings=3, offset_channels=2, false_claim_rate=0.15),
    "default": dict(noise_sd=0.30, dropout=0.08, n_decoys=3, p_mislabel=0.25, n_red_herrings=6, offset_channels=3, false_claim_rate=0.25),
    "hard":    dict(noise_sd=0.45, dropout=0.12, n_decoys=5, p_mislabel=0.35, n_red_herrings=8, offset_channels=4, false_claim_rate=0.35),
}
FIRST = ["Maya", "Jonas", "Priya", "Tomas", "Aisha", "Derek", "Lena", "Rafael", "Ingrid", "Samuel", "Noor", "Victor",
         "Hana", "Marcus", "Elif", "Owen", "Zara", "Felix", "Ana", "Kwame", "Sofia", "Ivan", "Leila", "Bruno"]
LAST = ["Rivera", "Okafor", "Nguyen", "Patel", "Lindqvist", "Moreau", "Kowalski", "Haddad", "Tanaka", "Ferreira",
        "Byrne", "Adeyemi", "Schulz", "Castellano", "Novak", "Mensah", "Larsen", "Dubois", "Iyer", "Costa"]
COMPANIES = ["Frostline Logistics", "Northgate Cold Chain", "Glacier Bay Storage", "Polaris Pharma Logistics",
             "Icefield Distribution", "Meridian Cold Storage", "Borealis Coldchain", "Tundra Vault Logistics"]
PRODUCTS = ["insulin glargine 100U/mL", "mRNA vaccine lot", "monoclonal antibody vials", "enoxaparin syringes",
            "pegfilgrastim prefilled", "adalimumab pens", "erythropoietin vials", "interferon beta kits"]
ROLES = ["warehouse_manager", "night_lead", "forklift_op_1", "forklift_op_2", "temp_worker", "receiving_clerk",
         "vendor_tech", "ops_engineer", "sre_oncall", "qa_manager"]
CHANNELS = ["badge", "exif", "cctv", "forklift", "chat", "tickets", "git", "submeter", "gateway", "probe"]


def _iso(start: dt.datetime, t_min: int) -> str:
    return (start + dt.timedelta(minutes=int(t_min))).strftime("%Y-%m-%dT%H:%M:%SZ")


def _handle(first, last, used):
    h = f"{first[0].lower()}.{last.lower()}"
    if h in used:
        h = f"{first[:2].lower()}.{last.lower()}"
    used.add(h)
    return h


def make_names(rng: random.Random) -> dict:
    letters = ["A", "B", "C", "D", "E", "F"]
    vendor = rng.choice(["KW", "RH", "TK", "VX", "NB"]) + "-" + str(rng.choice([5, 7, 9]))
    ctrl = {z: f"{vendor.split('-')[0]}{i + 1:02d}" for i, z in enumerate(letters)}
    used = set()
    people = []
    for role in ROLES:
        f, l = rng.choice(FIRST), rng.choice(LAST)
        people.append({"role": role, "name": f"{f} {l}", "handle": _handle(f, l, used)})
    return {"company": rng.choice(COMPANIES), "vendor_model": vendor, "controller": ctrl, "zones": letters,
            "site_code": "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(3)) + str(rng.randrange(10, 99)),
            "actors": people}


def make_params(rng: random.Random, zones: list[str], tier: dict, zinfo: dict, amb_base: float) -> dict:
    grid = list(range(6))
    rng.shuffle(grid)                      # grid[i] = zone index placed at cell i (2 rows x 3 cols)
    cell_of = {zones[grid[i]]: i for i in range(6)}
    pairs = []
    for z in zones:
        i = cell_of[z]
        r, c = divmod(i, 3)
        for z2 in zones:
            j = cell_of[z2]
            r2, c2 = divmod(j, 3)
            if z < z2 and abs(r - r2) + abs(c - c2) == 1:
                pairs.append([z, z2])
    stagger = zones[:]
    rng.shuffle(stagger)
    p = {
        "k_cool": {},
        "k_leak": {},
        "H": {z: round(rng.uniform(0.6, 2.4), 2) for z in zones},
        "bias": {z: round(rng.uniform(-1.5, 1.5), 2) for z in zones},
        "door_gain": round(rng.uniform(3.0, 9.0), 2),
        "c_adj": 0.0,
        "adjacency": pairs,
        "grid": {z: cell_of[z] for z in zones},
        "defrost": {"rule": "runtime_hours", "R_hours": rng.choice([5, 6, 7, 8, 9, 10, 11]),
                    "len_min": rng.randrange(12, 31), "heat_degC": round(rng.uniform(2.0, 5.0), 1),
                    "window_starts_min": sorted(((rng.randrange(0, 360) + 360 * i) % 1440) for i in range(4)),
                    "window_len_min": rng.choice([90, 120, 150])},
        "stagger_order": stagger,
        "trip": {"d_min": rng.randrange(6, 11)},
        "lockout": {"N": rng.choice([3, 4, 5]), "W_min": rng.choice([20, 30, 45, 60, 90]), "L_min": rng.choice([60, 90, 120, 180, 240])},
        "noise_sd": tier["noise_sd"], "frame_dropout": tier["dropout"],
    }
    adj = {z: [] for z in zones}
    for a, b in pairs:
        adj[a].append(b); adj[b].append(a)
    for z in zones:
        chill = zinfo["kind"][z] == "chill"
        p["k_leak"][z] = round(rng.uniform(0.0012, 0.0025) if chill else rng.uniform(0.0006, 0.0018), 5)
    # coupling must leave every room with at least 55% of its closed-door leak load (else a chill room next to
    # freezers never calls for cooling)
    c_max = 0.0009
    for z in zones:
        leak = p["k_leak"][z] * (amb_base - zinfo["setpoint"][z])
        pull = sum(zinfo["setpoint"][z] - zinfo["setpoint"][j] for j in adj[z])   # positive when neighbours are colder
        if pull > 0:
            c_max = min(c_max, 0.45 * leak / pull)
    p["c_adj"] = round(rng.uniform(0.0003, max(0.0003, c_max)), 5)
    for z in zones:
        leak = p["k_leak"][z] * (amb_base - zinfo["setpoint"][z])
        net = leak + p["c_adj"] * sum(zinfo["setpoint"][j] - zinfo["setpoint"][z] for j in adj[z])
        duty = rng.uniform(0.30, 0.60)
        p["k_cool"][z] = round(max(0.03, net / duty), 4)
    # guarantee a propped-open door can reach N trips inside W (needed for the incident): (N-1)*(d+6) <= W-6
    while (p["lockout"]["N"] - 1) * (p["trip"]["d_min"] + 1 + mechanism.TRIP_COOL_MIN) > p["lockout"]["W_min"] - 6:
        bigger = [w for w in [30, 45, 60, 90] if w > p["lockout"]["W_min"]]
        if bigger:
            p["lockout"]["W_min"] = bigger[0]
        else:
            p["lockout"]["N"] = max(3, p["lockout"]["N"] - 1)
    return p


def make_zones(rng: random.Random, zones: list[str]) -> dict:
    kinds = ["deep", "freezer", "freezer", "freezer", "chill", "chill"]
    rng.shuffle(kinds)
    sp = {}
    for z, k in zip(zones, kinds):
        sp[z] = {"deep": round(rng.uniform(-30, -26), 1), "freezer": round(rng.uniform(-25, -18), 1),
                 "chill": round(rng.uniform(2.0, 6.0), 1)}[k]
    kind = dict(zip(zones, kinds))
    panels = zones[:]
    rng.shuffle(panels)
    panel = {}
    for i in range(3):
        for z in panels[2 * i:2 * i + 2]:
            panel[z] = f"P{i + 1}"
    incident = rng.choice([z for z in zones if kind[z] == "freezer"])
    return {"order": zones, "setpoint": sp, "kind": kind, "panel": panel, "incident_zone": incident,
            "excursion_threshold": {z: (sp[z] + 5.0 if kind[z] != "chill" else 8.0) for z in zones}}


def shift_of(t_min: int) -> str:
    h = (t_min % 1440) // 60
    return "day" if 6 <= h < 14 else "evening" if 14 <= h < 22 else "night"


def build_world(seed: int, tier_name: str = "default") -> dict:
    tier = TIERS[tier_name]
    rng = random.Random(f"eval_imp:{seed}:{tier_name}")
    names = make_names(rng)
    zones = names["zones"]
    zinfo = make_zones(rng, zones)
    amb_base = round(rng.uniform(15.0, 21.0), 1)
    params = make_params(rng, zones, tier, zinfo, amb_base)
    days = 30
    start = dt.datetime(2026, rng.randrange(1, 8), rng.randrange(1, 28), 0, 0, 0)
    actors = {a["role"]: a for a in names["actors"]}
    inc_zone = zinfo["incident_zone"]
    freezers = [z for z in zones if zinfo["kind"][z] != "chill"]
    flash_day = rng.choice([4, 5])
    incident_day = rng.choice([14, 15, 16])
    hotfix_day = flash_day + 1
    power_day = rng.choice([2, 3])
    power_t0 = power_day * 1440 + 10 * 60 + rng.randrange(0, 60)
    power_t1 = power_t0 + rng.randrange(18, 28)
    receiving_zones = rng.sample([z for z in freezers if z != inc_zone], 2)   # dock doors serve two freezer rooms

    # rooms never on the probe route (their sensor bias cannot be established from the evidence)
    other_flashed_candidates = [z for z in freezers if z != inc_zone]
    other_flashed = rng.choice(other_flashed_candidates)
    drift_zone = rng.choice([z for z in zones if z not in (inc_zone, other_flashed)])
    probe_excluded = rng.sample([z for z in zones if z not in (inc_zone, other_flashed, drift_zone)], 2)
    # ---- inventory ----
    lots = []
    for i in range(rng.randrange(54, 70)):
        z = rng.choice(zones)
        lots.append({"lot_id": f"LN-{rng.randrange(20000, 29999)}", "product": rng.choice(PRODUCTS), "zone": z,
                     "pallet_id": f"PL-{rng.randrange(1000, 9999)}", "qty": rng.randrange(120, 960)})
    seen = set()
    lots = [l for l in lots if not (l["lot_id"] in seen or seen.add(l["lot_id"]))]

    # ---- schedules ----
    door_intervals, moves, probe_checks, receiving, badge, walkthroughs, props = [], [], [], [], [], [], []
    d_min, N_lock = params["trip"]["d_min"], params["lockout"]["N"]
    t_trip = lambda k: d_min + (k - 1) * (d_min + 1 + mechanism.TRIP_COOL_MIN)   # door-open minutes until the k-th trip
    short_bout = lambda: rng.randrange(3, max(4, t_trip(2)))                 # 0-1 trips
    near_miss_bout = lambda: t_trip(N_lock - 1) + rng.randrange(1, 4)        # N-1 trips
    lockout_bout = lambda: t_trip(N_lock) + rng.randrange(3, 12)             # N trips -> lockout
    benign_lockout_day = rng.randrange(5, 12)
    W_lock = params["lockout"]["W_min"]
    pool_days = [d for d in range(1, days - 2) if d not in (benign_lockout_day, power_day, incident_day, incident_day + 1)]
    rng.shuffle(pool_days)
    near_miss_days = set(pool_days[:5])
    late_trip_days = set(pool_days[5:8])          # N-1 trips, pause, one more trip just AFTER the window: no lockout
    tight_lock_days = set(pool_days[8:11])        # N trips spanning just UNDER the window: lockout
    ops = [actors["forklift_op_1"], actors["forklift_op_2"]]
    forklifts = {ops[0]["handle"]: "FL-1", ops[1]["handle"]: "FL-2"}
    handheld = {actors["warehouse_manager"]["handle"]: ("HH-1", 0.0), actors["receiving_clerk"]["handle"]: ("HH-2", round(rng.uniform(0.6, 1.1), 1)),
                actors["night_lead"]["handle"]: ("HH-1", 0.0)}
    zone_lots = {z: [l for l in lots if l["zone"] == z] for z in zones}
    ev_id = [0]

    def nid(prefix):
        ev_id[0] += 1
        return f"{prefix}{ev_id[0]:04d}"

    def add_door(z, t0, t1, cause, actor, **extra):
        d = {"id": nid("door"), "zone": z, "t0": t0, "t1": t1, "cause": cause, "actor": actor}
        d.update(extra)
        door_intervals.append(d)
        return d

    for day in range(days):
        base = day * 1440
        weekday = (start + dt.timedelta(days=day)).weekday()
        # shifts (badge in/out)
        for role, sh in [("warehouse_manager", "day"), ("receiving_clerk", "day"), ("forklift_op_1", "day"),
                         ("forklift_op_2", "evening"), ("night_lead", "night"), ("temp_worker", "night")]:
            if role == "temp_worker" and day < 3:
                continue
            if weekday >= 5 and role in ("receiving_clerk", "warehouse_manager") and rng.random() < 0.7:
                continue
            s0 = {"day": 6 * 60, "evening": 14 * 60, "night": 22 * 60}[sh]
            t_in = base + s0 + rng.randrange(-12, 6)
            t_out = t_in + 8 * 60 + rng.randrange(-10, 25)
            badge.append({"actor": actors[role]["handle"], "t": t_in, "kind": "shift_start"})
            badge.append({"actor": actors[role]["handle"], "t": t_out, "kind": "shift_end"})
        # pallet moves (day + evening), scanned in batches; some go through a staging zone (two hops)
        n_batches = rng.randrange(5, 9) if weekday < 5 else rng.randrange(1, 4)
        for _ in range(n_batches):
            op = ops[0] if rng.random() < 0.55 else ops[1]
            s0 = 6 * 60 if op is ops[0] else 14 * 60
            tb = base + s0 + rng.randrange(15, 7 * 60 + 30)
            t_sec = tb * 60
            for _k in range(rng.randrange(2, 5)):
                src = rng.choice(zones)
                if not zone_lots[src]:
                    continue
                lot = rng.choice(zone_lots[src])
                dst = rng.choice([z for z in zones if z != src])
                hops = [(src, dst)]
                if rng.random() < 0.30:
                    stage = rng.choice([z for z in zones if z not in (src, dst)])
                    hops = [(src, stage), (stage, dst)]
                for hi, (a, b) in enumerate(hops):
                    t = t_sec // 60
                    dur = rng.randrange(2, min(6, d_min))
                    add_door(a, t, t + dur, "pallet_move", op["handle"], lot=lot["lot_id"])
                    t2 = t + dur + rng.randrange(1, 4)
                    add_door(b, t2, t2 + rng.randrange(2, min(6, d_min)), "pallet_move", op["handle"], lot=lot["lot_id"])
                    moves.append({"id": nid("mv"), "t": t, "t_sec": t_sec, "actor": op["handle"], "forklift": forklifts[op["handle"]],
                                  "lot": lot["lot_id"], "pallet": lot["pallet_id"], "from": a, "to": b, "hop": hi, "n_hops": len(hops)})
                    zone_lots[a].remove(lot); lot["zone"] = b; zone_lots[b].append(lot)
                    t_sec += rng.randrange(45, 100) if hi + 1 < len(hops) else 0
                t_sec += rng.randrange(8, 40)
        # receiving bouts (long door-open at dock zones) -> trips / near misses
        if day in late_trip_days or day in tight_lock_days:
            z = rng.choice(receiving_zones)
            t = base + 8 * 60 + rng.randrange(0, 6 * 60)
            first = t_trip(N_lock - 1) + 2                              # holds N-1 trips
            add_door(z, t, t + first, "receiving", actors["receiving_clerk"]["handle"], truck=f"TRK-{rng.randrange(100, 999)}", bout="split_a")
            if day in late_trip_days:
                t2 = t + W_lock + 3                                         # N-th trip lands at first_trip + W + 3
            else:
                t2 = t + W_lock - 4                                         # N-th trip lands at first_trip + W - 4
            add_door(z, t2, t2 + d_min + 3, "receiving", actors["receiving_clerk"]["handle"], truck=f"TRK-{rng.randrange(100, 999)}", bout="split_b")
            receiving.append({"t": t, "zone": z, "dur": first, "actor": actors["receiving_clerk"]["handle"], "bout": "split"})
        if weekday < 5 or day in near_miss_days or day == benign_lockout_day:
            n_bouts = rng.randrange(1, 4)
            kinds = ["short"] * n_bouts
            if day in near_miss_days:
                kinds[0] = "near_miss"
            if day == benign_lockout_day:
                kinds[-1] = "lockout"
            W_lock = params["lockout"]["W_min"]
            slots = []
            for kind in kinds:
                z = rng.choice(receiving_zones)
                for _try in range(20):
                    t = base + 7 * 60 + rng.randrange(0, 9 * 60)
                    if all(abs(t - t0) > W_lock + 70 for t0 in slots):
                        break
                slots.append(t)
                dur = {"short": short_bout, "near_miss": near_miss_bout, "lockout": lockout_bout}[kind]()
                add_door(z, t, t + dur, "receiving", actors["receiving_clerk"]["handle"], truck=f"TRK-{rng.randrange(100, 999)}", bout=kind)
                receiving.append({"t": t, "zone": z, "dur": dur, "actor": actors["receiving_clerk"]["handle"], "bout": kind})
        # probe round on weekdays: the manager does every room with HH-1, the clerk three rooms with HH-2 (biased)
        if weekday < 5:
            probed = [z for z in zones if z not in probe_excluded]
            for who, picks in ((actors["warehouse_manager"]["handle"], probed), (actors["receiving_clerk"]["handle"], rng.sample(probed, 3))):
                t = base + rng.randrange(7 * 60, 12 * 60)
                for z in picks:
                    t += rng.randrange(4, 15)
                    add_door(z, t, t + 1, "probe_check", who)
                    probe_checks.append({"t": t, "zone": z, "actor": who, "handheld": handheld[who][0], "hh_bias": handheld[who][1]})
        # night walkthrough by the night lead
        for z in rng.sample(zones, 2):
            t = base + 23 * 60 + rng.randrange(0, 5 * 60)
            add_door(z, t, t + rng.randrange(1, 3), "walkthrough", actors["night_lead"]["handle"])
            walkthroughs.append({"t": t, "zone": z})
        # temp worker: propping the incident-zone door on nights (short before the incident, long on it)
        if day >= 6 and day != incident_day and rng.random() < 0.45:
            t = base + 23 * 60 + rng.randrange(30, 3 * 60)
            dur = rng.randrange(t_trip(1) + 1, t_trip(N_lock - 1) + 3)
            props.append(add_door(inc_zone, t, t + dur, "door_prop", actors["temp_worker"]["handle"]))
        if day == incident_day:
            t = base + 24 * 60 + rng.randrange(20, 80)           # ~00:20-01:20 next calendar day
            dur = rng.randrange(190, 260)
            props.append(add_door(inc_zone, t, t + dur, "door_prop", actors["temp_worker"]["handle"], incident=True))

    firmware_flash = [{"zone": inc_zone, "t": flash_day * 1440 + 14 * 60 + rng.randrange(0, 90), "actor": actors["vendor_tech"]["handle"]}]
    other = other_flashed
    firmware_flash.append({"zone": other, "t": firmware_flash[0]["t"] + rng.randrange(35, 70), "actor": actors["vendor_tech"]["handle"]})
    drift_t0 = 8 * 1440 + rng.randrange(0, 1440)
    drift_t1 = 22 * 1440 + rng.randrange(0, 600)
    recal_t = 23 * 1440 + 13 * 60 + rng.randrange(0, 150)
    sensor_drift = {"zone": drift_zone, "t0": drift_t0, "t1": drift_t1, "rate_per_min": round(rng.uniform(2.0, 3.2) / (drift_t1 - drift_t0), 8), "t_fix": recal_t}
    power_outages = [{"t0": power_t0, "t1": power_t1, "kind": "utility_generator_test"}]
    ambient = {"base": amb_base, "swing": round(rng.uniform(1.5, 4.0), 1), "drift": round(rng.uniform(0.5, 2.0), 1)}
    nuisance = {"ambient": ambient, "P0": {z: round(rng.uniform(8.0, 12.0), 2) for z in zones},
                "ctrl_clock_offset_min": {z: rng.randrange(2000, 200000) for z in zones},
                "seq0": {z: rng.randrange(20000, 900000) for z in zones},
                "comp_kw": {z: round(rng.uniform(4.0, 9.0), 1) for z in zones}, "heater_kw": round(rng.uniform(5.0, 7.5), 1)}
    offsets = {c: 0 for c in CHANNELS}
    off_pool = ["badge", "cctv", "exif", "probe"]
    rng.shuffle(off_pool)
    for c in off_pool[:tier["offset_channels"]]:
        offsets[c] = {"badge": rng.choice([7, 9, 11, 13, 16, 19]) * rng.choice([1, -1]), "cctv": rng.choice([-6, -4, -3, 3, 5]),
                      "exif": rng.choice([-60, 60, -120]), "probe": rng.choice([-8, -5, 5, 8])}[c]
    world = {
        "seed": seed, "tier": tier_name, "tier_knobs": tier, "names": names,
        "zones": {**zinfo, "controller": names["controller"]},
        "params": params, "nuisance": nuisance,
        "sim": {"start_iso": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "days": days, "step_min": 1},
        "actors": actors, "handheld": handheld, "forklifts": forklifts,
        "lots_initial": [dict(l) for l in lots],
        "ledger": {"door_intervals": door_intervals, "moves": moves, "probe_checks": probe_checks, "receiving": receiving,
                   "badge": badge, "walkthroughs": walkthroughs, "props": props, "firmware_flash": firmware_flash,
                   "setpoint_changes": [], "power_outages": power_outages, "sensor_drift": sensor_drift},
        "plan": {"flash_day": flash_day, "hotfix_day": hotfix_day, "incident_day": incident_day, "receiving_zones": receiving_zones,
                 "hotfix_t": (hotfix_day) * 1440 + 10 * 60 + rng.randrange(0, 200),
                 "override_t": (hotfix_day) * 1440 + 26 * 60 + rng.randrange(0, 90),
                 "archive_t": (hotfix_day + 1) * 1440 + 9 * 60 + rng.randrange(0, 240),
                 "lab_email_day": 26, "postmortem_day": 27, "power_outage": power_outages[0], "drift_zone": drift_zone,
                 "other_flashed": other, "probe_excluded": probe_excluded, "recal_t": recal_t,
                 "badge_reader_outage": {"reader": f"ROOM-{inc_zone}", "t0": (incident_day - 3) * 1440 + 9 * 60, "t1": (incident_day + 2) * 1440 + 16 * 60},
                 "fl2_outage": {"forklift": "FL-2", "t0": (incident_day + 1) * 1440 + 6 * 60, "t1": (incident_day + 3) * 1440 + 8 * 60},
                 "diskfull": {"t0": (incident_day + 1) * 1440 + 12 * 60 + rng.randrange(0, 15), "t1": (incident_day + 1) * 1440 + 15 * 60 + rng.randrange(0, 20)},
                 "cctv_retention_days": 7},
        "distortion": {"clock_offsets_min": offsets, "p_mislabel": tier["p_mislabel"], "n_red_herrings": tier["n_red_herrings"],
                       "n_decoys": tier["n_decoys"], "false_claim_rate": tier["false_claim_rate"]},
    }
    # lots_initial must be the inventory at t=0: undo the moves applied above
    for l in world["lots_initial"]:
        pass
    initial = {l["lot_id"]: l for l in world["lots_initial"]}
    for mv in reversed(moves):
        initial[mv["lot"]]["zone"] = mv["from"]
    return world


def world_iso(world: dict, t_min: int) -> str:
    start = dt.datetime.strptime(world["sim"]["start_iso"], "%Y-%m-%dT%H:%M:%SZ")
    return _iso(start, t_min)


def run_sim(world: dict) -> dict:
    rng = random.Random(f"sim:{world['seed']}:{world['tier']}")
    sim = mechanism.simulate(world, rng)
    z = world["zones"]["incident_zone"]
    thr = world["zones"]["excursion_threshold"][z]
    wins = mechanism.excursion_windows(sim, z, thr, min_len=30)
    inc = [d for d in world["ledger"]["props"] if d.get("incident")][0]
    lo, hi = inc["t0"] - 30, inc["t1"] + 300
    above = [t for t in range(max(0, lo), min(len(sim["T_true"][z]), hi)) if sim["T_true"][z][t] > thr]
    hit = [(above[0], above[-1] + 1)] if len(above) >= 120 else []
    sim_tmax = max(sim["T_true"][z][max(0, lo):hi]) if hi > lo else None
    p = world["params"]
    nm = mechanism.near_misses(sim, p["lockout"]["N"], p["lockout"]["W_min"])
    lock_zones = [e[1] for e in sim["lockouts"]]
    lo, hi = mechanism.w_bracket(sim, p["lockout"]["N"])
    sim["checks"] = {
        "w_bracket": [lo, hi], "excursion_windows": wins, "incident_window": hit[0] if hit else None,
        "n_lockouts": len(sim["lockouts"]), "lockout_zones": lock_zones,
        "incident_lockout": any(e[1] == z and inc["t0"] <= e[0] <= inc["t1"] for e in sim["lockouts"]),
        "n_near_misses": len(nm), "near_misses": nm, "n_trips": len(sim["trips"]),
        "n_collisions": len(sim["collisions"]), "duty": {zz: round(mechanism.duty_cycle(sim, zz), 3) for zz in world["zones"]["order"]},
        "incident_tmax": round(sim_tmax, 1) if sim_tmax is not None else None, "incident_threshold": thr,
        "n_defrosts": sum(1 for e in sim["frames"] if e["clauses"][0].get("event") == "DEFROST_ENTER"),
    }
    return sim


def stagger_determined(collisions: list[dict], order: list[str]) -> bool:
    # every adjacent pair in the hidden order must be implied by observed collisions (transitively)
    import itertools
    before = set()
    for c in collisions:
        w = c["winner"]
        for z in c["requested"]:
            if z != w:
                before.add((w, z))
    changed = True
    while changed:
        changed = False
        for (a, b), (c, d) in itertools.product(list(before), list(before)):
            if b == c and (a, d) not in before:
                before.add((a, d)); changed = True
    return all((order[i], order[i + 1]) in before for i in range(len(order) - 1))


def world_ok(world: dict, sim: dict) -> tuple[bool, str]:
    ck = sim["checks"]
    if not ck["incident_window"]:
        return False, "no excursion in incident window"
    w = ck["incident_window"]
    if w[1] - w[0] < 120:
        return False, f"excursion too short ({w[1]-w[0]} min)"
    if w[0] > world["sim"]["days"] * 1440 - 8 * 1440:
        return False, "incident too late in the window"
    if not ck["incident_lockout"]:
        return False, "no lockout during the propped-door night"
    if ck["n_lockouts"] < 3 or ck["n_lockouts"] > 8:
        return False, f"lockouts={ck['n_lockouts']}"
    if ck["n_near_misses"] < 3:
        return False, f"near_misses={ck['n_near_misses']}"
    lo, hi = ck["w_bracket"]
    W = world["params"]["lockout"]["W_min"]
    if lo is None or hi is None or not (lo <= W <= hi) or hi - lo > 12:
        return False, f"W bracket {ck['w_bracket']} for W={W}"
    if ck["n_collisions"] < 4:
        return False, f"collisions={ck['n_collisions']}"
    if not stagger_determined(sim["collisions"], world["params"]["stagger_order"]):
        return False, "stagger order not determined by collisions"
    if any(d > 0.85 or d < 0.15 for d in ck["duty"].values()):
        return False, f"duty out of range {ck['duty']}"
    return True, "ok"


def find_world(seed: int, tier_name: str = "default", max_tries: int = 40, verbose: bool = False) -> tuple[dict, dict, int]:
    reasons = []
    for k in range(max_tries):
        w = build_world(seed * 1000 + k, tier_name)
        w["seed"], w["sub_seed"] = seed, k
        s = run_sim(w)
        ok, why = world_ok(w, s)
        w["build_check"] = why
        reasons.append(why)
        if verbose:
            ck = s["checks"]
            print(f"  try {k}: {why} | lock={ck['lockout_zones']} nm={ck['n_near_misses']} coll={ck['n_collisions']} win={ck['incident_window']} tmax={ck['incident_tmax']}/{ck['incident_threshold']} defr={ck['n_defrosts']} W={ck['w_bracket']}")
        if ok:
            return w, s, k
    raise RuntimeError(f"no valid world for seed {seed} in {max_tries} tries: {reasons}")


if __name__ == "__main__":
    import json, sys, time
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    t0 = time.time()
    w, s, k = find_world(seed, verbose=True, max_tries=40)
    ck = s["checks"]
    print(json.dumps({"seed": seed, "sub_seed": k, "secs": round(time.time() - t0, 1), "incident_zone": w["zones"]["incident_zone"],
                      "incident_window": ck["incident_window"], "lockouts": ck["lockout_zones"], "near_misses": ck["n_near_misses"],
                      "trips": ck["n_trips"], "collisions": ck["n_collisions"], "duty": ck["duty"], "frames": len(s["frames"]),
                      "params": {kk: w["params"][kk] for kk in ("door_gain", "c_adj", "defrost", "trip", "lockout", "stagger_order")}}, indent=1))
