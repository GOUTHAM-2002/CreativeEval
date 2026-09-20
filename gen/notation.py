"""KW-7 telegram notation: a per-seed constructed line format for the K7 controllers.

Tokenization. A line is `HDR <ctrl> <seq> <t_ctrl> | <clause> ; <clause> ...`; tokens are
separated by single spaces, clauses by " ; ", header and body by " | ". Every syllable is
CV (one consonant + one vowel), so a token splits into 2-char syllables, and three
disjoint consonant sets decide what a token is from its first letter:
  R (roots)   a root is exactly two R-syllables ("kato"); every root is in the glossary
  D (digits)  a number is one or more D-syllables, base b, most significant digit first,
              no separators, no leading zero ("bezabe")
  X (aspects) the aspect-suffix syllables
Suffixes hang off a clause head with "-": "<root>-<zone>-<aspect>", where the zone suffix
is the first syllable of that zone's root and the aspect suffix is one X-syllable
(ASPECT_EVENT or ASPECT_STATE). The header ctrl token is "<COMPRESSOR root><index>" (two
R-syllables followed by D-syllables). No token needs lookahead to classify.
"""

import random

CONSONANTS = "b d f g h j k l m n p r s t v w z".split()
VOWELS = list("aeiou")
BASES = (7, 8, 11, 12)

STATES = ("RUN", "IDLE", "DEFROST", "RECOVERY", "LOCKOUT")
SENSORS = ("AIR_TEMP", "COIL_TEMP", "DISCH_PRESSURE")
TEMP_SENSORS = ("AIR_TEMP", "COIL_TEMP")
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
_LABELS_TAIL = (
    "RUN", "IDLE", "DEFROST", "RECOVERY", "LOCKOUT", "TRIP", "AIR_TEMP", "COIL_TEMP",
    "DISCH_PRESSURE", "DOOR", "HEATER", "SETPOINT", "COMPRESSOR", "FIRMWARE", "QUEUE", "READ",
    "ENTER", "EXIT", "SET", "FAULT", "CLEAR", "BOOT", "OPEN", "CLOSED", "ON", "OFF", "HIGH",
    "LOW", "STALE", "ABS", "OVERFLOW",
)
_KNOWN_TAIL = ("RUN", "IDLE", "AIR_TEMP", "SETPOINT", "COMPRESSOR", "READ")
LEGACY_LABELS = ("DEFROST", "TRIP", "LOCKOUT", "DOOR")

_CARD_GLOSS = {
    "HDR": "frame opener", "RUN": "compressor running", "IDLE": "compressor idle",
    "DEFROST": "defrost cycle", "TRIP": "safety trip", "LOCKOUT": "lockout",
    "DOOR": "door contact", "AIR_TEMP": "air temperature", "SETPOINT": "zone setpoint",
    "COMPRESSOR": "compressor unit", "READ": "report verb",
}


def _r1(x):
    return round(x, 1)


