# v2 cold-case layer: machine channels with outages/retention + FACT SHEETS for LLM-written human documents
# (with template fallbacks). Produces build/fact_sheets/*.json; rendering is gen/docs_llm.render_all.
from __future__ import annotations
import csv
import json
import random
import re
from pathlib import Path

from gen import seed as seedmod
from gen import docs_gen as v1

ROOT = Path(__file__).resolve().parent.parent
iso, hhmm, dstr, day_of = v1.iso, v1.hhmm, v1.dstr, v1.day_of
CANARIES = ["truth", "simulat", "generator", "fictional", "eval", "answer key", "hidden parameter", "seed"]


def local(world, t_min, offset_min=0):
    """Site-local wall clock string 'Mon 23 May, 9:47 pm' (site tz = UTC-5 in this world)."""
    import datetime as dt
    start = dt.datetime.strptime(world["sim"]["start_iso"], "%Y-%m-%dT%H:%M:%SZ")
    d = start + dt.timedelta(minutes=int(round(t_min + offset_min)))
    return d.strftime("%a %d %b, %-I:%M %p").replace("AM", "am").replace("PM", "pm")


class Ctx2(v1.Ctx):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.sheets = {}
        self.plan = self.world["plan"]
        self.flashed = [e["zone"] for e in self.world["ledger"]["firmware_flash"]]
        self.other_flashed = self.plan["other_flashed"]
        self.drift = self.world["ledger"]["sensor_drift"]
        self.po = self.plan["power_outage"]
        self.tz = "Atlantic/Reykjavik (UTC all year; site clocks match the logs)"
        self.actors_by_handle = {a["handle"]: a for a in self.world["names"]["actors"]}

    def sheet(self, doc_id, path, kind, author_role, persona, must_include, verbatim, fallback, *, length=(200, 400),
              may_mention=(), must_not=(), style="", audience="internal investigation", extra=None):
        a = self.actors[author_role] if author_role in self.actors else {"name": author_role, "handle": author_role, "role": author_role}
        sh = {"doc_id": doc_id, "path": path, "kind": kind,
              "author": {"name": a["name"], "handle": a["handle"], "role": a.get("role", author_role).replace("_", " "), "persona": persona, "tz": self.tz},
              "audience": audience, "length_words": list(length),
              "must_include": [{"fact_id": f"{doc_id}:{i}", "text": t} for i, t in enumerate(must_include)],
              "verbatim": [{"claim_id": cid, "text": txt} for cid, txt in verbatim],
              "may_mention": list(may_mention), "must_not_mention": list(must_not), "forbidden_strings": CANARIES,
              "allowed_entities": self.allowed_entities(), "style_notes": style, "fallback": fallback}
        if extra:
            sh.update(extra)
        if kind in ("statement", "report", "email", "memo") and isinstance(fallback, str):
            lines = fallback.split("\n")
            hdr = []
            for ln in lines:
                if ln.strip() == "":
                    break
                hdr.append(ln)
            if hdr and (hdr[0].startswith("#") or hdr[0].startswith("From:")):
                sh["header"] = "\n".join(hdr)
        self.sheets[doc_id] = sh
        return sh

    def allowed_entities(self):
        w = self.world
        return ([a["name"] for a in w["names"]["actors"]] + [self.info["people"]["former"][0]] + [a["handle"] for a in w["names"]["actors"]]
                + [f"room {z}" for z in self.zones] + list(w["zones"]["controller"].values()) + [w["names"]["company"], w["names"]["site_code"], "HH-1", "HH-2", "FL-1", "FL-2"])


