import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gen.protocol import EVENT_RENDER, SENSORS, STATES, Protocol  # noqa: E402
from grader.sections import protocol as protocol_section  # noqa: E402

CANARIES = ("truth", "seed", "generator", "eval", "answer", "hidden")
CTRL = {z: "RH07-%02d" % (i + 1) for i, z in enumerate("ABCDEF")}


def mk(seed):
    return Protocol(random.Random(seed), zones=list("ABCDEF"), controllers=CTRL)


def status_frame(rng, p, fw=None):
    zone = rng.choice(p.zones)
    fw = fw or rng.choice(["3.2", "3.4"])
    sp = round(rng.uniform(-30, 6), 1)
    f = {"ctrl_id": p.controllers[zone], "zone": zone, "seq": rng.randint(0, 2 ** 24 - 1),
         "t_ctrl_min": rng.randint(0, 250000), "fw": fw,
         "clauses": [{"kind": "READ", "sensor": "AIR_TEMP", "zone": zone, "value": round(sp + rng.uniform(-2, 12), 1)},
                     {"kind": "READ", "sensor": "COIL_TEMP", "zone": zone, "value": round(sp + rng.uniform(-8, 6), 1)},
                     {"kind": "READ", "sensor": "DISCH_PRESSURE", "zone": zone, "value": round(rng.uniform(0, 30), 1)},
                     {"kind": "STATE", "state": rng.choice(STATES), "zone": zone}]}
    if rng.random() < 0.3:
        f["door_open"] = True
    return f, sp


def event_frame(rng, p, ev=None):
    zone = rng.choice(p.zones)
    ev = ev or rng.choice(sorted(EVENT_RENDER))
    fw = rng.choice(["3.2", "3.4"])
    v = None
    if ev == "BOOT":
        v = 34.0 if fw == "3.4" else 32.0
    elif ev == "SETPOINT_SET":
        v = round(rng.uniform(-30, 6), 1)
    elif ev == "QUEUE_OVERFLOW":
        v = float(rng.randint(0, 5000))
    f = {"ctrl_id": p.controllers[zone], "zone": zone, "seq": rng.randint(0, 2 ** 24 - 1),
         "t_ctrl_min": rng.randint(0, 250000), "fw": fw,
         "clauses": [{"kind": "EVENT", "event": ev, "zone": zone, "value": v}]}
    return f, round(rng.uniform(-30, 6), 1)


def expected(f):
    e = {k: v for k, v in f.items() if k != "setpoint"}
    c0 = f["clauses"][0]
    if c0["kind"] == "EVENT" and c0["event"] != "BOOT":
        e["fw"] = "3.2"
    return e


def test_roundtrip():
    units = set()
    for seed in range(1, 6):
        p = mk(seed)
        units.add(p.tick_unit_s)
        rng = random.Random(1000 + seed)
        for i in range(300):
            if i % 2 == 0:
                f, sp = status_frame(rng, p)
            else:
                f, sp = event_frame(rng, p, sorted(EVENT_RENDER)[i % len(EVENT_RENDER)])
            line = p.encode(dict(f, setpoint=sp))
            assert line.isascii() and "\n" not in line and line.startswith("$") and "*" in line
            assert p.decode(line, sp) == expected(f)
            assert p.encode(f, setpoint=sp) == line
    assert len(units) >= 2


def test_all_tick_units_exact():
    for unit in (60, 10, 1):
        p = mk(1)
        p.tick_unit_s = unit
        f, sp = status_frame(random.Random(5), p)
        f["t_ctrl_min"] = 200003
        d = p.decode(p.encode(f, setpoint=sp), sp)
        assert d["t_ctrl_min"] == 200003 and isinstance(d["t_ctrl_min"], int)


def test_multi_event_frame_two_lines():
    p = mk(2)
    f = {"ctrl_id": CTRL["C"], "zone": "C", "seq": 77, "t_ctrl_min": 900, "fw": "3.2",
         "clauses": [{"kind": "EVENT", "event": "DEFROST_ENTER", "zone": "C", "value": None},
                     {"kind": "EVENT", "event": "HEATER_ON", "zone": "C", "value": None}]}
    lines = p.encode(f).split("\n")
    assert len(lines) == 2
    evs = [p.decode(l)["clauses"][0]["event"] for l in lines]
    assert evs == ["DEFROST_ENTER", "HEATER_ON"]
    assert all(p.decode(l)["seq"] == 77 for l in lines)
    try:
        p.decode(p.encode(f))
    except ValueError:
        pass
    else:
        raise AssertionError("decode accepted two lines")


