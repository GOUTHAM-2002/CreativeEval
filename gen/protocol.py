"""RH-7 wire format: per-seed undocumented ASCII/hex telemetry protocol for the controllers.

Line: $<UNIT>,<SEQ>,<TICK>,<TYPE>,<W0> <W1> ... <Wn>*<CS>. Per seed: type codes, STATUS word
order, temperature SCALE/OFFSET, pressure scale, tick unit, checksum variant, flag bit positions.
Firmware 3.2 reports temperatures as deltas from the setpoint, 3.4 as absolutes with the ABS_TEMP flag.
"""

import random
import re

STATES = ("RUN", "IDLE", "DEFROST", "RECOVERY", "LOCKOUT")
SENSORS = ("AIR_TEMP", "COIL_TEMP", "DISCH_PRESSURE")
TEMP_SENSORS = ("AIR_TEMP", "COIL_TEMP")
STATUS_WORDS = ("AIR_TEMP", "COIL_TEMP", "DISCH_PRESSURE", "STATE_FLAGS")
EVENT_RENDER = {
    "DOOR_OPEN": ("DOOR", "OPEN"),
    "DOOR_CLOSE": ("DOOR", "CLOSED"),
    "TRIP": ("TRIP", "FAULT"),
    "LOCKOUT_ENTER": ("LOCKOUT", "ENTER"),
    "LOCKOUT_EXIT": ("LOCKOUT", "EXIT"),
    "DEFROST_ENTER": ("DEFROST", "ENTER"),
    "DEFROST_EXIT": ("DEFROST", "EXIT"),
    "HEATER_ON": ("HEATER", "ON"),
    "HEATER_OFF": ("HEATER", "OFF"),
    "BOOT": ("FIRMWARE", "BOOT"),
    "SETPOINT_SET": ("SETPOINT", "SET"),
    "QUEUE_OVERFLOW": ("QUEUE", "OVERFLOW"),
}
VALUED_EVENTS = ("BOOT", "SETPOINT_SET", "QUEUE_OVERFLOW")
TYPE_LABELS = ("STATUS", "DOOR", "TRIP", "LOCKOUT", "DEFROST", "HEATER", "BOOT", "SETPOINT", "QUEUE_OVERFLOW")
LEGACY_LABELS = ("DEFROST", "TRIP", "LOCKOUT", "DOOR")
HEAD_TYPE = {"FIRMWARE": "BOOT", "QUEUE": "QUEUE_OVERFLOW"}
SUBCODE = {"OPEN": 1, "CLOSED": 0, "FAULT": 1, "ENTER": 1, "EXIT": 0, "ON": 1, "OFF": 0}
FLAG_LABELS = ("RUN", "DEFROST", "LOCKOUT", "RECOVERY", "DOOR_OPEN")
TEMP_COMBOS = ((10, 400), (10, 500), (10, 1000), (16, 500), (16, 1000), (32, 1000))   # OFFSET/SCALE >= 31.25 degC
PRESS_SCALES = (10, 100)
TICK_UNITS = (60, 10, 1)
_LINE_RE = re.compile(r"^\$([A-Za-z0-9_-]+),([0-9A-F]{6}),([0-9A-F]{6}),([0-9A-F]{2}),([0-9A-F]{4}(?: [0-9A-F]{4})*)\*([0-9A-F]{2})$")


def _r1(x):
    return round(x, 1)