class Notation:
    EVENT_RENDER = EVENT_RENDER

    def __init__(self, rng, zones=None, controllers=None):
        self.zones = list(zones) if zones is not None else ["A", "B", "C", "D", "E", "F"]
        if controllers is None:
            controllers = {z: "K7-%02d" % (i + 1) for i, z in enumerate(self.zones)}
        self.controllers = {z: controllers[z] for z in self.zones}
        self._ctrl_index = {self.controllers[z]: i + 1 for i, z in enumerate(self.zones)}
        self._ctrl_of_index = {i: c for c, i in self._ctrl_index.items()}
        self._zone_of_ctrl = {c: z for z, c in self.controllers.items()}
        self.labels = ["HDR"] + ["ZONE_" + z for z in self.zones] + list(_LABELS_TAIL)
        self.known_labels = ["HDR"] + ["ZONE_" + z for z in self.zones] + list(_KNOWN_TAIL)
        self._event_of_pair = {v: k for k, v in EVENT_RENDER.items()}
        self._build(rng)

    # ---- vocabulary -------------------------------------------------------------------
    def _build(self, rng):
        cons = CONSONANTS[:]
        rng.shuffle(cons)
        n_r = rng.randint(7, 9)
        self.r_cons = sorted(cons[:n_r])
        self.d_cons = sorted(cons[n_r:n_r + 4])
        self.x_cons = sorted(cons[n_r + 4:n_r + 6])
        self.vowels = sorted(rng.sample(VOWELS, rng.randint(3, 4)))
        self.base = rng.choice(BASES)

        dsyl = [c + v for c in self.d_cons for v in self.vowels]
        rng.shuffle(dsyl)
        self.digits = dsyl[:self.base]
        self._digit_val = {g: i for i, g in enumerate(self.digits)}

        rsyl = [c + v for c in self.r_cons for v in self.vowels]
        cands = [a + b for a in rsyl for b in rsyl if a != b]
        rng.shuffle(cands)
        it = iter(cands)
        self.root = {}
        used_first = set()
        for lab in self.labels:
            for r in it:
                if not (lab.startswith("ZONE_") and r[:2] in used_first):
                    break
            self.root[lab] = r
            if lab.startswith("ZONE_"):
                used_first.add(r[:2])
        self.legacy = {next(it): lab for lab in LEGACY_LABELS}
        self.label = {r: lab for lab, r in self.root.items()}
        self.glossary = dict(self.label)
        for i, g in enumerate(self.digits):
            self.glossary[g] = "DIGIT_%d" % i

        xsyl = [c + v for c in self.x_cons for v in self.vowels]
        rng.shuffle(xsyl)
        self.aspect = {"ASPECT_EVENT": xsyl[0], "ASPECT_STATE": xsyl[1]}
        self._aspect_of_syl = {s: a for a, s in self.aspect.items()}
        self.zone_suffix = {z: self.root["ZONE_" + z][:2] for z in self.zones}
        self._zone_of_suffix = {s: z for z, s in self.zone_suffix.items()}
        self.order = rng.choice(["VSO", "SOV"])

    # ---- public helpers ---------------------------------------------------------------
    def known_roots(self):
        return [self.root[lab] for lab in self.known_labels] + list(self.digits)

    def label_of(self, root):
        if root not in self.glossary:
            raise ValueError("unknown root %r" % root)
        return self.glossary[root]

    def truth(self):
        affixes = {"-" + s: "ZONE" for s in self.zone_suffix.values()}
        for a, s in self.aspect.items():
            affixes["-" + s] = a
        return {
            "base": self.base,
            "digit_glyphs": list(self.digits),
            "clause_order": self.order,
            "glossary": dict(self.glossary),
            "known_roots": self.known_roots(),
            "affixes": affixes,
            "v34_change": "absolute_temp",
            "legacy_roots": dict(self.legacy),
            "event_render": {e: list(p) for e, p in EVENT_RENDER.items()},
        }

    # ---- encode -----------------------------------------------------------------------
    def _num(self, n):
        n = int(n)
        if n < 0:
            raise ValueError("cannot encode negative number %d" % n)
        if n == 0:
            return self.digits[0]
        out = []
        while n:
            out.append(self.digits[n % self.base])
            n //= self.base
        return "".join(reversed(out))

    def _head(self, label, zone, aspect):
        if zone not in self.zone_suffix:
            raise ValueError("unknown zone %r" % zone)
        return self.root[label] + "-" + self.zone_suffix[zone] + "-" + self.aspect[aspect]

    def _clause(self, c, fw, setpoint):
        kind = c.get("kind")
        zone = c.get("zone")
        abs_tok = None
        if kind == "READ":
            sensor = c["sensor"]
            if sensor not in SENSORS:
                raise ValueError("unknown sensor %r" % sensor)
            v = c["value"]
            if sensor == "DISCH_PRESSURE":
                n = round(v * 10)
            elif fw == "3.4":
                n = round(v * 10) + 500
                abs_tok = self.root["ABS"]
            else:
                if setpoint is None:
                    raise ValueError("fw 3.2 temperature needs a setpoint")
                n = round((v - setpoint) * 10) + 500
            verb, head, val = self.root["READ"], self._head(sensor, zone, "ASPECT_STATE"), self._num(n)
        elif kind == "STATE":
            state = c["state"]
            if state not in STATES:
                raise ValueError("unknown state %r" % state)
            verb, head, val = self.root["READ"], self._head(state, zone, "ASPECT_STATE"), None
        elif kind == "EVENT":
            ev = c["event"]
            if ev not in EVENT_RENDER:
                raise ValueError("unknown event %r" % ev)
            hl, vl = EVENT_RENDER[ev]
            v = c.get("value")
            val = None
            if ev == "BOOT":
                val = self._num(round(v) if v is not None else (34 if fw == "3.4" else 32))
            elif ev == "SETPOINT_SET":
                val = self._num(round(v * 10) + 500)
            elif ev == "QUEUE_OVERFLOW":
                val = self._num(round(v))
            verb, head = self.root[vl], self._head(hl, zone, "ASPECT_EVENT")
        else:
            raise ValueError("unknown clause kind %r" % kind)
        if self.order == "VSO":
            toks = [verb] + ([abs_tok] if abs_tok else []) + [head] + ([val] if val else [])
        else:
            toks = [head] + ([abs_tok] if abs_tok else []) + ([val] if val else []) + [verb]
        return " ".join(toks)

    def encode(self, frame, setpoint=None):
        if setpoint is None:
            setpoint = frame.get("setpoint")
        ctrl = frame.get("ctrl_id")
        if ctrl not in self._ctrl_index:
            raise ValueError("unknown controller %r" % ctrl)
        if frame.get("zone") != self._zone_of_ctrl[ctrl]:
            raise ValueError("frame zone %r does not match controller %r" % (frame.get("zone"), ctrl))
        fw = frame.get("fw")
        if fw not in ("3.2", "3.4"):
            raise ValueError("bad fw %r" % fw)
        hdr = " ".join([
            self.root["HDR"],
            self.root["COMPRESSOR"] + self._num(self._ctrl_index[ctrl]),
            self._num(frame["seq"]),
            self._num(frame["t_ctrl_min"]),
        ])
        clauses = [self._clause(c, fw, setpoint) for c in frame.get("clauses", [])]
        return hdr + " |" + (" " + " ; ".join(clauses) if clauses else "")

    # ---- decode -----------------------------------------------------------------------
    def _syllables(self, tok):
        if len(tok) < 2 or len(tok) % 2:
            raise ValueError("bad token %r" % tok)
        return [tok[i:i + 2] for i in range(0, len(tok), 2)]

    def _parse_num(self, tok):
        syl = self._syllables(tok)
        if any(s not in self._digit_val for s in syl):
            raise ValueError("bad number %r" % tok)
        if len(syl) > 1 and self._digit_val[syl[0]] == 0:
            raise ValueError("leading zero in %r" % tok)
        n = 0
        for s in syl:
            n = n * self.base + self._digit_val[s]
        return n

    def _classify(self, tok):
        parts = tok.split("-")
        base = parts[0]
        if base and base[0] in self.d_cons:
            if len(parts) > 1:
                raise ValueError("number with suffix %r" % tok)
            return ("num", self._parse_num(base), None)
        if base not in self.label:
            raise ValueError("unknown root %r" % base)
        return ("root", self.label[base], parts[1:])

    def _parse_clause(self, text):
        toks = text.split(" ")
        if len(toks) < 2 or any(not t for t in toks):
            raise ValueError("bad clause %r" % text)
        typed = [self._classify(t) for t in toks]
        if self.order == "VSO":
            verb, rest = typed[0], typed[1:]
        else:
            verb, rest = typed[-1], typed[:-1]
        if verb[0] != "root" or verb[2]:
            raise ValueError("bad verb in %r" % text)
        vl = verb[1]
        tags, head, num, has_abs = [], None, None, False
        for t in rest:
            if t[0] == "num":
                if num is not None:
                    raise ValueError("two numbers in %r" % text)
                num = t[1]
                tags.append("num")
            elif t[2]:
                if head is not None:
                    raise ValueError("two heads in %r" % text)
                head = t
                tags.append("head")
            elif t[1] == "ABS":
                if has_abs:
                    raise ValueError("two ABS in %r" % text)
                has_abs = True
                tags.append("abs")
            else:
                raise ValueError("unexpected token in %r" % text)
        if head is None:
            raise ValueError("no head in %r" % text)
        a, n = (["abs"] if has_abs else []), (["num"] if num is not None else [])
        expect = a + ["head"] + n if self.order == "VSO" else ["head"] + a + n
        if tags != expect:
            raise ValueError("bad token order in %r" % text)
        if len(head[2]) != 2 or head[2][0] not in self._zone_of_suffix or head[2][1] not in self._aspect_of_syl:
            raise ValueError("bad suffixes in %r" % text)
        zone, aspect, hl = self._zone_of_suffix[head[2][0]], self._aspect_of_syl[head[2][1]], head[1]
        if aspect == "ASPECT_STATE":
            if vl != "READ":
                raise ValueError("state clause needs READ in %r" % text)
            if hl in SENSORS:
                if num is None or (has_abs and hl not in TEMP_SENSORS):
                    raise ValueError("bad READ clause %r" % text)
                return {"kind": "READ", "sensor": hl, "zone": zone, "value": None, "_raw": num, "_abs": has_abs}
            if hl in STATES and num is None and not has_abs:
                return {"kind": "STATE", "state": hl, "zone": zone}
            raise ValueError("bad state clause %r" % text)
        ev = self._event_of_pair.get((hl, vl))
        if ev is None or has_abs or (num is not None) != (ev in VALUED_EVENTS):
            raise ValueError("bad event clause %r" % text)
        value = None
        if ev == "SETPOINT_SET":
            value = _r1((num - 500) / 10)
        elif ev in VALUED_EVENTS:
            value = float(num)
        return {"kind": "EVENT", "event": ev, "zone": zone, "value": value}

    def decode(self, line, setpoint=None):
        if not isinstance(line, str) or not line.isascii() or line != line.strip() or "\n" in line:
            raise ValueError("bad line")
        if line.endswith(" |"):
            hdr, body = line[:-2], ""
        elif " | " in line:
            hdr, body = line.split(" | ", 1)
        else:
            raise ValueError("no header separator")
        h = hdr.split(" ")
        if len(h) != 4 or h[0] != self.root["HDR"]:
            raise ValueError("bad header %r" % hdr)
        comp = self.root["COMPRESSOR"]
        if not h[1].startswith(comp) or len(h[1]) <= len(comp):
            raise ValueError("bad controller token %r" % h[1])
        idx = self._parse_num(h[1][len(comp):])
        if idx not in self._ctrl_of_index:
            raise ValueError("unknown controller index %d" % idx)
        ctrl = self._ctrl_of_index[idx]
        clauses = [self._parse_clause(t) for t in (body.split(" ; ") if body else [])]
        any_abs = False
        for c in clauses:
            if c["kind"] != "READ":
                continue
            raw, is_abs = c.pop("_raw"), c.pop("_abs")
            any_abs = any_abs or is_abs
            if c["sensor"] == "DISCH_PRESSURE":
                c["value"] = _r1(raw / 10)
            elif is_abs:
                c["value"] = _r1((raw - 500) / 10)
            elif setpoint is None:
                c["raw"] = raw
            else:
                c["value"] = _r1((raw - 500) / 10 + setpoint)
        return {
            "ctrl_id": ctrl,
            "zone": self._zone_of_ctrl[ctrl],
            "seq": self._parse_num(h[2]),
            "t_ctrl_min": self._parse_num(h[3]),
            "fw": "3.4" if any_abs else "3.2",
            "clauses": clauses,
        }

    # ---- shipped artifacts ------------------------------------------------------------
    def render_partial_decoder(self):
        def table(pairs, quote_key=True):
            fmt = '    "%s": %r,' if quote_key else "    %s: %r,"
            return "\n".join(fmt % (k, v) for k, v in pairs)

        digits = [(g, i) for i, g in enumerate(self.digits)]
        known = [(self.root[lab], lab) for lab in self.known_labels]
        known += [(g, "DIGIT_%d" % i) for g, i in digits]
        zmk = [(self.zone_suffix[z], z) for z in self.zones]
        units = [(i, self._ctrl_of_index[i]) for i in sorted(self._ctrl_of_index)]
        return _PARTIAL_SRC % {
            "base": self.base,
            "digits": table(digits),
            "known": table(known),
            "zones": table(zmk),
            "units": table(units, quote_key=False),
            "ctrl_prefix": self.root["COMPRESSOR"],
        }

    def render_quickref(self):
        L = []
        hdr, comp = self.root["HDR"], self.root["COMPRESSOR"]
        ev, st = self.aspect["ASPECT_EVENT"], self.aspect["ASPECT_STATE"]
        L.append("KW-7 TELEGRAM QUICK REFERENCE (firmware 2.x)")
        L.append("=" * 44)
        L.append("Sheet 1/1. Keep with the controller panel. Telegrams are plain ASCII, one per line.")
        L.append("")
        L.append("FRAME")
        L.append("  <hdr> <unit> <seq> <tick> | <clause> ; <clause> ; ...")
        L.append('  hdr    "%s"                opener, always the first word' % hdr)
        L.append('  unit   "%s"+<number>       compressor unit index (1 = K7-01, 2 = K7-02, ...)' % comp)
        L.append("  seq    <number>              telegram sequence number, restarts with the controller")
        L.append("  tick   <number>              controller clock, minutes since power-up")
        L.append('  Clauses are separated by " ; " (space, semicolon, space).')
        L.append("")
        if self.order == "VSO":
            L.append("CLAUSE (verb first)")
            L.append("  <verb> <head>-<zone>-<type> [<number>]")
        else:
            L.append("CLAUSE (verb last)")
            L.append("  <head>-<zone>-<type> [<number>] <verb>")
        L.append("  The head is the word the clause is about (a sensor, a state, a unit part).")
        L.append('  It always carries two markers joined with "-": first the zone marker, then')
        L.append('  the report-type marker ("-%s" or "-%s"). Verbs and numbers carry no markers.' % (ev, st))
        L.append("")
        L.append("ZONE MARKERS (first syllable of the zone word)")
        for z in self.zones:
            L.append("  -%s   zone %s   (%s)" % (self.zone_suffix[z], z, self.root["ZONE_" + z]))
        L.append("")
        L.append("NUMBERS")
        L.append("  Base %d, most significant digit first, digits run together as one word," % self.base)
        L.append("  no leading zero.")
        L.append("  " + "   ".join("%d=%s" % (i, g) for i, g in enumerate(self.digits)))
        L.append('  e.g. 100 = "%s", 4095 = "%s"' % (self._num(100), self._num(4095)))
        L.append("")
        L.append("WORD LIST")
        words = [(self.root[lab], lab) for lab in self.known_labels]
        words += [(r, lab) for r, lab in self.legacy.items()]
        for r, lab in words:
            gloss = _CARD_GLOSS.get(lab) or ("zone %s" % lab[-1])
            L.append("  %s   %s" % (r, gloss))
        L.append("")
        L.append("Unlisted words: check the firmware release note for your unit.")
        return "\n".join(L) + "\n"