def test_decode_without_setpoint():
    p = mk(11)
    f = {"ctrl_id": CTRL["B"], "zone": "B", "seq": 5, "t_ctrl_min": 9, "fw": "3.2",
         "clauses": [{"kind": "READ", "sensor": "AIR_TEMP", "zone": "B", "value": -12.5},
                     {"kind": "READ", "sensor": "COIL_TEMP", "zone": "B", "value": -18.0},
                     {"kind": "READ", "sensor": "DISCH_PRESSURE", "zone": "B", "value": 3.0},
                     {"kind": "STATE", "state": "RUN", "zone": "B"}]}
    c = p.decode(p.encode(f, setpoint=-20.0))["clauses"][0]
    assert c["value"] is None and c["raw"] == round(7.5 * p.temp_scale) + p.temp_offset
    f["fw"] = "3.4"
    d = p.decode(p.encode(f))
    assert d["fw"] == "3.4" and d["clauses"][0]["value"] == -12.5 and "raw" not in d["clauses"][0]


def test_checksum_and_garbage_rejected():
    p = mk(11)
    f, sp = status_frame(random.Random(3), p, fw="3.2")
    line = p.encode(f, setpoint=sp)
    body = line[1:line.rindex("*")]
    flipped = "%02X" % ((int(line[-2:], 16) + 1) & 0xFF)
    bads = ["", "hello", line + " x", line[:-1], line + "\n", line.lower(), "$" + body + "*" + flipped,
            "$" + body.replace(",", ";", 1) + "*" + line[-2:], "$" + body[:-1] + ("1" if body[-1] != "1" else "2") + "*" + line[-2:]]
    for bad in bads:
        try:
            p.decode(bad)
        except ValueError:
            continue
        raise AssertionError("decode accepted %r" % bad)


def test_determinism():
    a, b = mk(42), mk(42)
    assert a.truth() == b.truth()
    assert a.render_partial_decoder() == b.render_partial_decoder()
    assert a.render_quickref() == b.render_quickref()
    rng = random.Random(7)
    for _ in range(50):
        f, sp = status_frame(rng, a)
        assert a.encode(f, setpoint=sp) == b.encode(f, setpoint=sp)


def test_diversity():
    ts = [mk(s).truth() for s in range(1, 9)]
    for i in range(len(ts)):
        for j in range(i + 1, len(ts)):
            assert ts[i]["types"] != ts[j]["types"]
    assert len({t["checksum"] for t in ts}) == 2
    assert len({t["tick_unit_s"] for t in ts}) >= 2
    assert len({tuple(t["status_words"]) for t in ts}) >= 3


def test_truth_shape():
    for seed in range(1, 11):
        t = mk(seed).truth()
        assert sorted(t["types"].values()) == sorted(["STATUS", "DOOR", "TRIP", "LOCKOUT", "DEFROST", "HEATER", "BOOT", "SETPOINT", "QUEUE_OVERFLOW"])
        codes = [int(k, 16) for k in t["types"]]
        assert len(set(codes)) == 9 and all(0x10 <= c <= 0xFE for c in codes)
        assert sorted(t["status_words"]) == ["AIR_TEMP", "COIL_TEMP", "DISCH_PRESSURE", "STATE_FLAGS"]
        assert t["temp_scale"] in (10, 16, 32) and t["temp_offset"] in (400, 500, 1000) and t["press_scale"] in (10, 100)
        assert t["tick_unit_s"] in (60, 10, 1) and t["checksum"] in ("xor", "sum")
        bits = t["flag_bits"]
        assert sorted(bits) == ["ABS_TEMP", "DEFROST", "DOOR_OPEN", "LOCKOUT", "RECOVERY", "RUN"]
        assert len(set(bits.values())) == 6 and all(0 <= b <= 15 for b in bits.values()) and 12 <= bits["ABS_TEMP"] <= 15
        assert t["event_words"]["DOOR"] == {"0001": "OPEN", "0000": "CLOSED"}
        assert t["v34_change"] == "absolute_temp"
        assert sorted(t["legacy_types"].values()) == ["DEFROST", "DOOR", "LOCKOUT", "TRIP"]
        assert set(t["legacy_types"]).isdisjoint(t["types"])
        assert len(t["quickref_wrong_positions"]) == 2
        st = next(k for k, v in t["types"].items() if v == "STATUS")
        assert "type:" + st in t["known"] and "flag:RUN" in t["known"]
        assert set(t["known"]) == set(mk(seed).known_roots())


