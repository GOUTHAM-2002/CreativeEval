import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gen.notation import EVENT_RENDER, SENSORS, STATES, Notation  # noqa: E402

CANARIES = ("truth", "seed", "generator", "eval", "answer")
MUST_KNOW = ("HDR", "ZONE_A", "ZONE_B", "ZONE_C", "ZONE_D", "ZONE_E", "ZONE_F", "RUN", "IDLE",
             "AIR_TEMP", "SETPOINT", "COMPRESSOR", "READ")
MUST_NOT_KNOW = ("DEFROST", "TRIP", "LOCKOUT", "DOOR", "HEATER", "DISCH_PRESSURE", "COIL_TEMP", "ABS",
                 "QUEUE", "OVERFLOW", "RECOVERY", "FAULT", "OPEN", "CLOSED", "ON", "OFF", "HIGH", "LOW",
                 "STALE", "ENTER", "EXIT", "CLEAR", "BOOT", "FIRMWARE")


def make_frame(rng, nt):
    zone = rng.choice(nt.zones)
    fw = rng.choice(["3.2", "3.4"])
    sp = round(rng.uniform(-25, 5), 1)
    clauses = []
    for _ in range(rng.randint(1, 4)):
        kind = rng.choice(["READ", "STATE", "EVENT"])
        if kind == "READ":
            s = rng.choice(SENSORS)
            v = round(rng.uniform(0, 30), 1) if s == "DISCH_PRESSURE" else round(rng.uniform(-45, 15), 1)
            clauses.append({"kind": "READ", "sensor": s, "zone": zone, "value": v})
        elif kind == "STATE":
            clauses.append({"kind": "STATE", "state": rng.choice(STATES), "zone": zone})
        else:
            ev = rng.choice(sorted(EVENT_RENDER))
            v = None
            if ev == "BOOT":
                v = 34.0 if fw == "3.4" else 32.0
            elif ev == "SETPOINT_SET":
                v = round(rng.uniform(-25, 5), 1)
            elif ev == "QUEUE_OVERFLOW":
                v = float(rng.randint(1, 500))
            clauses.append({"kind": "EVENT", "event": ev, "zone": zone, "value": v})
    # fw is inferred from ABS, so a 3.4 frame must carry a temperature read
    if fw == "3.4" and not any(c["kind"] == "READ" and c["sensor"] != "DISCH_PRESSURE" for c in clauses):
        clauses.insert(0, {"kind": "READ", "sensor": "AIR_TEMP", "zone": zone,
                           "value": round(rng.uniform(-45, 15), 1)})
    frame = {"ctrl_id": nt.controllers[zone], "zone": zone, "seq": rng.randint(0, 10 ** 6),
             "t_ctrl_min": rng.randint(0, 10 ** 6), "fw": fw, "clauses": clauses}
    return frame, sp


def test_roundtrip():
    for seed in range(1, 6):
        nt = Notation(random.Random(seed))
        rng = random.Random(1000 + seed)
        for _ in range(200):
            f, sp = make_frame(rng, nt)
            line = nt.encode(dict(f, setpoint=sp))
            assert line.isascii() and "\n" not in line and "  " not in line
            assert nt.decode(line, sp) == f
            assert nt.encode(f, setpoint=sp) == line


def test_decode_without_setpoint():
    nt = Notation(random.Random(11))
    f = {"ctrl_id": "K7-02", "zone": "B", "seq": 5, "t_ctrl_min": 9, "fw": "3.2",
         "clauses": [{"kind": "READ", "sensor": "AIR_TEMP", "zone": "B", "value": -12.5}]}
    c = nt.decode(nt.encode(f, setpoint=-20.0))["clauses"][0]
    assert c["value"] is None and c["raw"] == 575
    f["fw"] = "3.4"
    c = nt.decode(nt.encode(f))["clauses"][0]
    assert c["value"] == -12.5 and "raw" not in c


def test_decode_rejects_garbage():
    nt = Notation(random.Random(11))
    line = nt.encode({"ctrl_id": "K7-01", "zone": "A", "seq": 1, "t_ctrl_min": 2, "fw": "3.2",
                      "clauses": [{"kind": "STATE", "state": "RUN", "zone": "A"}]})
    for bad in ["", "hello world", line + " x", line.replace(" | ", " "), line[:-1], line + "\n"]:
        try:
            nt.decode(bad)
        except ValueError:
            continue
        raise AssertionError("decode accepted %r" % bad)