# ---------------------------------------------------------------- machine channels (templated; these are records, not prose)
def badge_csv(c):
    w, rng = c.world, c.rng
    out = v1.badge_csv.__wrapped__(c) if hasattr(v1.badge_csv, "__wrapped__") else None
    holders = {a["handle"]: (f"B{1000 + i * 7 + rng.randrange(0, 5):04d}", a["name"]) for i, a in enumerate(w["names"]["actors"])}
    rows = []
    for b in w["ledger"]["badge"]:
        bid, nm = holders[b["actor"]]
        rows.append((b["t"], bid, nm, "MAIN-ENTRANCE", "IN" if b["kind"] == "shift_start" else "OUT"))
    for d in w["ledger"]["door_intervals"]:
        if d["cause"] in ("pallet_move", "probe_check", "walkthrough", "receiving"):
            bid, nm = holders[d["actor"]]
            rows.append((d["t0"], bid, nm, f"ROOM-{d['zone']}", "UNLOCK"))
    tech = holders[c.handle("vendor_tech")]
    for e in w["ledger"]["firmware_flash"]:
        rows.append((e["t"] - rng.randrange(8, 25), tech[0], tech[1], f"ROOM-{e['zone']}", "UNLOCK"))
    ft = w["ledger"]["firmware_flash"][0]["t"]
    rows.append((ft - rng.randrange(40, 70), tech[0], tech[1], "MAIN-ENTRANCE", "IN (VISITOR)"))
    rows.append((ft + rng.randrange(90, 150), tech[0], tech[1], "MAIN-ENTRANCE", "OUT (VISITOR)"))
    rt = c.plan["recal_t"]
    rows.append((rt - rng.randrange(30, 60), tech[0], tech[1], "MAIN-ENTRANCE", "IN (VISITOR)"))
    rows.append((rt - rng.randrange(5, 15), tech[0], tech[1], f"ROOM-{c.drift['zone']}", "UNLOCK"))
    rows.append((rt + rng.randrange(40, 80), tech[0], tech[1], "MAIN-ENTRANCE", "OUT (VISITOR)"))
    # the night lead closing the propped door: that reader was offline (see badge_reader_outage), so no row
    bro = c.plan["badge_reader_outage"]
    rows = [r for r in rows if not (r[3] == bro["reader"] and bro["t0"] <= r[0] <= bro["t1"])]
    rows.sort()
    with open(c.people / "badge_access.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["timestamp", "badge_id", "holder", "reader", "event"])
        for t, bid, nm, rd, ev in rows:
            wr.writerow([iso(w, t, c.offs["badge"]), bid, nm, rd, ev])
    c.badge_holders = holders
    return len(rows)


def forklift_csv(c):
    w, rng = c.world, c.rng
    fo = c.plan["fl2_outage"]
    rows = []
    for mv in w["ledger"]["moves"]:
        t0 = mv["t_sec"] / 60.0
        if mv["forklift"] == fo["forklift"] and fo["t0"] <= t0 <= fo["t1"]:
            continue                                  # telematics unit offline (battery), see ticket
        rows.append((t0, mv["forklift"], mv["actor"], "PALLET_PICK", mv["from"], mv["pallet"], mv["lot"]))
        rows.append((t0 + rng.uniform(1.0, 4.0), mv["forklift"], mv["actor"], "PALLET_DROP", mv["to"], mv["pallet"], mv["lot"]))
    for d in w["ledger"]["door_intervals"]:
        if d["cause"] == "receiving":
            fl = "FL-1" if day_of(d["t0"]) % 2 == 0 else "FL-2"
            if fl == fo["forklift"] and fo["t0"] <= d["t0"] <= fo["t1"]:
                continue
            rows.append((d["t0"] + 0.5, fl, "", "DOCK_UNLOAD_START", d["zone"], "", d.get("truck", "")))
            rows.append((d["t1"] - 0.5, fl, "", "DOCK_UNLOAD_END", d["zone"], "", d.get("truck", "")))
    rows.sort()
    with open(c.people / "forklift_telematics.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["timestamp", "forklift_id", "operator", "event", "zone", "pallet_id", "ref"])
        for t, fl, op, ev, z, pl, ref in rows:
            wr.writerow([iso(w, t, c.offs["forklift"]), fl, op, ev, z, pl, ref])
    return len(rows)


def cctv_csv(c):
    w, rng, sim = c.world, c.rng, c.sim
    total = w["sim"]["days"] * 1440
    keep_from = total - c.plan["cctv_retention_days"] * 1440
    rows = []
    for z in c.zones:
        cam = f"CORR-{z}"
        for t in range(keep_from, total, 5):
            score = 0
            if any(sim["door_open"][z][k] for k in range(t, min(t + 5, total))):
                score = rng.randrange(35, 90)
            elif rng.random() < 0.02:
                score = rng.randrange(5, 20)
            if score:
                rows.append((t + rng.randrange(0, 5), cam, score))
    rows.sort()
    with open(c.people / "cctv_motion.csv", "w", newline="") as f:
        f.write(f"# export {iso(w, total)} from NVR-1; motion index per camera; retention 7 days (older footage overwritten)\n")
        wr = csv.writer(f)
        wr.writerow(["timestamp", "camera", "motion_score"])
        for t, cam, sc in rows:
            wr.writerow([iso(w, t, c.offs["cctv"]), cam, sc])
    return len(rows)


def receipts(c):
    v1.receipts(c)
    w, rng = c.world, c.rng
    rt = c.plan["recal_t"]
    c.write("people/receipts/vendor_invoice_recalibration.txt", f"""SERVICE INVOICE  {w['names']['vendor_model'].split('-')[0]} Controls Ltd
Customer: {w['names']['company']}  Site {w['names']['site_code']}
Visit date: {dstr(w, rt)}   Technician: {c.name('vendor_tech')}
  Air sensor recalibration, room {c.drift['zone']} ({w['zones']['controller'][c.drift['zone']]}) ........  190.00
  Travel ............................................................................  120.00
  Total ............................................................................  310.00
""")


# ---------------------------------------------------------------- fact sheets for human documents
def sheets_statements(c):
    w, rng = c.world, c.rng
    inc, ctrl = c.inc, w["zones"]["controller"]
    ip = c.inc_prop
    inc_night = dstr(w, ip["t0"] - 300)
    walk = [x for x in w["ledger"]["walkthroughs"] if abs(x["t"] - ip["t0"]) < 400 and x["t"] < ip["t0"]]
    walk_t = walk[-1]["t"] if walk else ip["t0"] - 90
    taken = dstr(w, c.plan["postmortem_day"] * 1440)
    A = c.actors
    # night lead: false claim (door) + omits closing it
    fb = f"""# Statement — {c.name('night_lead')} (night shift lead)
Taken {taken}

On the night of {inc_night} I came on at {local(w, ip['t0'] - 180)} with the agency worker. I did my walk-through at {local(w, walk_t)} and all the rooms were closed and nobody went near room {inc} after that. The compressor on {ctrl[inc]} had been clicking on and off at night for a couple of weeks and I said so in handover.
I first heard of a problem when the lab wrote. I checked room {inc} on my way out in the morning and the door was shut.
"""
    c.sheet("doc:night_lead", f"people/statements/night_lead_{A['night_lead']['handle']}.md", "statement", "night_lead",
            "defensive, terse, blames the equipment, careful not to admit anything about doors",
            [f"came on shift at about {local(w, ip['t0'] - 180)} on {inc_night} together with the agency worker {c.name('temp_worker')}",
             f"did a walk-through at about {local(w, walk_t)}", f"has complained in handovers that the {ctrl[inc]} compressor sounded rough at night",
             "first learned of a problem from the customer lab e-mail", f"checked room {inc} on the way out in the morning and found the door shut"],
            [("fc01", f"all the rooms were closed and nobody went near room {inc} after that")], fb,
            must_not=["wedge", "propped", "closing the door", "04:"], style="first person, no headings, local times with am/pm")
    # temp worker: denial (NOT refutable in v2), receipt story
    fb = f"""# Statement — {c.name('temp_worker')} (agency, night shift)
Taken {taken}

I started on {dstr(w, 3 * 1440)}. At night I restock the pick faces from the rooms, mostly room {inc}. I open and close the doors as fast as I can because the rooms are cold.
I did not prop any door open. The wedge on my receipt was for the break-room door, which slams; the extension cord was for the radio. The photo in the chat was a joke.
"""
    c.sheet("doc:temp_worker", f"people/statements/temp_worker_{A['temp_worker']['handle']}.md", "statement", "temp_worker",
            "nervous, short sentences, worried about the agency contract",
            [f"started on {dstr(w, 3 * 1440)} through the agency", f"restocks pick faces at night, mostly from room {inc}",
             "bought a rubber door wedge and an extension cord and submitted the receipt", "posted a photo of the wedge in the ops chat as a joke",
             "denies propping any cold-room door"], [], fb, must_not=["04:", "lockout"], style="first person, plain words, no headings")
    # warehouse manager: false claim about the archive timing
    fb = f"""# Statement — {c.name('warehouse_manager')} (warehouse manager)
Taken {taken}

The vendor visit on {dstr(w, w['ledger']['firmware_flash'][0]['t'])} was routine. Afterwards rooms {c.other_flashed} and {inc} showed minus forty on the dashboard and I raised it with engineering the same day. Engineering said it was a sensor fault on the new boards and routed the alerts to the old channel.
I archived the old alert channel only after the incident, when we cleaned up the workspace. Probe checks are done on weekdays with the two handhelds. The badge reader on room {inc} was out for most of that week; facilities had a ticket.
"""
    c.sheet("doc:warehouse_manager", f"people/statements/warehouse_manager_{A['warehouse_manager']['handle']}.md", "statement", "warehouse_manager",
            "managerial, wants to look organised, shifts blame to engineering and the vendor",
            [f"vendor firmware visit on {dstr(w, w['ledger']['firmware_flash'][0]['t'])}", f"rooms {c.other_flashed} and {inc} read about -40 on the dashboard after the visit",
             "raised the -40 readings with engineering the same day", "does the weekday probe round with handheld HH-1 (rooms on the pick route only)",
             f"the badge reader on room {inc} was offline for most of the incident week (facilities ticket)", f"the utility ran a generator test on {dstr(w, c.po['t0'])} that cut power for about {c.po['t1'] - c.po['t0']} minutes"],
            [("fc02", "I archived the old alert channel only after the incident")], fb,
            must_not=["wedge"], style="first person, confident, local times")
    # ops engineer: false claim (vendor confirmed sensor fault)
    fb = f"""# Statement — {c.name('ops_engineer')} (platform engineer)
Taken {taken}

After the firmware visit the gateway logged {ctrl[c.other_flashed]} and {ctrl[inc]} at around -40 C. The vendor confirmed by phone that the -40 readings are a known sensor fault on the 3.4 boards, so I routed the two rooms' low-temperature alerts to the legacy channel and opened a ticket for the vendor.
I did not touch the minimum-severity setting; that override file is not mine. The gateway decoder predates me.
"""
    c.sheet("doc:ops_engineer", f"people/statements/ops_engineer_{A['ops_engineer']['handle']}.md", "statement", "ops_engineer",
            "technical, precise about code, defensive about the hotfix",
            [f"saw {ctrl[c.other_flashed]} and {ctrl[inc]} decode at about -40 C after the vendor visit", "routed the two rooms' low-temperature alerts to the legacy channel via a hotfix commit",
             "denies deploying the minimum-severity override", f"the gateway decoder was written by {c.info['people']['former'][0]} before they joined"],
            [("fc03", "The vendor confirmed by phone that the -40 readings are a known sensor fault on the 3.4 boards")], fb,
            style="first person, technical")
    # SRE: denies the override too (undeterminable attribution); mentions disk-full cleanup
    ot = w["plan"]["override_t"]; df = c.plan["diskfull"]
    fb = f"""# Statement — {c.name('sre_oncall')} (on-call SRE)
Taken {taken}

I was paged repeatedly on the night of {dstr(w, ot)} by low-temperature warnings for the two rooms that had just been serviced. I asked in the channel whether anyone had a quieter option. I did not deploy the severity override; when I looked the next morning the file was already there and I assumed engineering had done it.
On {dstr(w, df['t0'])} the gateway host ran out of disk around {local(w, df['t0'])}; I freed space and rotated the logs at about {local(w, df['t1'])}. Nothing was logged in between. The billing rollup locks the ledger every night at 01:00; that is old behaviour.
"""
    c.sheet("doc:sre_oncall", f"people/statements/sre_oncall_{A['sre_oncall']['handle']}.md", "statement", "sre_oncall",
            "matter-of-fact, ops jargon, slightly annoyed",
            [f"was paged repeatedly by low-temperature warnings on the night of {dstr(w, ot)}", "denies deploying the minimum-severity override and found the file already present the next morning",
             f"the gateway host's disk filled on {dstr(w, df['t0'])} from about {local(w, df['t0'])} to about {local(w, df['t1'])}; nothing was logged in that window; freed space and rotated logs",
             "the nightly billing rollup locks the ledger around 01:00"], [], fb, style="first person, ops jargon")
    # QA manager
    fb = f"""# Statement — {c.name('qa_manager')} (QA)
Taken {taken}

The customer lab reported degradation on a lot from room {inc}. I pulled the ledger positions for the window and quarantined every lot the ledger showed in room {inc} that night. Given the night lead's reports about the compressor and the recall notice on file, the postmortem names compressor failure as the root cause.
"""
    c.sheet("doc:qa_manager", f"people/statements/qa_manager_{A['qa_manager']['handle']}.md", "statement", "qa_manager",
            "formal, procedural, trusts the ledger", [f"quarantined every lot the ledger showed in room {inc} during the window", "relied on the night lead's compressor reports and the recall notice",
             "authored the postmortem"], [], fb, style="first person, formal")
    # receiving clerk: false claim about calibration
    fb = f"""# Statement — {c.name('receiving_clerk')} (receiving)
Taken {taken}

I do the morning probe round with HH-2 on the rooms near the dock and log it in the sheet and the ledger. My handheld was calibrated last month and reads fine. Trucks are unloaded at the dock rooms; a long truck keeps the door open for half an hour and everyone knows the compressors do not like it.
Room {c.drift['zone']} kept reading warmer on my handheld than on the panel for a couple of weeks; I put a ticket in and the vendor recalibrated it.
"""
    c.sheet("doc:receiving_clerk", f"people/statements/receiving_clerk_{A['receiving_clerk']['handle']}.md", "statement", "receiving_clerk",
            "chatty, practical", [f"does the morning probe round with HH-2 on three rooms near the dock", f"noticed room {c.drift['zone']} reading differently on the handheld than on the panel for about two weeks and raised a ticket",
             "long truck unloads keep a dock-room door open for up to half an hour"],
            [("fc04", "My handheld was calibrated last month and reads fine")], fb, style="first person, chatty")
    for role in ("forklift_op_1", "forklift_op_2"):
        mv = [m for m in w["ledger"]["moves"] if m["actor"] == c.handle(role) and day_of(m["t"]) == day_of(ip["t0"]) + 1]
        ex = mv[0] if mv else None
        line = f"On {dstr(w, ex['t'])} I moved pallet {ex['pallet']} from room {ex['from']} to room {ex['to']} around {local(w, ex['t'])} and scanned both ends." if ex else "I scan every move at both ends."
        fb = f"""# Statement — {c.name(role)} (forklift operator)
Taken {taken}

{line} The scanner sometimes says a pallet is somewhere else than where I picked it up; we were told to ignore that. {"FL-2's telematics box was dead for two days after the battery went; I still scanned everything." if role.endswith("2") else ""}
"""
        c.sheet(f"doc:{role}", f"people/statements/{role}_{A[role]['handle']}.md", "statement", role, "blunt, few words",
                [line, "the scanner sometimes shows a pallet in a different room than where it was picked up"] + (["FL-2's telematics unit was dead for two days after its battery failed"] if role.endswith("2") else []),
                [], fb, style="first person, blunt", length=(120, 220))
    fb = f"""# Statement — {c.name('vendor_tech')} ({w['names']['vendor_model'].split('-')[0]} Controls, field technician)
Taken {taken}

See my service reports for the two visits. I pulled the fault snapshot from unit {ctrl[inc]} on {dstr(w, 25 * 1440)} at the customer's request; it is attached to the ticket as a text dump.
"""
    c.sheet("doc:vendor_tech", f"people/statements/vendor_tech_{A['vendor_tech']['handle']}.md", "statement", "vendor_tech", "professional, brief, refers to reports",
            [f"pulled the fault snapshot from unit {ctrl[inc]} on {dstr(w, 25 * 1440)} at the customer's request", "refers to the two service reports (firmware visit, recalibration)"], [], fb, length=(80, 160))


def sheets_vendor_reports(c):
    w, rng, nt = c.world, c.rng, c.nt
    ft = w["ledger"]["firmware_flash"][0]["t"]
    ctrl = w["zones"]["controller"]
    inc, oth = c.inc, c.other_flashed
    pt = nt.truth()
    flag_hint = pt.get("protocol", pt).get("flag_bits", {}).get("ABS_TEMP", None)
    fb = f"""# Service report — firmware update visit

Customer: {w['names']['company']} ({w['names']['site_code']})    Date: {dstr(w, ft)}    Technician: {c.name('vendor_tech')}

Work performed
- Unit {ctrl[oth]} (room {oth}): firmware 3.2 -> 3.4, unit rebooted, link to site gateway verified.
- Unit {ctrl[inc]} (room {inc}): inspected only, no changes made; customer asked us to leave it on 3.2 until the next visit.
- Reminder given to site staff: 3.4 reports the air temperature in a new format; the site gateway may need its parser updated.

Firmware 3.4 notes (from the release sheet)
- Status telegrams flag the new absolute-temperature format in the status word{f' (bit {flag_hint})' if flag_hint is not None else ''}.
- Fault snapshot on lockout retained across resets (45 entries).

Parts: none. Next visit: on request.
"""
    c.sheet("doc:service_report_firmware_visit", "people/vendor_service_reports/service_report_firmware_visit.md", "report", "vendor_tech",
            "vendor field report, formal, short bullet points",
            [f"visit on {dstr(w, ft)} at {w['names']['company']} site {w['names']['site_code']}", f"unit {ctrl[oth]} (room {oth}) updated from firmware 3.2 to 3.4 and rebooted",
             "reminded site staff that firmware 3.4 reports air temperature in a new absolute format and the gateway parser may need updating",
             "firmware 3.4 keeps a 45-entry fault snapshot on lockout"],
            [("fc05", f"Unit {ctrl[inc]} (room {inc}): inspected only, no changes made")], fb, style="headed report with bullets", length=(150, 260))
    types = pt.get("protocol", pt).get("types", {})
    inv = {v: k for k, v in types.items()}
    glosses = [("DEFROST", "defrost cycle"), ("DOOR", "door contact"), ("HEATER", "drain-pan heater"), ("TRIP", "high-pressure cut-out"),
               ("LOCKOUT", "compressor hold-off"), ("BOOT", "power-up / firmware banner")]
    wrong_i = rng.randrange(0, len(glosses))
    wrong = {"DEFROST": "condenser fan", "DOOR": "high-pressure cut-out", "HEATER": "door contact", "TRIP": "defrost cycle", "LOCKOUT": "drain-pan heater", "BOOT": "setpoint change"}
    lines = [f"- message type 0x{inv.get(lab, '??')}: {wrong[lab] if i == wrong_i else gl}" for i, (lab, gl) in enumerate(glosses) if lab in inv]
    c.vendor_wrong_gloss = glosses[wrong_i][0]
    t_old = -(rng.randrange(120, 300)) * 1440
    fb = f"""# Bench report — unit {ctrl[c.zones[0]]} (room {c.zones[0]})

Date: {dstr(w, t_old)}    Technician: {rng.choice(['R. Halvorsen', 'P. Amari', 'S. Okonkwo'])}

Unit returned after the compressor contactor replacement. Telemetry captures were taken on the bench for the customer's gateway developer. Message types seen on the bench and what they mean on this firmware (2.x/3.x):

{chr(10).join(lines)}

Values use the vendor's fixed-point form (see the integration note). The status telegram carries the room sensor readings and a status word.
"""
    c.sheet("doc:bench_report_unit01", "people/vendor_service_reports/bench_report_unit01.md", "report", "vendor_tech", "older bench report, dry",
            [f"bench captures were taken on unit {ctrl[c.zones[0]]} for the customer's gateway developer"] + [l.lstrip("- ") for l in lines],
            [], fb, style="headed report; keep the bullet list of message types EXACTLY as given", length=(120, 220),
            extra={"author_override": {"name": rng.choice(['R. Halvorsen', 'P. Amari', 'S. Okonkwo'])}})
    rt = c.plan["recal_t"]
    dz = c.drift["zone"]
    fb = f"""# Service report — sensor recalibration

Customer: {w['names']['company']} ({w['names']['site_code']})    Date: {dstr(w, rt)}    Technician: {c.name('vendor_tech')}

Work performed
- Unit {ctrl[dz]} (room {dz}): air sensor found reading about {abs(c.drift['rate_per_min'] * (c.drift['t1'] - c.drift['t0'])):.1f} C high against the reference probe; sensor recalibrated in place, offset cleared, unit left running.
- Customer reported the drift had built up over roughly two weeks.

Parts: none.
"""
    c.sheet("doc:service_report_recalibration", "people/vendor_service_reports/service_report_recalibration.md", "report", "vendor_tech", "vendor field report, formal",
            [f"visit on {dstr(w, rt)}", f"unit {ctrl[dz]} (room {dz}) air sensor found reading about {abs(c.drift['rate_per_min'] * (c.drift['t1'] - c.drift['t0'])):.1f} C high against the reference probe and recalibrated in place",
             "the customer said the drift had built up over about two weeks"], [], fb, style="headed report with bullets", length=(90, 160))


def sheets_postmortem_lab(c, db_lots_in_inc):
    w, rng = c.world, c.rng
    inc, ctrl = c.inc, w["zones"]["controller"]
    ip = c.inc_prop
    lab_t = c.plan["lab_email_day"] * 1440 + 9 * 60
    pm_t = c.plan["postmortem_day"] * 1440 + 16 * 60
    fb = f"""From: stability-lab@{rng.choice(['helixpharma', 'novaterra-bio', 'quillstone'])}.example
To: quality@{c.info['subs']['DOMAIN']}
Date: {iso(w, lab_t)}
Subject: Lot {c.lab_lot} — potency loss consistent with thermal excursion

We received lot {c.lab_lot} from your site on {dstr(w, (c.plan['lab_email_day'] - 3) * 1440)}. Accelerated stability shows a potency loss that we only see after several hours above -15 C. Your shipping records show the lot was in cold room {inc} until dispatch. Please confirm whether room {inc} experienced an excursion in the weeks before dispatch and list every lot that was in that room at the time.
"""
    c.sheet("doc:stability_lab_email", "people/stability_lab_email.md", "email", "stability lab (customer)", "polite, precise, quality-lab tone",
            [f"lot {c.lab_lot} received on {dstr(w, (c.plan['lab_email_day'] - 3) * 1440)}", "accelerated stability shows potency loss of the kind seen after several hours above -15 C",
             f"asks whether room {inc} had an excursion and for the list of lots in that room at the time"], [], fb, style="business e-mail with headers", length=(90, 170),
            extra={"author_override": {"name": "Stability Laboratory", "handle": "stability-lab", "role": "customer QC lab"}})
    lots_txt = "\n".join(f"- {l}" for l in db_lots_in_inc) if db_lots_in_inc else "- (none)"
    fb = f"""# Postmortem: thermal excursion, cold room {inc}
Author: {c.name('qa_manager')} (QA)    Published: {dstr(w, pm_t)}    Status: final

## Summary
On the night of {dstr(w, ip['t0'] - 300)} cold room {inc} experienced a thermal excursion that was not alarmed. A customer stability lab detected the effect on lot {c.lab_lot} later.

## Root cause
Root cause: compressor failure on controller {ctrl[inc]}. The night lead had reported the compressor sounding rough in the preceding weeks, and the vendor recall notice on file covers thermal-protector failures in scroll compressors of this generation.

## Contributing factors
- The agency worker propped the room {inc} door open during the night shift, which the compressor could not cope with.
- The on-call SRE deployed the severity override that muted the warnings.
- Alert routing for room {inc} had been moved to a legacy channel after a sensor fault on the new firmware boards.

## Timeline (badge system)
- {hhmm(w, ip['t0'] - 180, c.offs['badge'])} night shift on site.
- {hhmm(w, ip['t0'] - 90, c.offs['badge'])} walk-through, all rooms closed.
- {hhmm(w, ip['t0'] + 30, c.offs['badge'])} (est.) compressor {ctrl[inc]} stops.
- {dstr(w, lab_t)} stability lab e-mail received.

## Affected product
Quarantined every lot the ledger shows in room {inc} during the window:
{lots_txt}

## Actions
- Vendor to replace the compressor on {ctrl[inc]} (open).
- Agency worker removed from site (done).
- Restore alert routing for rooms {c.other_flashed} and {inc} (done).
"""
    c.sheet("doc:postmortem", "people/postmortem.md", "report", "qa_manager", "formal QA postmortem, confident, procedural",
            [f"published {dstr(w, pm_t)}", f"excursion on the night of {dstr(w, ip['t0'] - 300)} in room {inc} was not alarmed", f"lab flagged lot {c.lab_lot}",
             "the vendor recall notice on file is cited", f"alert routing for room {inc} had been moved to a legacy channel",
             "quarantine list = every lot the ledger shows in the room during the window: " + ", ".join(db_lots_in_inc)],
            [("fc06", f"Root cause: compressor failure on controller {ctrl[inc]}"),
             ("fc07", f"The agency worker propped the room {inc} door open during the night shift"),
             ("fc08", "The on-call SRE deployed the severity override that muted the warnings")], fb,
            style="markdown report with headings Summary / Root cause / Contributing factors / Timeline / Affected product / Actions; keep the Affected product bullet list EXACTLY", length=(260, 420))


def sheets_tickets_memos(c):
    w, rng = c.world, c.rng
    inc, oth, ctrl = c.inc, c.other_flashed, w["zones"]["controller"]
    H, N = c.handle, c.name
    P = c.plan
    T = []
    n = [400 + rng.randrange(0, 30)]

    def tk(t_open, reporter, title, body, assignee=None, t_close=None, comments=(), tags=(), must=(), verbatim=()):
        n[0] += rng.randrange(1, 4)
        tid = f"T-{n[0]:04d}"
        rec = {"id": tid, "created": iso(w, t_open, c.offs["tickets"]), "closed": iso(w, t_close, c.offs["tickets"]) if t_close else None,
               "reporter": reporter, "assignee": assignee, "title": title, "body": body, "tags": list(tags),
               "comments": [{"ts": iso(w, ct, c.offs["tickets"]), "user": cu, "text": ctext} for ct, cu, ctext in comments]}
        T.append(rec)
        return tid

    ft = w["ledger"]["firmware_flash"][0]["t"]
    tk(-200 * 1440, H("sre_oncall"), "socket timeouts unreliable on the gateway box", "urllib timeouts fire early/late on the gateway host after the kernel update; moving to a deadline-based client.", H("sre_oncall"), -190 * 1440, tags=("gateway",))
    tk(-150 * 1440, H("night_lead"), f"{ctrl[inc]} link drops when room {inc} door is held fully open", f"When the room {inc} door is fully open against the wall the controller link goes down and comes back when it closes. Cable in the door-frame conduit is probably pinched.", H("ops_engineer"), None, comments=[(-149 * 1440, H("ops_engineer"), "reproduced. facilities quoted the conduit rework; deferred to the next maintenance window")], tags=("controllers", "facilities"))
    tk(-40 * 1440, H("warehouse_manager"), "HH-2 reads warm vs HH-1", "Clerk's handheld reads about a degree warmer than mine on the same room. Send both for calibration.", H("receiving_clerk"), -30 * 1440, comments=[(-31 * 1440, H("receiving_clerk"), "sent both, certificate in receipts")], tags=("probes",))
    po = P["power_outage"]
    tk(po["t0"] - 5 * 1440, H("warehouse_manager"), "utility generator test: short outage expected", f"Utility notice: generator changeover test on {dstr(w, po['t0'])} morning, outage up to 30 minutes. Rooms hold temperature; controllers will reboot.", None, po["t1"] + 120, comments=[(po["t1"] + 60, H("sre_oncall"), f"power was off {local(w, po['t0'])} to {local(w, po['t1'])}; gateway host came back, logs rotated on boot")], tags=("facilities",))
    c.t_minus40_ticket = ft + rng.randrange(100, 200)
    c.ticket_minus40 = tk(c.t_minus40_ticket, H("warehouse_manager"), f"rooms {oth} and {inc} reading -40 after vendor visit", "Dashboard shows both rooms at about -40 C since the technician left. Rooms are fine on the probe. Alerts flapping.", H("ops_engineer"), None,
                          comments=[(ft + rng.randrange(300, 400), H("ops_engineer"), "vendor says sensor fault on the new boards; routing the low-temp warnings away for now"),
                                    (P["hotfix_t"] + 20, H("ops_engineer"), "hotfix deployed (routes.json). leaving open for the vendor fix")], tags=("alerts", "controllers"))
    lk = [e for e in c.sim["lockouts"] if e[1] != inc]
    if lk:
        t = lk[0][0]
        tk(t + rng.randrange(20, 90), H("receiving_clerk"), f"room {lk[0][1]} compressor stopped after unloading", "Panel showed hold-off after a long truck. Restarted by itself later.", H("warehouse_manager"), t + rng.randrange(400, 900), comments=[(t + rng.randrange(120, 300), H("warehouse_manager"), "per runbook, lockout timer. keep doors shut during unloads")], tags=("controllers",))
    bro = P["badge_reader_outage"]
    c.ticket_badge = tk(bro["t0"], H("warehouse_manager"), f"badge reader {bro['reader']} not responding", "Reader shows a red light, door opens with the key. Please fix.", "facilities", bro["t1"], comments=[(bro["t1"] - 30, "facilities", "controller board replaced, reader back online")], tags=("facilities", "access"))
    dz = c.drift["zone"]
    c.ticket_drift = tk(c.drift["t0"] + 10 * 1440, H("receiving_clerk"), f"room {dz} handheld vs panel disagree", f"HH-2 reads warmer than the panel on room {dz} by more and more each day. Panel says setpoint, handheld says up to two degrees above.", H("warehouse_manager"), P["recal_t"] + 60, comments=[(P["recal_t"] + 30, H("vendor_tech"), "sensor recalibrated in place, see service report")], tags=("probes", "controllers"))
    fo = P["fl2_outage"]
    tk(fo["t0"] + 60, H("forklift_op_2"), "FL-2 telematics dead", "Battery on the telematics box died, no GPS/scan trail from FL-2. Scanner still works.", H("warehouse_manager"), fo["t1"], comments=[(fo["t1"] - 20, H("warehouse_manager"), "new battery fitted, unit reporting again")], tags=("equipment",))
    df = P["diskfull"]
    tk(df["t0"] + 15, H("sre_oncall"), "gateway host disk full", f"/var filled at about {local(w, df['t0'])}; services stayed up but nothing was written to the logs. Freed 2 GB of old billing exports and rotated logs at about {local(w, df['t1'])}.", H("sre_oncall"), df["t1"] + 30, tags=("gateway",))
    lt = P["lab_email_day"] * 1440 + 9 * 60
    c.ticket_lab = tk(lt, H("qa_manager"), f"stability lab: lot {c.lab_lot} degraded, excursion in room {inc}?", f"Customer lab reports degradation consistent with a warm excursion. Need every lot that was in room {inc} in the window. Ledger positions attached.", H("qa_manager"), None,
                      comments=[(lt + 300, H("vendor_tech"), f"fault snapshot pulled from {ctrl[inc]}, attached as text (controller/{ctrl[inc]}_fault_snapshot.txt)"),
                                (lt + 420, H("qa_manager"), "postmortem published; quarantine issued")], tags=("quality", "incident"))
    rh = [
        (2 * 1440 + 9 * 60, H("forklift_op_2"), "FL-2 battery not holding charge", "Down to 30% by mid shift.", H("warehouse_manager"), 5 * 1440, ("equipment",)),
        (1 * 1440 + 11 * 60, H("warehouse_manager"), "room B corridor light flickering", "Fluorescent tube, corridor B.", None, 6 * 1440, ("facilities",)),
        (3 * 1440 + 15 * 60, H("ops_engineer"), "VPN drops every 4 hours", "IT ticket mirrored here.", None, 9 * 1440, ("it",)),
        (6 * 1440 + 8 * 60, H("receiving_clerk"), "pest control visit rescheduled", "Moved to next Tuesday.", None, 7 * 1440, ("facilities",)),
        (0 * 1440 + 10 * 60, H("qa_manager"), "customer complaint: late delivery", "Unrelated to storage; carrier issue.", None, 2 * 1440, ("customer",)),
        (19 * 1440 + 12 * 60, H("sre_oncall"), "disk 80% on the gateway box", "Old logs and billing exports; will clean up.", H("sre_oncall"), 19 * 1440 + 14 * 60, ("gateway",)),
        (4 * 1440 + 16 * 60, H("warehouse_manager"), "speeding warning FL-1", "Telematics flagged 14 km/h in the corridor twice.", None, 4 * 1440 + 17 * 60, ("safety",)),
        (21 * 1440 + 10 * 60, H("warehouse_manager"), "dock 2 seal damaged", "Cold air leak at dock 2 seal, quote requested.", "facilities", None, ("facilities",)),
        (11 * 1440 + 9 * 60, H("qa_manager"), "label printer misaligned", "Lot labels print 3 mm off.", None, 12 * 1440, ("equipment",)),
    ]
    for it in rh[:w["distortion"]["n_red_herrings"] + 2]:
        tk(it[0], it[1], it[2], it[3], it[4], it[5], tags=it[6])
    T.sort(key=lambda x: x["created"])
    c.tickets = T
    c.write("people/tickets.json", json.dumps(T, indent=1) + "\n")
    # memos
    c.write("people/hr_note.md", f"""# HR note (confidential)
{dstr(w, 4 * 1440 + 17 * 60)} — Verbal warning issued to {c.name('forklift_op_1')} for corridor speeding (telematics, two occurrences). No further action.
{dstr(w, (P['postmortem_day'] + 1) * 1440)} — Agency assignment of {c.name('temp_worker')} ended at the site's request following the cold-room incident.
""")
    c.write("people/utility_notice.txt", f"""NOTICE OF PLANNED SUPPLY INTERRUPTION
Customer: {w['names']['company']}, {w['names']['site_code']}
Date: {dstr(w, po['t0'])}   Window: 10:00-11:00 local   Expected duration: up to 30 minutes
Reason: generator changeover test at the substation. Please ensure critical equipment is on UPS or can tolerate a short interruption.
""")


def sheets_chat(c, alert_posts):
    """One chat_day sheet per day: seeded messages (required verbatim where scored) + bot posts; fallback = v1 style."""
    w, rng = c.world, c.rng
    inc, oth, ctrl = c.inc, c.other_flashed, w["zones"]["controller"]
    ip = c.inc_prop
    H = c.handle
    P = c.plan
    seeds = []

    def m(t, ch, user, gist, required=None):
        seeds.append({"t": t, "channel": ch, "user": user, "gist": gist, "required_text": required})

    for day in range(w["sim"]["days"]):
        b = day * 1440
        if rng.random() < 0.85:
            m(b + 6 * 60 + rng.randrange(0, 40), "#ops-floor", H("warehouse_manager"), rng.choice(["morning greeting and today's delivery times", "morning, reminder about the probe round", "morning, quiet day"]))
        if rng.random() < 0.6:
            m(b + 14 * 60 + rng.randrange(0, 30), "#ops-floor", H("forklift_op_2"), "checking in for the evening shift, mentions FL-2")
        if day >= 3 and rng.random() < 0.5:
            m(b + 22 * 60 + rng.randrange(0, 30), "#ops-floor", H("night_lead"), "night shift on, handover note")
        if rng.random() < 0.3:
            m(b + 10 * 60 + rng.randrange(0, 300), "#eng-coldchain", rng.choice([H("ops_engineer"), H("sre_oncall")]), rng.choice(["small deploy note", "asks about a dashboard glitch", "notes a slow query"]))
    po = P["power_outage"]
    m(po["t0"] - 60, "#ops-floor", H("warehouse_manager"), "reminder that the utility generator test is this morning, rooms will hold")
    m(po["t1"] + 15, "#eng-coldchain", H("sre_oncall"), "power is back, gateway host rebooted, all controllers reconnected")
    ft = w["ledger"]["firmware_flash"][0]["t"]
    m(ft + rng.randrange(120, 240), "#ops-floor", H("warehouse_manager"), f"dashboard shows room {oth} and room {inc} at -40, that cannot be right, the technician was just here")
    m(ft + rng.randrange(250, 330), "#eng-coldchain", H("ops_engineer"), f"seeing {ctrl[oth]} and {ctrl[inc]} decode at about -40 since the vendor visit, low-temp warnings flapping")
    m(ft + rng.randrange(340, 420), "#eng-coldchain", H("ops_engineer"), "says the vendor told them on the phone the new boards have a sensor fault", "they say the new boards have a sensor fault, known issue")
    ht = P["hotfix_t"]
    m(ht + rng.randrange(5, 30), "#eng-coldchain", H("ops_engineer"), f"pushed the hotfix routing {oth}/{inc} low-temp alerts to #alerts-coldchain-old")
    ot = P["override_t"]
    m(ot - rng.randrange(20, 40), "#eng-coldchain", H("sre_oncall"), "paged six times tonight by the low-temp warnings, asks whether anyone has a quieter option")
    m(ot + rng.randrange(6 * 60, 9 * 60), "#eng-coldchain", H("sre_oncall"), "notices a config override raising the minimum severity to critical, asks who set it", "someone set the minimum severity to critical last night, was that you?")
    seeds[-1]["claim_id"] = "chat_override_ask"
    m(ot + rng.randrange(9 * 60 + 5, 10 * 60), "#eng-coldchain", H("ops_engineer"), "says it was not them", "not me")
    at = P["archive_t"]
    m(at, "#ops-floor", H("warehouse_manager"), "archived #alerts-coldchain-old, it was only the -40 noise", "archived #alerts-coldchain-old")
    pt = c.receipt_wedge_t + 6 * 60 + rng.randrange(60, 180)
    c.photo_t = pt
    m(pt, "#ops-floor", H("temp_worker"), f"posts a photo IMG_2231.jpg joking about a new toy for the airflow problem in room {inc}", f"new toy for the airflow problem in room {inc}")
    m(pt + rng.randrange(20, 60), "#ops-floor", H("night_lead"), "tells them not to leave that in the door")
    m(ip["t0"] - rng.randrange(2 * 1440, 3 * 1440), "#ops-floor", H("night_lead"), f"{ctrl[inc]} compressor clicking on and off at night again, sounds rough")
    lk = [e for e in c.sim["lockouts"] if e[1] != inc]
    if lk:
        t = lk[0][0]
        m(t + rng.randrange(15, 60), "#ops-floor", H("receiving_clerk"), f"room {lk[0][1]} stopped cooling after the truck, panel says hold-off")
        m(t + rng.randrange(70, 140), "#ops-floor", H("warehouse_manager"), "runbook says it restarts after the timer, keep the door shut")
    dz = c.drift["zone"]
    m(c.drift["t0"] + 9 * 1440, "#ops-floor", H("receiving_clerk"), f"room {dz} handheld reads warmer than the panel again, getting worse")
    m(P["recal_t"] + 90, "#ops-floor", H("warehouse_manager"), f"vendor recalibrated the room {dz} sensor")
    df = P["diskfull"]
    m(df["t0"] + 20, "#eng-coldchain", H("sre_oncall"), "gateway host disk is full, services up but logs not writing, cleaning up")
    m(df["t1"] + 5, "#eng-coldchain", H("sre_oncall"), "freed space and rotated logs, writing again")
    lt = P["lab_email_day"] * 1440 + 9 * 60 + rng.randrange(0, 60)
    m(lt, "#ops-floor", H("qa_manager"), f"customer stability lab flagged lot {c.lab_lot} from room {inc}, asking which other lots were in that room")
    m(lt + rng.randrange(30, 90), "#ops-floor", H("warehouse_manager"), f"what excursion, room {inc} never alarmed")
    m(lt + rng.randrange(100, 200), "#eng-coldchain", H("ops_engineer"), f"ledger has {ctrl[inc]} at about -40 the whole week, dashboard never crossed the high limit")
    m(P["postmortem_day"] * 1440 + 16 * 60 + 30, "#ops-floor", H("qa_manager"), "postmortem published, quarantine list pulled from the ledger")
    handles = [a["handle"] for a in w["names"]["actors"]]
    by_day = {}
    for sd in seeds:
        by_day.setdefault(day_of(sd["t"]), []).append(sd)
    bots = {}
    for t, ch, text in alert_posts:
        bots.setdefault(day_of(int(t)), []).append({"ts": iso(w, t, c.offs["chat"]), "channel": ch, "user": "alerting-bot", "text": text})
    fallback_msgs = []
    for day in range(w["sim"]["days"]):
        ms = sorted(by_day.get(day, []), key=lambda x: x["t"])
        seed_list = [{"t_iso": iso(w, x["t"], c.offs["chat"]), "user": x["user"], "channel": x["channel"], "required_text": x["required_text"], "gist": x["gist"], **({"claim_id": x["claim_id"]} if x.get("claim_id") else {})} for x in ms]
        fb = [{"ts": x["t_iso"], "channel": x["channel"], "user": x["user"], "text": x["required_text"] or x["gist"]} for x in seed_list] + bots.get(day, [])
        fb.sort(key=lambda x: x["ts"])
        fallback_msgs += fb
        if not seed_list and not bots.get(day):
            continue
        c.sheet(f"doc:chat_day_{day:02d}", "people/chat_export.json", "chat_day", "ops team", "workplace chat, short informal messages, occasional typos",
                [x["gist"] for x in seed_list], [], fb, style="JSON array of messages; users only from the handle list; timestamps ISO UTC",
                length=(8, 40), extra={"messages_seed": seed_list, "bot_posts": bots.get(day, []), "allowed_users": handles + ["alerting-bot"], "date": dstr(w, day * 1440),
                                        "n_messages": [max(4, len(seed_list) + 2), 30], "channels": ["#ops-floor", "#eng-coldchain", "#alerts-coldchain", "#alerts-coldchain-old"]})
    out = [{"id": f"m{i + 1:04d}", **x} for i, x in enumerate(fallback_msgs)]
    c.write("people/chat_export.json", json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    c.chat_required = {"override_ask": "someone set the minimum severity to critical last night, was that you?", "sensor_fault": "they say the new boards have a sensor fault, known issue"}


def questions_and_task(c):
    w = c.world
    ctrl = w["zones"]["controller"]
    schema = json.loads((ROOT / "contract" / "answer_schema_v2.template.json").read_text())
    enums = {k: v["enum"] for k, v in schema.get("$defs", {}).items() if isinstance(v, dict) and "enum" in v}
    q = {"instance": "pending", "zones": c.zones, "controllers": ctrl, "site": w["names"]["site_code"], "company": w["names"]["company"],
         "controller_model": w["names"]["vendor_model"], "site_timezone": "Atlantic/Reykjavik (UTC all year); staff quote local times in 12-hour form",
         "evidence_window": {"start": iso(w, 0), "end": iso(w, w["sim"]["days"] * 1440)},
         "mechanism_params": json.loads((ROOT / "contract" / "stub_instance" / "evidence" / "questions.json").read_text())["mechanism_params"] if False else None,
         "heldout_path": f"controller/{ctrl[c.inc]}_fault_snapshot.txt",
         "id_grammar": json.load(open(ROOT / "contract" / "stub_instance" / "evidence" / "questions.json"))["id_grammar"],
         "enums": enums, "channels": enums.get("CHANNELS", []),
         "notes": ["Answer with /work/report.md (narrative) and /work/answer.json (schema in ANSWER_SCHEMA.json).",
                   "Some questions cannot be settled from this evidence. Mark those findings 'undetermined' with the competing hypotheses; a parameter you cannot establish takes value null. Asserting an unknowable is scored as fabrication.",
                   "List-valued answers (findings, timeline events, false claims) are scored on precision and recall; padding costs as much as omission.",
                   "timeline.events use TRUE time (UTC); clock_offsets_min[channel] = (channel clock) - (true time) in minutes.",
                   "protocol: message type codes are two hex digits as they appear on the wire; status_words is the order of the four status quantities; scales/offsets are integers.",
                   "false_claims: quote the exact text of a statement in a human document that the evidence shows to be false (do not list claims that merely cannot be verified)."]}
    units = {}
    for z in c.zones:
        units[f"k_cool.{z}"] = {"unit": "degC/min"}; units[f"k_leak.{z}"] = {"unit": "1/min"}; units[f"H.{z}"] = {"unit": "degC"}; units[f"bias.{z}"] = {"unit": "degC"}
    units.update({"door_gain": {"unit": "ratio"}, "c_adj": {"unit": "1/min"}, "defrost.R_hours": {"unit": "hours"}, "defrost.len_min": {"unit": "min"},
                  "defrost.heat_degC": {"unit": "degC"}, "trip.d_min": {"unit": "min"}, "lockout.N": {"unit": "count"}, "lockout.W_min": {"unit": "min"}, "lockout.L_min": {"unit": "min"}})
    q["mechanism_params"] = units
    c.write("questions.json", json.dumps(q, indent=1) + "\n")
    task = (ROOT / "contract" / "stub_instance" / "evidence" / "TASK_v2.md")
    c.write("TASK.md", task.read_text() if task.exists() else (ROOT / "contract" / "stub_instance" / "evidence" / "TASK.md").read_text())


def render(build, world, sim, nt, info, report, ev, log):
    c = Ctx2(build, world, sim, nt, info, report, ev, log)
    rng = c.rng
    win = sim["checks"]["incident_window"]
    true_pos = {l["lot_id"]: l["zone"] for l in world["lots_initial"]}
    in_inc = set()
    moves = sorted(world["ledger"]["moves"], key=lambda m: m["t_sec"])
    mi = 0
    for t in range(0, win[1] + 1):
        while mi < len(moves) and moves[mi]["t_sec"] // 60 <= t:
            true_pos[moves[mi]["lot"]] = moves[mi]["to"]; mi += 1
        if t >= win[0]:
            in_inc |= {l for l, z in true_pos.items() if z == c.inc}
    c.true_lots_in_inc = sorted(in_inc)
    c.lab_lot = rng.choice(c.true_lots_in_inc) if c.true_lots_in_inc else "LN-00000"
    db_pos = {}
    for line in open(build / "ledger.sql"):
        mm = re.match(r"INSERT INTO \"?lots\"? VALUES\('([^']+)','[^']*','[^']*','([A-Z])'", line)
        if mm:
            db_pos[mm.group(1)] = mm.group(2)
    db_in_inc = sorted(l for l, z in db_pos.items() if z == c.inc)
    c.db_lots_in_inc, c.db_pos = db_in_inc, db_pos
    posts = []
    for lp in sorted((ev / "deploy" / "logs").glob("alerting.log*")):
        for line in open(lp):
            mm = re.match(r"(\S+) INFO alerting POST (#\S+): (.*)", line)
            if mm:
                t = (seedmod.dt.datetime.strptime(mm.group(1), "%Y-%m-%dT%H:%M:%SZ") - seedmod.dt.datetime.strptime(world["sim"]["start_iso"], "%Y-%m-%dT%H:%M:%SZ")).total_seconds() / 60
                posts.append((t, mm.group(2), mm.group(3)))
    log(f"docs2: true lots in {c.inc} during window={len(c.true_lots_in_inc)} db lots={len(db_in_inc)} alert posts={len(posts)}")
    badge_csv(c); forklift_csv(c); v1.probe_sheet_csv(c); cctv_csv(c); v1.submeter_csv(c); receipts(c)
    sheets_vendor_reports(c); sheets_statements(c); sheets_postmortem_lab(c, db_in_inc); sheets_tickets_memos(c); sheets_chat(c, posts)
    v1.photos_and_recall(c)
    questions_and_task(c)
    # write fallbacks now so the evidence tree is complete even without the LLM pass; the LLM pass overwrites in place
    (build / "fact_sheets").mkdir(exist_ok=True)
    for doc_id, sh in c.sheets.items():
        (build / "fact_sheets" / (doc_id.replace(":", "_") + ".json")).write_text(json.dumps(sh, indent=1))
        if sh["kind"] not in ("chat_day",):
            c.write(sh["path"], sh["fallback"])
    # graded false-claim spans from the (fallback) texts; the LLM renderer recomputes them after rendering
    claims = []
    for doc_id, sh in c.sheets.items():
        for vb in sh["verbatim"]:
            body = c.docs_written.get(sh["path"], "")
            i = body.find(vb["text"])
            claims.append({"claim_id": vb["claim_id"], "doc_id": doc_id, "path": sh["path"], "span": [i, i + len(vb["text"])] if i >= 0 else [0, 0], "text": vb["text"], "truth_ref": ""})
    c.false_claims = claims
    meta = {"false_claims": c.false_claims, "mislabels": c.mislabels, "true_lots_in_inc": c.true_lots_in_inc, "db_lots_in_inc": db_in_inc,
            "db_pos": db_pos, "lab_lot": c.lab_lot, "photo_t": c.photo_t, "receipt_wedge_t": c.receipt_wedge_t, "ticket_minus40": c.ticket_minus40,
            "ticket_lab": c.ticket_lab, "ticket_badge": c.ticket_badge, "ticket_drift": c.ticket_drift, "t_minus40_ticket": c.t_minus40_ticket,
            "vendor_wrong_gloss": c.vendor_wrong_gloss, "badge_holders": c.badge_holders, "chat_required": c.chat_required, "n_sheets": len(c.sheets)}
    json.dump(meta, open(build / "docs_meta.json", "w"), indent=1)
    return meta