def test_partial_decoder():
    for seed in (3, 4, 5):
        p = mk(seed)
        src = p.render_partial_decoder()
        low = src.lower()
        assert not any(w in low for w in CANARIES)
        ns = {}
        exec(compile(src, "rh7_decode.py", "exec"), ns)
        for name in ("checksum", "parse_frame", "decode_line", "KNOWN_TYPES"):
            assert name in ns
        assert set(ns["KNOWN_TYPES"]) == {p.types["STATUS"]}
        assert "controller-local counter, unused" in src
        rng = random.Random(500 + seed)
        for i in range(60):
            if i % 2 == 0:
                f, sp = status_frame(rng, p)
            else:
                f, sp = event_frame(rng, p)
            for line in p.encode(f, setpoint=sp).split("\n"):
                out = ns["decode_line"](line, {f["zone"]: sp})
                assert out["ctrl_id"] == f["ctrl_id"] and out["seq"] == f["seq"]
                _, _, _, typ, words = p.parse(line)
                if typ != p.types["STATUS"]:
                    assert out["unknown"] == ["type=0x%02x words=%s" % (typ, " ".join("%04x" % w for w in words))]
                    assert out["clauses"][0]["head"] == "unknown_type" and out["clauses"][0]["zone"] == f["zone"]
                    continue
                known_pos = {p.status_words.index("AIR_TEMP"), p.status_words.index("STATE_FLAGS")}
                want_unknown = ["word[%d]=0x%04x" % (k, w) for k, w in enumerate(words) if k not in known_pos]
                assert out["unknown"] == want_unknown
                heads = {c["head"]: c for c in out["clauses"]}
                true_air = f["clauses"][0]["value"]
                if f["fw"] == "3.2":
                    assert abs(heads["AIR_TEMP"]["value"] - true_air) < 1e-6
                else:
                    assert abs(heads["AIR_TEMP"]["value"] - round(true_air + sp, 1)) < 1e-6
                state = f["clauses"][3]["state"]
                assert ("RUN" in heads) == (state in ("RUN", "RECOVERY"))
        bad = p.encode(f, setpoint=sp).split("\n")[0]
        bad = bad[:-2] + "%02X" % ((int(bad[-2:], 16) ^ 0x5A) & 0xFF)
        try:
            ns["decode_line"](bad, {})
        except ValueError:
            pass
        else:
            raise AssertionError("partial decoder accepted a bad checksum")


def test_quickref():
    for seed in (5, 6, 7):
        p = mk(seed)
        card, t = p.render_quickref(), p.truth()
        low = card.lower()
        assert "2.x" in card and "controller-local counter" in card
        assert ("exclusive-OR" in card) == (t["checksum"] == "xor")
        assert ("modulo 256" in card) == (t["checksum"] == "sum")
        for code, lab in t["legacy_types"].items():
            assert ("%s  %s" % (code.upper(), lab)) in card
        assert "ABS" not in card and "absolute" not in low
        for lab in ("HEATER", "BOOT", "SETPOINT", "QUEUE"):
            assert lab not in card
        printed = [line.split()[1] for line in card.splitlines() if line.strip().startswith("w") and line.split()[0] in ("w0", "w1", "w2", "w3")]
        assert len(printed) == 4 and sorted(printed) == sorted(t["status_words"])
        i, j = t["quickref_wrong_positions"]
        assert printed[i] == t["status_words"][j] and printed[j] == t["status_words"][i]
        for k in range(4):
            if k not in (i, j):
                assert printed[k] == t["status_words"][k]
        ex = next(line for line in card.splitlines() if "Example:" in line).split("Example:", 1)[1].strip()
        p.parse(ex)
        assert not any(w in low for w in CANARIES)
        assert 40 <= len(card.splitlines()) <= 60