def test_determinism():
    a, b = Notation(random.Random(42)), Notation(random.Random(42))
    assert a.truth() == b.truth()
    rng = random.Random(7)
    for _ in range(50):
        f, sp = make_frame(rng, a)
        assert a.encode(f, setpoint=sp) == b.encode(f, setpoint=sp)


def test_diversity():
    a, b = Notation(random.Random(1)), Notation(random.Random(2))
    ra, rb = set(a.truth()["glossary"]), set(b.truth()["glossary"])
    assert len(ra & rb) / len(ra) < 0.30


def test_tokenization_unambiguous():
    for seed in range(1, 11):
        nt = Notation(random.Random(seed))
        t = nt.truth()
        roots = [r for r, lab in t["glossary"].items() if not lab.startswith("DIGIT_")]
        digits = set(t["digit_glyphs"])
        assert len(digits) == t["base"] == len(t["digit_glyphs"])
        assert all(len(g) == 2 for g in digits)
        assert all(len(r) == 4 for r in roots) and len(set(roots)) == len(roots)
        root_syls = {r[:2] for r in roots} | {r[2:] for r in roots}
        affix_syls = {a[1:] for a in t["affixes"]}
        assert not (digits & root_syls)
        assert not (digits & affix_syls)
        assert set(t["legacy_roots"]).isdisjoint(t["glossary"])
        assert set(t["known_roots"]) <= set(t["glossary"])
        assert sorted(set(t["affixes"].values())) == ["ASPECT_EVENT", "ASPECT_STATE", "ZONE"]


def test_partial_decoder():
    for seed in (3, 4):
        nt = Notation(random.Random(seed))
        src = nt.render_partial_decoder()
        low = src.lower()
        assert not any(w in low for w in CANARIES)
        ns = {}
        exec(compile(src, "kw7_decode.py", "exec"), ns)
        known = ns["KNOWN_TOKENS"]
        assert ns["BASE"] == nt.base and set(ns["DIGITS"]) == set(nt.digits)
        assert set(known) == set(nt.known_roots())
        for lab in MUST_KNOW:
            assert lab in known.values()
        for lab in MUST_NOT_KNOW:
            assert lab not in known.values()
        for i, g in enumerate(nt.digits):
            assert ns["parse_number"](g) == i
        rng = random.Random(500 + seed)
        for _ in range(50):
            f, sp = make_frame(rng, nt)
            line = nt.encode(f, setpoint=sp)
            out = ns["decode_line"](line, {f["zone"]: sp})
            assert out["ctrl_id"] == f["ctrl_id"] and out["seq"] == f["seq"]
            body = line.split(" | ", 1)[1]
            for tok in body.replace(" ; ", " ").split(" "):
                root = tok.split("-")[0]
                if root[0] in nt.d_cons:
                    assert ns["parse_number"](tok) == nt._parse_num(tok)
                elif root not in known:
                    assert "unk=" + tok in out["unknown"]
            assert len(out["clauses"]) == len(f["clauses"])
            for c, got in zip(f["clauses"], out["clauses"]):
                if c["kind"] == "READ" and c["sensor"] == "AIR_TEMP":
                    if f["fw"] == "3.2":
                        want, raw = c["value"], round((c["value"] - sp) * 10) + 500
                    else:
                        want, raw = c["value"] + sp, round(c["value"] * 10) + 500
                    assert abs(got["value"] - want) < 1e-6 and got["raw"] == raw


def test_quickref():
    for seed in (5, 6):
        nt = Notation(random.Random(seed))
        card, t = nt.render_quickref(), nt.truth()
        assert "KW-7" in card and "2.x" in card
        assert ("Base %d" % t["base"]) in card
        for g in t["digit_glyphs"]:
            assert g in card
        for old in t["legacy_roots"]:
            assert old in card
        assert nt.root["ABS"] not in card
        assert len(t["legacy_roots"]) == 4
        assert sorted(t["legacy_roots"].values()) == ["DEFROST", "DOOR", "LOCKOUT", "TRIP"]
        for lab in ("DEFROST", "TRIP", "LOCKOUT", "DOOR"):
            assert nt.root[lab] not in card
        assert " ; " in card and "|" in card
        assert not any(w in card.lower() for w in CANARIES)