class Protocol:
    EVENT_RENDER = EVENT_RENDER

    def __init__(self, rng, zones=None, controllers=None):
        self.zones = list(zones) if zones is not None else ["A", "B", "C", "D", "E", "F"]
        if controllers is None:
            controllers = {z: "RH07-%02d" % (i + 1) for i, z in enumerate(self.zones)}
        self.controllers = {z: controllers[z] for z in self.zones}
        self._zone_of_ctrl = {c: z for z, c in self.controllers.items()}
        self._event_of_pair = {v: k for k, v in EVENT_RENDER.items()}
        self._build(rng)

    # ---- per-seed choices ---------------------------------------------------------------
    def _build(self, rng):
        codes = rng.sample(range(0x10, 0xFF), len(TYPE_LABELS) + len(LEGACY_LABELS))
        self.types = dict(zip(TYPE_LABELS, codes[:len(TYPE_LABELS)]))
        self._label_of_type = {c: lab for lab, c in self.types.items()}
        self.legacy_types = dict(zip(codes[len(TYPE_LABELS):], LEGACY_LABELS))
        self.status_words = list(STATUS_WORDS)
        rng.shuffle(self.status_words)
        self._pos = {w: i for i, w in enumerate(self.status_words)}
        self.temp_scale, self.temp_offset = rng.choice(TEMP_COMBOS)
        self.press_scale = rng.choice(PRESS_SCALES)
        self.tick_unit_s = rng.choice(TICK_UNITS)
        self.checksum_kind = rng.choice(["xor", "sum"])
        abs_bit = rng.randint(12, 15)
        others = rng.sample([b for b in range(16) if b != abs_bit], len(FLAG_LABELS))
        self.flag_bits = dict(zip(FLAG_LABELS, others))
        self.flag_bits["ABS_TEMP"] = abs_bit
        i, j = rng.sample(range(4), 2)
        self.quickref_wrong_positions = sorted([i, j])
        self.glossary = {}
        for lab, c in self.types.items():
            self.glossary["type:%02x" % c] = lab
        for w, i in self._pos.items():
            self.glossary["%02x:word%d" % (self.types["STATUS"], i)] = w
        for lab in ("DOOR", "TRIP", "LOCKOUT", "DEFROST", "HEATER"):
            self.glossary["%02x:word0" % self.types[lab]] = lab + "_SUBCODE"
        self.glossary["%02x:word0" % self.types["BOOT"]] = "FW_BCD"
        self.glossary["%02x:word0" % self.types["SETPOINT"]] = "TEMP"
        self.glossary["%02x:word0" % self.types["QUEUE_OVERFLOW"]] = "COUNT"
        for lab in self.flag_bits:
            self.glossary["flag:" + lab] = lab

    # ---- public helpers -------------------------------------------------------------------
    def known_roots(self):
        s = self.types["STATUS"]
        return ["type:%02x" % s, "%02x:word%d" % (s, self._pos["AIR_TEMP"]), "%02x:word%d" % (s, self._pos["STATE_FLAGS"]), "flag:RUN"]

    def label_of(self, key):
        if key not in self.glossary:
            raise ValueError("unknown key %r" % key)
        return self.glossary[key]

    def event_words(self):
        out = {}
        for ev, (head, sub) in EVENT_RENDER.items():
            if sub in SUBCODE:
                out.setdefault(head, {})["%04X" % SUBCODE[sub]] = sub
        out["BOOT"] = {"0032": "FW_3.2", "0034": "FW_3.4"}
        out["SETPOINT"] = {"*": "TEMP"}
        out["QUEUE_OVERFLOW"] = {"*": "COUNT"}
        return out

    def truth(self):
        return {
            "checksum": self.checksum_kind,
            "tick_unit_s": self.tick_unit_s,
            "types": {"%02x" % c: lab for lab, c in self.types.items()},
            "status_words": list(self.status_words),
            "temp_scale": self.temp_scale,
            "temp_offset": self.temp_offset,
            "press_scale": self.press_scale,
            "flag_bits": dict(self.flag_bits),
            "event_words": self.event_words(),
            "known": self.known_roots(),
            "v34_change": "absolute_temp",
            "quickref_wrong_positions": list(self.quickref_wrong_positions),
            "legacy_types": {"%02x" % c: lab for c, lab in self.legacy_types.items()},
        }

    # ---- encode ---------------------------------------------------------------------------
    def _cs(self, body):
        data = body.encode("ascii")
        if self.checksum_kind == "xor":
            c = 0
            for b in data:
                c ^= b
            return c
        return sum(data) & 0xFF

    def _line(self, unit, seq, t_ctrl_min, typ, words):
        if seq < 0 or t_ctrl_min < 0:
            raise ValueError("negative seq/tick")
        tick = (int(t_ctrl_min) * 60 // self.tick_unit_s) & 0xFFFFFF
        body = "%s,%06X,%06X,%02X,%s" % (unit, int(seq) & 0xFFFFFF, tick, typ, " ".join("%04X" % w for w in words))
        return "$" + body + "*%02X" % self._cs(body)

    def _temp_word(self, x):
        n = round(x * self.temp_scale) + self.temp_offset
        if not -0x8000 <= n <= 0x7FFF:
            raise ValueError("temperature %r out of range" % x)
        return n & 0xFFFF

    def _temp_val(self, w):
        n = w - 0x10000 if w >= 0x8000 else w
        return (n - self.temp_offset) / self.temp_scale

    def _word16(self, n, what):
        n = int(n)
        if not 0 <= n <= 0xFFFF:
            raise ValueError("%s %r out of range" % (what, n))
        return n

    def _status_words(self, clauses, fw, setpoint, door_open):
        reads = {c["sensor"]: c for c in clauses if c.get("kind") == "READ"}
        states = [c for c in clauses if c.get("kind") == "STATE"]
        if len(clauses) != 4 or set(reads) != set(SENSORS) or len(states) != 1:
            raise ValueError("STATUS frame needs one READ per sensor and one STATE")
        state = states[0]["state"]
        if state not in STATES:
            raise ValueError("unknown state %r" % state)
        words = [0] * 4
        for s in TEMP_SENSORS:
            v = reads[s]["value"]
            if fw == "3.4":
                words[self._pos[s]] = self._temp_word(v)
            else:
                if setpoint is None:
                    raise ValueError("fw 3.2 temperature needs a setpoint")
                words[self._pos[s]] = self._temp_word(v - setpoint)
        words[self._pos["DISCH_PRESSURE"]] = self._word16(round(reads["DISCH_PRESSURE"]["value"] * self.press_scale), "pressure")
        fb = self.flag_bits
        flags = 0
        if state in ("RUN", "RECOVERY"):
            flags |= 1 << fb["RUN"]
        if state == "RECOVERY":
            flags |= 1 << fb["RECOVERY"]
        if state == "DEFROST":
            flags |= 1 << fb["DEFROST"]
        if state == "LOCKOUT":
            flags |= 1 << fb["LOCKOUT"]
        if door_open:
            flags |= 1 << fb["DOOR_OPEN"]
        if fw == "3.4":
            flags |= 1 << fb["ABS_TEMP"]
        words[self._pos["STATE_FLAGS"]] = flags
        return words

    def _event_word(self, c, fw):
        ev = c["event"]
        if ev not in EVENT_RENDER:
            raise ValueError("unknown event %r" % ev)
        head, sub = EVENT_RENDER[ev]
        v = c.get("value")
        if ev == "BOOT":
            n = round(v) if v is not None else (34 if fw == "3.4" else 32)
            return self.types["BOOT"], int("%d" % n, 16)
        if ev == "SETPOINT_SET":
            return self.types["SETPOINT"], self._temp_word(v)
        if ev == "QUEUE_OVERFLOW":
            return self.types["QUEUE_OVERFLOW"], self._word16(round(v), "count")
        return self.types[head], SUBCODE[sub]

    def encode(self, frame, setpoint=None):
        if setpoint is None:
            setpoint = frame.get("setpoint")
        ctrl = frame.get("ctrl_id")
        if ctrl not in self._zone_of_ctrl:
            raise ValueError("unknown controller %r" % ctrl)
        zone = self._zone_of_ctrl[ctrl]
        if frame.get("zone") != zone:
            raise ValueError("frame zone %r does not match controller %r" % (frame.get("zone"), ctrl))
        fw = frame.get("fw")
        if fw not in ("3.2", "3.4"):
            raise ValueError("bad fw %r" % fw)
        clauses = frame.get("clauses", [])
        if not clauses:
            raise ValueError("empty frame")
        if any(c.get("zone") != zone for c in clauses):
            raise ValueError("clause zone does not match controller %r" % ctrl)
        seq, tick = frame["seq"], frame["t_ctrl_min"]
        kinds = {c.get("kind") for c in clauses}
        if kinds == {"EVENT"}:
            lines = []
            for c in clauses:
                typ, w = self._event_word(c, fw)
                lines.append(self._line(ctrl, seq, tick, typ, [w]))
            return "\n".join(lines)
        if kinds <= {"READ", "STATE"}:
            words = self._status_words(clauses, fw, setpoint, frame.get("door_open", False))
            return self._line(ctrl, seq, tick, self.types["STATUS"], words)
        raise ValueError("frame mixes EVENT clauses with READ/STATE clauses")

    # ---- decode ---------------------------------------------------------------------------
    def parse(self, line):
        if not isinstance(line, str) or "\n" in line or line != line.strip():
            raise ValueError("bad line")
        m = _LINE_RE.match(line)
        if not m:
            raise ValueError("malformed frame %r" % line[:60])
        unit, seq, tick, typ, words, cs = m.groups()
        if int(cs, 16) != self._cs(line[1:line.rindex("*")]):
            raise ValueError("bad checksum in %r" % line[:60])
        return unit, int(seq, 16), int(tick, 16), int(typ, 16), [int(w, 16) for w in words.split(" ")]

    def _tick_to_min(self, tick):
        tm = tick * self.tick_unit_s
        return tm // 60 if tm % 60 == 0 else tm / 60

    def decode(self, line, setpoint=None):
        unit, seq, tick, typ, words = self.parse(line)
        if unit not in self._zone_of_ctrl:
            raise ValueError("unknown controller %r" % unit)
        zone = self._zone_of_ctrl[unit]
        label = self._label_of_type.get(typ)
        if label is None:
            raise ValueError("unknown type 0x%02X" % typ)
        out = {"ctrl_id": unit, "zone": zone, "seq": seq, "t_ctrl_min": self._tick_to_min(tick), "fw": "3.2", "clauses": []}
        if label == "STATUS":
            if len(words) != 4:
                raise ValueError("STATUS frame needs 4 words")
            flags = words[self._pos["STATE_FLAGS"]]
            fb = self.flag_bits
            is_abs = bool(flags >> fb["ABS_TEMP"] & 1)
            for s in TEMP_SENSORS:
                w = words[self._pos[s]]
                c = {"kind": "READ", "sensor": s, "zone": zone, "value": None}
                if is_abs:
                    c["value"] = _r1(self._temp_val(w))
                elif setpoint is None:
                    c["raw"] = w
                else:
                    c["value"] = _r1(self._temp_val(w) + setpoint)
                out["clauses"].append(c)
            out["clauses"].append({"kind": "READ", "sensor": "DISCH_PRESSURE", "zone": zone,
                                   "value": _r1(words[self._pos["DISCH_PRESSURE"]] / self.press_scale)})
            if flags >> fb["LOCKOUT"] & 1:
                state = "LOCKOUT"
            elif flags >> fb["DEFROST"] & 1:
                state = "DEFROST"
            elif flags >> fb["RECOVERY"] & 1:
                state = "RECOVERY"
            elif flags >> fb["RUN"] & 1:
                state = "RUN"
            else:
                state = "IDLE"
            out["clauses"].append({"kind": "STATE", "state": state, "zone": zone})
            out["fw"] = "3.4" if is_abs else "3.2"
            if flags >> fb["DOOR_OPEN"] & 1:
                out["door_open"] = True
            return out
        if len(words) != 1:
            raise ValueError("%s frame needs 1 word" % label)
        w = words[0]
        if label == "BOOT":
            digits = "%04X" % w
            if not digits.isdigit():
                raise ValueError("bad firmware BCD %s" % digits)
            value = float(int(digits))
            out["fw"] = "3.4" if value == 34 else "3.2"
            out["clauses"].append({"kind": "EVENT", "event": "BOOT", "zone": zone, "value": value})
        elif label == "SETPOINT":
            out["clauses"].append({"kind": "EVENT", "event": "SETPOINT_SET", "zone": zone, "value": _r1(self._temp_val(w))})
        elif label == "QUEUE_OVERFLOW":
            out["clauses"].append({"kind": "EVENT", "event": "QUEUE_OVERFLOW", "zone": zone, "value": float(w)})
        else:
            sub = {v: k for k, v in SUBCODE.items() if (label, k) in self._event_of_pair}.get(w)
            if sub is None:
                raise ValueError("bad %s sub-code %04X" % (label, w))
            out["clauses"].append({"kind": "EVENT", "event": self._event_of_pair[(label, sub)], "zone": zone, "value": None})
        return out

    # ---- shipped artifacts ----------------------------------------------------------------
    def render_partial_decoder(self):
        units = "\n".join('    "%s": "%s",' % (self.controllers[z], z) for z in self.zones)
        return _PARTIAL_SRC % {
            "unit0": self.controllers[self.zones[0]],
            "checksum": self.checksum_kind,
            "status": self.types["STATUS"],
            "w_air": self._pos["AIR_TEMP"],
            "w_flags": self._pos["STATE_FLAGS"],
            "run_bit": self.flag_bits["RUN"],
            "scale": self.temp_scale,
            "offset": self.temp_offset,
            "units": units,
        }

    def render_quickref(self):
        unit0 = self.controllers[self.zones[0]]
        st = self.types["STATUS"]
        i, j = self.quickref_wrong_positions
        layout = list(self.status_words)
        layout[i], layout[j] = layout[j], layout[i]
        gloss = {"AIR_TEMP": "air temperature, offset from the zone setpoint",
                 "COIL_TEMP": "evaporator coil temperature, offset from the zone setpoint",
                 "DISCH_PRESSURE": "compressor discharge pressure",
                 "STATE_FLAGS": "state bits, see below"}
        ex_words = [0] * 4
        for k, w in enumerate(layout):
            ex_words[k] = self.temp_offset if w in TEMP_SENSORS else (0 if w == "STATE_FLAGS" else 8 * self.press_scale)
        example = self._line(unit0, 1, 0, st, ex_words)
        body = example[1:example.rindex("*")]
        cs_words = {"xor": "exclusive-OR", "sum": "arithmetic sum, modulo 256,"}[self.checksum_kind]
        model = unit0.split("-")[0].rstrip("0123456789") or "RH"
        L = []
        L.append("%s-7 CONTROLLER - INTEGRATION NOTE, SERIAL TELEMETRY (firmware 2.x)" % model)
        L.append("=" * 70)
        L.append("Applies to controller firmware 2.0 - 2.6. Keep with the panel documentation.")
        L.append("")
        L.append("1. FRAMING")
        L.append("   One message per line, printable ASCII, terminated by LF.")
        L.append("     $<unit>,<seq>,<tick>,<type>,<w0> <w1> ... <wn>*<cs>")
        L.append("   unit   controller identifier as configured on the panel (e.g. %s)" % unit0)
        L.append("   seq    message counter, 6 hex digits (24 bit), wraps; restarts at 000000 after a reset")
        L.append("   tick   controller-local counter, 6 hex digits (24 bit), see section 2")
        L.append("   type   message type, 2 hex digits, see sections 4 and 5")
        L.append("   w0..wn data words, 4 hex digits each (16 bit), one space between words;")
        L.append("          the number of words depends on the message type")
        L.append("   cs     checksum, 2 hex digits, see section 3")
        L.append("   All hex digits are upper case.")
        L.append("")
        L.append("2. TICK")
        L.append("   The tick field is the controller's own free-running counter. It is not wall-clock time:")
        L.append("   it starts at zero at power-up and is never adjusted by the host. Hosts that need a")
        L.append("   timestamp must record the time of receipt.")
        L.append("")
        L.append("3. CHECKSUM")
        L.append("   The %s of every byte between '$' and '*' (both excluded), written as two" % cs_words)
        L.append("   upper-case hex digits after the '*'.")
        L.append("   Example:  %s" % example)
        L.append("             bytes covered: %s" % body)
        L.append("")
        L.append("4. STATUS MESSAGE (type %02X)" % st)
        L.append("   Sent periodically and on every state change. Four data words:")
        for k, w in enumerate(layout):
            L.append("     w%d  %-15s %s" % (k, w, gloss[w]))
        L.append("   Temperature words: (word - %d) / %d degrees C relative to the zone setpoint;" % (self.temp_offset, self.temp_scale))
        L.append("   %d means 'on setpoint'." % self.temp_offset)
        L.append("   Pressure word: gauge pressure, scaled; see the compressor data sheet for the unit fitted.")
        L.append("   STATE_FLAGS: bit %d set while the compressor contactor is closed (running). Other bits" % self.flag_bits["RUN"])
        L.append("   are reserved for the vendor service tool.")
        L.append("")
        L.append("5. EVENT MESSAGES")
        L.append("   One data word (sub-code). Sent when the condition changes.")
        ev_gloss = {"DEFROST": "0001 = defrost start, 0000 = defrost end", "TRIP": "0001 = high-pressure trip",
                    "LOCKOUT": "0001 = lockout entered, 0000 = lockout cleared", "DOOR": "0001 = door open, 0000 = door closed"}
        for c, lab in self.legacy_types.items():
            L.append("     %02X  %-8s %s" % (c, lab, ev_gloss[lab]))
        L.append("   Other message types are reserved for factory use and may be ignored.")
        L.append("")
        L.append("6. NOTES")
        L.append("   Type codes and the word layout are firmware-specific. Check the release note of the")
        L.append("   firmware fitted before relying on this table.")
        return "\n".join(L) + "\n"


_PARTIAL_SRC = '''"""RH-7 wire format decoder, reverse-engineered from bench captures of unit %(unit0)s. Partial.

The vendor never supplied a frame map. Field positions below were matched by hand against the
front-panel display during the bench runs; anything not identified is passed through in
"unknown" so it still lands in the gateway log.

    $<unit>,<seq>,<tick>,<type>,<w0> <w1> ...*<cs>
"""

CHECKSUM = "%(checksum)s"          # "xor" or "sum", see checksum()
STATUS_TYPE = 0x%(status)02X
W_AIR_TEMP = %(w_air)d              # word index inside a STATUS frame
W_FLAGS = %(w_flags)d
RUN_BIT = %(run_bit)d                 # bit of the flags word: compressor running
TEMP_SCALE = %(scale)d
TEMP_OFFSET = %(offset)d           # word = round(delta * TEMP_SCALE) + TEMP_OFFSET, delta from the zone setpoint

KNOWN_TYPES = {STATUS_TYPE: "STATUS"}

# unit id -> rack zone
UNITS = {
%(units)s
}


def checksum(payload):
    data = payload.encode()
    if CHECKSUM == "xor":
        c = 0
        for b in data:
            c ^= b
        return c
    return sum(data) & 0xFF


def parse_frame(line):
    line = line.strip()
    if not line.startswith("$") or "*" not in line:
        raise ValueError("not a frame: %%r" %% line)
    body, _, cs = line[1:].rpartition("*")
    if int(cs, 16) != checksum(body):
        raise ValueError("checksum mismatch: %%r" %% line)
    fields = body.split(",")
    if len(fields) != 5:
        raise ValueError("bad field count: %%r" %% line)
    unit, seq, tick, typ, words = fields
    return {"unit": unit, "seq": int(seq, 16), "tick": tick, "type": int(typ, 16),
            "words": [int(w, 16) for w in words.split()]}


def decode_line(line, setpoints=None):
    """Decode one frame. setpoints: {zone: degC}, used for AIR_TEMP."""
    setpoints = setpoints or {}
    fr = parse_frame(line)
    zone = UNITS.get(fr["unit"])
    words = fr["words"]
    # fr["tick"]: controller-local counter, unused
    out = {"ctrl_id": fr["unit"], "seq": fr["seq"], "type": fr["type"], "zone": zone, "clauses": [], "unknown": []}
    if fr["type"] not in KNOWN_TYPES:
        out["unknown"].append("type=0x%%02x words=%%s" %% (fr["type"], " ".join("%%04x" %% w for w in words)))
        out["clauses"].append({"zone": zone, "head": "unknown_type", "value": None, "raw": list(words)})
        return out
    if len(words) <= max(W_AIR_TEMP, W_FLAGS):
        raise ValueError("short STATUS frame: %%r" %% line)
    for i, w in enumerate(words):
        if i == W_AIR_TEMP:
            # units report the offset from the zone setpoint, TEMP_OFFSET = on setpoint
            value = round(setpoints.get(zone, 0.0) + (w - TEMP_OFFSET) / float(TEMP_SCALE), 1)
            out["clauses"].append({"zone": zone, "head": "AIR_TEMP", "value": value, "raw": w})
        elif i == W_FLAGS:
            head = "RUN" if w & (1 << RUN_BIT) else "IDLE"
            out["clauses"].append({"zone": zone, "head": head, "value": None, "raw": w})
        else:
            out["unknown"].append("word[%%d]=0x%%04x" %% (i, w))
    return out
'''