def _truth_with_heldout(p):
    t = p.truth()
    t["heldout"] = [{"seq": 10, "ts": "2026-05-24T01:00:00Z", "zone": "E", "event": "AIR_TEMP", "value": -19.6, "tol_value": 0.2, "tol_s": 120},
                    {"seq": 11, "ts": "2026-05-24T01:02:00Z", "zone": "E", "event": "DOOR", "value": None, "tol_value": 0.2, "tol_s": 120}]
    return t


def _perfect(t):
    known = {k.split(":", 1)[1] for k in t["known"] if k.startswith("type:")}
    return {"types": {k: v for k, v in t["types"].items() if k not in known},
            "status_words": list(t["status_words"]), "temp_scale": t["temp_scale"], "temp_offset": t["temp_offset"],
            "press_scale": t["press_scale"], "flag_bits": dict(t["flag_bits"]), "v34_change": t["v34_change"],
            "heldout": [{k: f[k] for k in ("seq", "ts", "zone", "event", "value")} for f in t["heldout"]]}


def test_grader_section():
    cfg = {"vacuous_component_score": 1.0, "section_mix": {}}
    for seed in (1, 2):
        t = _truth_with_heldout(mk(seed))
        res = protocol_section.score(_perfect(t), t, cfg)
        assert res["score"] == 1.0 and res["n_unknown_types"] == 8 and res["types_hits"] == 8
        assert res["flag_hits"] == 6 and res["status_words_pts"] == 1.0 and res["scales_acc"] == 1.0
        assert res["heldout_frames_full"] == 2
        for empty in ({}, None, [], "x"):
            assert protocol_section.score(empty, t, cfg)["score"] == 0.0
        ans = _perfect(t)
        ans["types"] = {"0x" + k.upper(): v for k, v in ans["types"].items()}
        assert protocol_section.score(ans, t, cfg)["types_acc"] == 1.0
        ans["status_words"] = list(reversed(ans["status_words"]))
        ans["flag_bits"]["RUN"] = 99
        ans["temp_scale"] = 1
        ans["v34_change"] = "none"
        ans["heldout"] = []
        res = protocol_section.score(ans, t, cfg)
        assert res["status_words_pts"] == 0.0 and res["flag_hits"] == 5 and res["scales_hits"] == 2
        assert res["v34"]["pts"] == 0.0 and res["heldout_mean"] == 0.0
        want = 0.30 * 1.0 + 0.10 * 0 + 0.15 * (2 / 3) + 0.10 * (5 / 6) + 0.05 * 0 + 0.30 * 0
        assert abs(res["score"] - want) < 1e-9
        assert json.dumps(res)


def test_mix_override():
    t = _truth_with_heldout(mk(3))
    cfg = {"vacuous_component_score": 1.0, "section_mix": {"protocol": {"types_acc": 1.0, "status_words": 0, "scales": 0, "flag_bits": 0, "v34": 0, "heldout_mean": 0}}}
    ans = {"types": {k: "STATUS" for k in t["types"]}}
    assert protocol_section.score(ans, t, cfg)["score"] == 0.0
    ans = _perfect(t)
    ans["heldout"] = []
    assert protocol_section.score(ans, t, cfg)["score"] == 1.0


def test_label_of_and_sensors():
    p = mk(9)
    assert SENSORS == ("AIR_TEMP", "COIL_TEMP", "DISCH_PRESSURE")
    st = "%02x" % p.types["STATUS"]
    assert p.label_of("type:" + st) == "STATUS"
    assert p.label_of("%s:word%d" % (st, p.status_words.index("COIL_TEMP"))) == "COIL_TEMP"
    assert p.label_of("flag:ABS_TEMP") == "ABS_TEMP"
    try:
        p.label_of("type:ff")
    except ValueError:
        pass
    else:
        raise AssertionError("label_of accepted an unknown key")