_PARTIAL_SRC = '''"""KW-7 telegram decoder, reverse-engineered from unit K7-01 bench captures. Partial.

Vendor docs were never provided. Token meanings below were matched by hand against
the front-panel display during bench runs; anything not in KNOWN_TOKENS is passed
through as unk=<token> so it still shows up in the gateway log.
"""

BASE = %(base)d

# digit glyph -> value; positional, most significant first, digits run together
DIGITS = {
%(digits)s
}

KNOWN_TOKENS = {
%(known)s
}

# first syllable of the zone word doubles as the zone marker on clause heads
ZONE_MARKERS = {
%(zones)s
}

# rack labels by unit index
UNITS = {
%(units)s
}

CTRL_PREFIX = "%(ctrl_prefix)s"  # unit word, immediately followed by the unit index
HDR_SEP = " | "
CLAUSE_SEP = " ; "


def is_number(tok):
    if not tok or len(tok) %% 2:
        return False
    return all(tok[i:i + 2] in DIGITS for i in range(0, len(tok), 2))


def parse_number(tok):
    if not is_number(tok):
        raise ValueError("not a number: %%r" %% tok)
    n = 0
    for i in range(0, len(tok), 2):
        n = n * BASE + DIGITS[tok[i:i + 2]]
    return n


def split_affixes(tok):
    """Return (root, zone). Markers hang off the head word with '-'."""
    parts = tok.split("-")
    root = parts[0]
    zone = ZONE_MARKERS.get(parts[1]) if len(parts) > 1 else None
    # parts[2:] -- trailing marker, purpose unknown; dropped
    return root, zone


def decode_line(line, setpoints=None):
    """Decode one telegram. setpoints: {zone: degC}, used for AIR_TEMP."""
    setpoints = setpoints or {}
    line = line.strip()
    if line.endswith(" |"):
        hdr, body = line[:-2], ""
    elif HDR_SEP in line:
        hdr, body = line.split(HDR_SEP, 1)
    else:
        raise ValueError("no header separator: %%r" %% line)
    h = hdr.split()
    if len(h) != 4 or KNOWN_TOKENS.get(h[0]) != "HDR":
        raise ValueError("bad header: %%r" %% hdr)
    if not h[1].startswith(CTRL_PREFIX):
        raise ValueError("bad unit token: %%r" %% h[1])
    unit = parse_number(h[1][len(CTRL_PREFIX):])
    out = {
        "ctrl_id": UNITS.get(unit, "K7-%%02d" %% unit),
        "seq": parse_number(h[2]),
        # h[3]: controller-local counter, unused
        "clauses": [],
        "unknown": [],
    }
    for text in (body.split(CLAUSE_SEP) if body else []):
        c = {"zone": None, "head": None, "words": [], "raw": None, "value": None}
        for tok in text.split():
            if is_number(tok):
                c["raw"] = parse_number(tok)
                continue
            root, zone = split_affixes(tok)
            name = KNOWN_TOKENS.get(root)
            if name is None:
                name = "unk=" + tok
                out["unknown"].append(name)
            if zone is not None:
                c["zone"], c["head"] = zone, name
            else:
                c["words"].append(name)
        if c["raw"] is not None:
            if c["head"] == "AIR_TEMP":
                # sensors report the offset from the zone setpoint, 500 = on setpoint
                c["value"] = round(setpoints.get(c["zone"], 0.0) + (c["raw"] - 500) / 10.0, 1)
            elif c["head"] == "SETPOINT":
                c["value"] = round((c["raw"] - 500) / 10.0, 1)
        out["clauses"].append(c)
    return out
'''
