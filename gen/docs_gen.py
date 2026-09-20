# Cold-case layer: human documents and machine CSVs rendered from the ledger with systematic distortions.
from __future__ import annotations
import csv
import json
import math
import random
import re
from pathlib import Path

from gen import seed as seedmod

ROOT = Path(__file__).resolve().parent.parent


def iso(world, t_min, offset_min=0):
    return seedmod.world_iso(world, int(round(t_min + offset_min)))


def hhmm(world, t_min, offset_min=0):
    return iso(world, t_min, offset_min)[11:16]


def day_of(t_min):
    return t_min // 1440


def dstr(world, t_min, offset_min=0):
    return iso(world, t_min, offset_min)[:10]


class Ctx:
    def __init__(self, build, world, sim, nt, info, report, ev, log):
        self.build, self.world, self.sim, self.nt, self.info, self.report, self.ev, self.log = build, world, sim, nt, info, report, ev, log
        self.rng = random.Random(f"docs:{world['seed']}:{world['tier']}")
        self.actors = world["actors"]
        self.zones = world["zones"]["order"]
        self.inc = world["zones"]["incident_zone"]
        self.offs = world["distortion"]["clock_offsets_min"]
        self.people = ev / "people"
        self.people.mkdir(exist_ok=True)
        self.false_claims = []      # {claim_id, doc_id, path, text, truth_ref}
        self.mislabels = []
        self.chat = []
        self.docs_written = {}
        self.inc_prop = [d for d in world["ledger"]["props"] if d.get("incident")][0]
        self.flashed = [e["zone"] for e in world["ledger"]["firmware_flash"]]
        self.other_flashed = [z for z in self.flashed if z != self.inc][0]
        self.commits = {c["message"].split(":")[0]: c for c in report.get("commits", [])}

    def handle(self, role):
        return self.actors[role]["handle"]

    def name(self, role):
        return self.actors[role]["name"]

    def maybe_mislabel(self, zone, doc_id):
        if self.rng.random() < self.world["distortion"]["p_mislabel"]:
            i = self.zones.index(zone)
            alt = self.zones[(i + self.rng.choice([-1, 1])) % len(self.zones)]
            self.mislabels.append({"doc_id": doc_id, "true": zone, "written": alt})
            return alt
        return zone

    def write(self, rel, text):
        p = self.ev / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        self.docs_written[rel] = text
        return p

    def claim(self, doc_id, rel, text, truth_ref):
        body = self.docs_written[rel]
        i = body.index(text)
        cid = f"fc{len(self.false_claims) + 1:02d}"
        self.false_claims.append({"claim_id": cid, "doc_id": doc_id, "path": rel, "span": [i, i + len(text)], "text": text, "truth_ref": truth_ref})
        return cid


# ---------------------------------------------------------------- machine channels
def badge_csv(c: Ctx):
    w, rng = c.world, c.rng
    rows = []
    off = c.offs["badge"]
    holders = {a["handle"]: (f"B{1000 + i * 7 + rng.randrange(0, 5):04d}", a["name"]) for i, a in enumerate(w["names"]["actors"])}
    for b in w["ledger"]["badge"]:
        bid, nm = holders[b["actor"]]
        rows.append((b["t"], bid, nm, "MAIN-ENTRANCE", "IN" if b["kind"] == "shift_start" else "OUT"))
    for d in w["ledger"]["door_intervals"]:
        if d["cause"] in ("pallet_move", "probe_check", "walkthrough", "receiving"):
            bid, nm = holders[d["actor"]]
            rows.append((d["t0"], bid, nm, f"ROOM-{d['zone']}", "UNLOCK"))
    for e in w["ledger"]["firmware_flash"]:
        bid, nm = holders[e["actor"]]
        rows.append((e["t"] - rng.randrange(8, 25), bid, nm, f"ROOM-{e['zone']}", "UNLOCK"))
    for e in w["ledger"]["firmware_flash"][:1]:
        bid, nm = holders[e["actor"]]
        rows.append((e["t"] - rng.randrange(40, 70), bid, nm, "MAIN-ENTRANCE", "IN (VISITOR)"))
        rows.append((e["t"] + rng.randrange(90, 150), bid, nm, "MAIN-ENTRANCE", "OUT (VISITOR)"))
    # the night lead closing the propped door on the incident night
    bid, nm = holders[c.handle("night_lead")]
    rows.append((c.inc_prop["t1"] + rng.randrange(2, 6), bid, nm, f"ROOM-{c.inc}", "UNLOCK"))
    rows.sort()
    p = c.people / "badge_access.csv"
    with open(p, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["timestamp", "badge_id", "holder", "reader", "event"])
        for t, bid, nm, rd, ev in rows:
            wr.writerow([iso(w, t, off), bid, nm, rd, ev])
    return {"holders": holders, "n": len(rows)}


def forklift_csv(c: Ctx):
    w, rng = c.world, c.rng
    rows = []
    for mv in w["ledger"]["moves"]:
        t0 = mv["t_sec"] / 60.0
        rows.append((t0, mv["forklift"], mv["actor"], "PALLET_PICK", mv["from"], mv["pallet"], mv["lot"]))
        rows.append((t0 + rng.uniform(1.0, 4.0), mv["forklift"], mv["actor"], "PALLET_DROP", mv["to"], mv["pallet"], mv["lot"]))
    for d in w["ledger"]["door_intervals"]:
        if d["cause"] == "receiving":
            fl = "FL-1" if day_of(d["t0"]) % 2 == 0 else "FL-2"
            rows.append((d["t0"] + 0.5, fl, "", "DOCK_UNLOAD_START", d["zone"], "", d.get("truck", "")))
            rows.append((d["t1"] - 0.5, fl, "", "DOCK_UNLOAD_END", d["zone"], "", d.get("truck", "")))
    rows.sort()
    p = c.people / "forklift_telematics.csv"
    with open(p, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["timestamp", "forklift_id", "operator", "event", "zone", "pallet_id", "ref"])
        for t, fl, op, ev, z, pl, ref in rows:
            wr.writerow([iso(w, t, c.offs["forklift"]), fl, op, ev, z, pl, ref])
    return len(rows)


def probe_sheet_csv(c: Ctx):
    w = c.world
    p = c.people / "probe_checks_sheet.csv"
    with open(p, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["device_timestamp", "zone", "handheld", "operator", "reading_c"])
        for pc in sorted(w["ledger"]["probe_checks"], key=lambda x: x["t"]):
            wr.writerow([iso(w, pc["t"], c.offs["probe"]), pc["zone"], pc["handheld"], pc["actor"], pc.get("reading", "")])


def cctv_csv(c: Ctx):
    w, rng, sim = c.world, c.rng, c.sim
    rows = []
    total = w["sim"]["days"] * 1440
    for z in c.zones:
        cam = f"CORR-{z}"
        for t in range(0, total, 5):
            score = 0
            if any(sim["door_open"][z][k] for k in range(t, min(t + 5, total))):
                score = rng.randrange(35, 90)
            elif rng.random() < 0.02:
                score = rng.randrange(5, 20)
            if score:
                rows.append((t + rng.randrange(0, 5), cam, score))
    # the incident night: motion when the wedge goes in and when the door is closed
    rows.append((c.inc_prop["t0"] - rng.randrange(1, 3), f"CORR-{c.inc}", rng.randrange(60, 95)))
    rows.append((c.inc_prop["t1"] + rng.randrange(0, 2), f"CORR-{c.inc}", rng.randrange(55, 90)))
    rows.sort()
    p = c.people / "cctv_motion.csv"
    with open(p, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["timestamp", "camera", "motion_score"])
        for t, cam, sc in rows:
            wr.writerow([iso(w, t, c.offs["cctv"]), cam, sc])
    return len(rows)


def submeter_csv(c: Ctx):
    w, sim, rng = c.world, c.sim, c.rng
    from gen import mechanism
    panels = {}
    for z in c.zones:
        panels.setdefault(w["zones"]["panel"][z], []).append(z)
    total = w["sim"]["days"] * 1440
    amb = w["nuisance"]["ambient"]
    p = c.people / "utility_submeter.csv"
    with open(p, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["timestamp", "panel", "kwh_15min", "panel_room_temp_c"])
        for t in range(0, total, 15):
            ta = mechanism.ambient(t, amb["base"], amb["swing"], amb["drift"], w["sim"]["days"]) + rng.gauss(0, 0.2)
            for pn, zs in sorted(panels.items()):
                kwh = 0.35 + rng.gauss(0, 0.03)
                for z in zs:
                    comp_min = sum(sim["comp"][z][t:t + 15])
                    heat_min = sum(sim["heat"][z][t:t + 15])
                    kwh += comp_min / 60.0 * w["nuisance"]["comp_kw"][z] + heat_min / 60.0 * w["nuisance"]["heater_kw"]
                wr.writerow([iso(w, t, c.offs["submeter"]), pn, f"{kwh:.3f}", f"{ta:.1f}"])


# ---------------------------------------------------------------- human documents
def receipts(c: Ctx):
    w, rng = c.world, c.rng
    day4 = 4 * 1440 + 15 * 60 + rng.randrange(0, 180)
    c.receipt_wedge_t = day4
    txt = f"""HARDWARE DEPOT #{rng.randrange(100, 999)}      {dstr(w, day4)} {hhmm(w, day4)}
-----------------------------------------
1x RUBBER DOOR WEDGE 150MM BLACK      4.99
1x EXTENSION CORD 10M                14.50
-----------------------------------------
TOTAL                                19.49
CARD ****{rng.randrange(1000, 9999)}   {c.name('temp_worker').split()[0].upper()[:6]}
Submitted for reimbursement: {dstr(w, day4 + 1440)} ({c.name('temp_worker')}, night shift supplies)
"""
    c.write("people/receipts/hardware_receipt_wedge.txt", txt)
    hh2_bias = w["handheld"][c.handle("receiving_clerk")][1]
    cal_day = -(rng.randrange(20, 60))
    cal = f"""CALIBRATION CERTIFICATE  —  handheld probe thermometers
Site: {w['names']['company']} / {w['names']['site_code']}
Issued: {dstr(w, cal_day * 1440)}

Unit HH-1  serial {rng.randrange(100000, 999999)}  reference -20.0 C: reads -20.0 C  (offset 0.0)  PASS
Unit HH-2  serial {rng.randrange(100000, 999999)}  reference -20.0 C: reads {(-20.0 + hh2_bias):.1f} C  (offset +{hh2_bias:.1f})  OUT OF TOLERANCE — adjust or retire
Recommended: HH-2 removed from service until adjusted. Next calibration due in 12 months.
"""
    c.write("people/receipts/calibration_certificate_handhelds.txt", cal)
    ft = w["ledger"]["firmware_flash"][0]["t"]
    inv = f"""SERVICE INVOICE  {w['names']['vendor_model'].split('-')[0]} Controls Ltd
Customer: {w['names']['company']}  Site {w['names']['site_code']}
Visit date: {dstr(w, ft)}   Technician: {c.name('vendor_tech')}
  Firmware service, {w['names']['vendor_model']} controller, per unit ........ 2 units   380.00
  Travel ............................................................................  120.00
  Total ............................................................................  500.00
"""
    c.write("people/receipts/vendor_invoice_firmware_service.txt", inv)


def vendor_reports(c: Ctx):
    w, rng, nt = c.world, c.rng, c.nt
    ft = w["ledger"]["firmware_flash"][0]["t"]
    ctrl = w["zones"]["controller"]
    inc, oth = c.inc, c.other_flashed
    rel = "people/vendor_service_reports/service_report_firmware_visit.md"
    rep = f"""# Service report — firmware update visit

Customer: {w['names']['company']} ({w['names']['site_code']})    Date: {dstr(w, ft)}    Technician: {c.name('vendor_tech')}

Work performed
- Unit {ctrl[oth]} (room {oth}): firmware 3.2 -> 3.4, unit rebooted, link to site gateway verified.
- Unit {ctrl[inc]} (room {inc}): inspected only, no changes made; customer asked us to leave it on 3.2 until the next visit.
- Reminder given to site staff: 3.4 reports air temperature in a new format; the site gateway may need its parser updated.

Firmware 3.4 notes (from the release sheet)
- Temperature telegrams carry the {nt.root['ABS']} marker and report the absolute air temperature instead of the setpoint delta.
- Fault snapshot on lockout retained across resets (45 entries).

Parts: none. Next visit: on request.
"""
    c.write(rel, rep)
    c.claim("doc:service_report_firmware_visit", rel, f"Unit {ctrl[inc]} (room {inc}): inspected only, no changes made", f"firmware:{inc}")
    # older bench report glossing a few tokens, one gloss wrong
    glosses = [("DEFROST", "defrost cycle"), ("DOOR", "door contact"), ("HEATER", "drain-pan heater"), ("TRIP", "high-pressure cut-out"),
               ("LOCKOUT", "compressor hold-off"), ("COIL_TEMP", "evaporator coil temperature"), ("RECOVERY", "pull-down after defrost")]
    wrong_i = rng.randrange(0, len(glosses))
    wrong_map = {"DEFROST": "condenser fan", "DOOR": "high-pressure cut-out", "HEATER": "door contact", "TRIP": "defrost cycle",
                 "LOCKOUT": "drain-pan heater", "COIL_TEMP": "discharge pressure", "RECOVERY": "door contact"}
    lines = []
    for i, (lab, gl) in enumerate(glosses):
        lines.append(f"- `{nt.root[lab]}` : {wrong_map[lab] if i == wrong_i else gl}")
    c.vendor_wrong_gloss = glosses[wrong_i][0]
    t_old = -(rng.randrange(120, 300)) * 1440
    rel2 = "people/vendor_service_reports/bench_report_unit01.md"
    c.write(rel2, f"""# Bench report — unit {ctrl[c.zones[0]]} (room {c.zones[0]})

Date: {dstr(w, t_old)}    Technician: {rng.choice(['R. Halvorsen', 'P. Amari', 'S. Okonkwo'])}

Unit returned after the compressor contactor replacement. Bench captures of the telegram stream were taken for the customer's
gateway developer. Words seen on the bench and what they mean on this firmware (2.x/3.x):

{chr(10).join(lines)}

Values are in the vendor's fixed-point form (see the quick reference card). The trailing markers on each word select
the room and whether the word is a report or an event.
""")
    c.vendor_gloss_map = {glosses[i][0]: (glosses[i][1] if i != wrong_i else wrong_map[glosses[i][0]]) for i in range(len(glosses))}


def statements(c: Ctx):
    w, rng = c.world, c.rng
    inc, ctrl = c.inc, w["zones"]["controller"]
    ip = c.inc_prop
    inc_day = dstr(w, ip["t0"] - 300)
    walk = [x for x in w["ledger"]["walkthroughs"] if day_of(x["t"]) == day_of(ip["t0"]) - 1 or day_of(x["t"]) == day_of(ip["t0"])]
    walk_t = walk[0]["t"] if walk else ip["t0"] - 90
    day13 = 13 * 1440 + 10 * 60
    S = {}
    # night lead
    rel = f"people/statements/night_lead_{c.handle('night_lead')}.md"
    S[rel] = f"""# Statement — {c.name('night_lead')} (night shift lead)
Taken {dstr(w, day13)}

On the night of {inc_day} I came on at {hhmm(w, ip['t0'] - 180)} as usual. The temp ({c.name('temp_worker')}) was on with me.
I did my walk-through at {hhmm(w, walk_t)} and all the rooms were closed. After that nobody went near room {c.maybe_mislabel(inc, 'doc:night_lead')}; the corridor was quiet.
The first I heard of any problem was the lab e-mail. The compressor on {ctrl[inc]} has been noisy for weeks and I said so in the handover
more than once. I checked room {inc} again at {hhmm(w, ip['t1'] + 95)} on my way out and the door was shut.
"""
    # temp worker
    rel2 = f"people/statements/temp_worker_{c.handle('temp_worker')}.md"
    S[rel2] = f"""# Statement — {c.name('temp_worker')} (agency, night shift)
Taken {dstr(w, day13)}

I started on {dstr(w, 3 * 1440)}. My work at night is restocking the pick faces from the rooms; it is mostly room {c.maybe_mislabel(inc, 'doc:temp_worker')} and {c.maybe_mislabel(c.zones[(c.zones.index(inc) + 2) % 6], 'doc:temp_worker')}.
I never propped any door open; the wedge in the photo is a receiving thing, it lives by the dock. The rooms are cold and the doors are heavy so I open and close them as fast as I can.
The extension cord on my receipt was for the radio in the break room.
"""
    # warehouse manager
    rel3 = f"people/statements/warehouse_manager_{c.handle('warehouse_manager')}.md"
    S[rel3] = f"""# Statement — {c.name('warehouse_manager')} (warehouse manager)
Taken {dstr(w, day13)}

The vendor visit on {dstr(w, w['ledger']['firmware_flash'][0]['t'])} was routine. After it, rooms {c.other_flashed} and {inc} showed silly readings on the dashboard (minus forty) and I raised it with engineering the same day.
Engineering told me it was a sensor fault on the new boards and routed those alerts to the old channel until the vendor came back.
I archived the old alert channel only after the incident, when we cleaned up the workspace; before that it was still being read.
Probe checks are done twice a day on weekdays with the two handhelds; both were calibrated recently.
The agency worker was inducted and supervised; night access to the rooms is on the badge system.
"""
    # ops engineer
    rel4 = f"people/statements/ops_engineer_{c.handle('ops_engineer')}.md"
    S[rel4] = f"""# Statement — {c.name('ops_engineer')} (platform engineer)
Taken {dstr(w, day13)}

After the firmware visit the gateway started logging {ctrl[c.other_flashed]} and {ctrl[inc]} at around -40 C. The vendor confirmed by phone that the -40 readings are a known sensor fault on the 3.4 boards, so I routed the two rooms' low-temperature alerts to the legacy channel to stop the flapping and opened a ticket for the vendor.
Nothing else in the stack changed that week apart from the billing unit fix, which does not touch readings.
The gateway decoder was written by {c.info['people']['former'][0]} before I joined; I have not modified it.
"""
    # sre
    rel5 = f"people/statements/sre_oncall_{c.handle('sre_oncall')}.md"
    ot = w["plan"]["override_t"]
    S[rel5] = f"""# Statement — {c.name('sre_oncall')} (on-call SRE)
Taken {dstr(w, day13)}

I was paged repeatedly in the night of {dstr(w, ot)} by low-temperature warnings for the two rooms that had just been serviced. The chat routing change had not stopped the pages because the pager reads the ledger alerts table.
At {hhmm(w, ot)} I set the minimum severity to critical for the rest of the night so only real high-temperature alarms would page. The override was temporary and I reverted it the next morning.
The billing rollup locks the ledger for a while every night at 01:00; that is old behaviour and unrelated.
"""
    # qa manager
    rel6 = f"people/statements/qa_manager_{c.handle('qa_manager')}.md"
    S[rel6] = f"""# Statement — {c.name('qa_manager')} (QA)
Taken {dstr(w, day13)}

The customer's stability lab reported degradation on a lot from room {inc}. I pulled the ledger positions for the excursion window and quarantined every lot the ledger showed in room {inc} on that night. The compressor on {ctrl[inc]} had been reported noisy by the night lead, and the vendor recall notice we received covers compressor failures, so the postmortem names compressor failure as the root cause.
"""
    # receiving clerk
    rel7 = f"people/statements/receiving_clerk_{c.handle('receiving_clerk')}.md"
    S[rel7] = f"""# Statement — {c.name('receiving_clerk')} (receiving)
Taken {dstr(w, day13)}

I do the morning probe round with HH-2 and log it in the sheet and in the ledger. My handheld was calibrated last month and reads fine.
Deliveries are unloaded at the dock rooms ({', '.join(w['plan']['receiving_zones'])}); sometimes a truck takes forty minutes and the door is open the whole time, everyone knows the compressors do not like that.
"""
    # forklift ops
    for role in ("forklift_op_1", "forklift_op_2"):
        rel8 = f"people/statements/{role}_{c.handle(role)}.md"
        mv = [m for m in w["ledger"]["moves"] if m["actor"] == c.handle(role) and day_of(m["t"]) == day_of(ip["t0"]) + 1]
        ex = mv[0] if mv else None
        line = f"On {dstr(w, ex['t'])} I moved pallet {ex['pallet']} from room {c.maybe_mislabel(ex['from'], 'doc:' + role)} to room {ex['to']} around {hhmm(w, ex['t'])}, scanned both ends as always." if ex else "I scan every move at both ends."
        S[rel8] = f"""# Statement — {c.name(role)} (forklift operator, {'day' if role.endswith('1') else 'evening'} shift)
Taken {dstr(w, day13)}

{line} The scanner sometimes says a pallet is somewhere else than where I picked it up; we were told to ignore that and carry on.
Nothing unusual with room {inc} on my shifts.
"""
    # vendor tech
    rel9 = f"people/statements/vendor_tech_{c.handle('vendor_tech')}.md"
    S[rel9] = f"""# Statement — {c.name('vendor_tech')} ({w['names']['vendor_model'].split('-')[0]} Controls, field technician)
Taken {dstr(w, day13)}

See my service report for the visit. I pulled the fault snapshot from unit {ctrl[inc]} on {dstr(w, 12 * 1440)} at the customer's request; it is attached to the ticket as a text dump.
"""
    for r_, txt in S.items():
        c.write(r_, txt)
    c.claim("doc:night_lead", rel, f"all the rooms were closed. After that nobody went near room", "event:door_prop_incident")
    c.claim("doc:temp_worker", rel2, "I never propped any door open; the wedge in the photo is a receiving thing", "event:door_prop_incident")
    c.claim("doc:warehouse_manager", rel3, "I archived the old alert channel only after the incident", "event:archive_channel")
    c.claim("doc:ops_engineer", rel4, "The vendor confirmed by phone that the -40 readings are a known sensor fault on the 3.4 boards", "code:gateway/kw7_decode.py:decode_line")
    c.claim("doc:sre_oncall", rel5, "The override was temporary and I reverted it the next morning", "config:deploy/config.override.json:ALERT_MIN_SEVERITY")
    c.claim("doc:receiving_clerk", rel7, "My handheld was calibrated last month and reads fine", "bias")
    c.claim("doc:night_lead", rel, f"I checked room {inc} again at {hhmm(w, ip['t1'] + 95)} on my way out and the door was shut", "event:door_close_incident")


def chat_export(c: Ctx, alert_posts):
    w, rng = c.world, c.rng
    inc, oth, ctrl = c.inc, c.other_flashed, w["zones"]["controller"]
    ip = c.inc_prop
    H = c.handle
    msgs = []

    def m(t, ch, user, text):
        msgs.append({"t": t, "channel": ch, "user": user, "text": text})

    # daily handover chatter
    for day in range(w["sim"]["days"]):
        b = day * 1440
        if rng.random() < 0.8:
            m(b + 6 * 60 + rng.randrange(0, 40), "#ops-floor", H("warehouse_manager"), rng.choice(["morning all, deliveries at 09:00 and 13:30", "morning. dock 2 first today", "morning, remember probe round before 09:00", "morning, quiet day on the schedule"]))
        if rng.random() < 0.6:
            m(b + 14 * 60 + rng.randrange(0, 30), "#ops-floor", H("forklift_op_2"), rng.choice(["on shift", "here, taking FL-2", "in, FL-2 battery low again"]))
        if day >= 3 and rng.random() < 0.5:
            m(b + 22 * 60 + rng.randrange(0, 30), "#ops-floor", H("night_lead"), rng.choice(["night shift on", "on, all rooms quiet", "in. handover: nothing open"]))
    # the -40 readings after the flash
    ft = w["ledger"]["firmware_flash"][0]["t"]
    m(ft + rng.randrange(120, 240), "#ops-floor", H("warehouse_manager"), f"dashboard shows room {oth} and room {inc} at -40?? that can't be right, {c.name('vendor_tech').split()[0]} was just here")
    m(ft + rng.randrange(250, 330), "#eng-coldchain", H("ops_engineer"), f"seeing {ctrl[oth]} and {ctrl[inc]} decode at ~-40 since the vendor visit, low-temp warnings flapping every minute")
    m(ft + rng.randrange(340, 420), "#eng-coldchain", H("ops_engineer"), "spoke to the vendor, they say the new boards have a sensor fault, known issue, will be fixed on their next visit")
    ht = w["plan"]["hotfix_t"]
    m(ht + rng.randrange(5, 30), "#eng-coldchain", H("ops_engineer"), f"pushed the hotfix: routed {oth}/{inc} low-temp alerts to #alerts-coldchain-old until the sensor fix lands")
    m(ht + rng.randrange(40, 90), "#eng-coldchain", H("warehouse_manager"), "thanks, the flapping in #alerts-coldchain was unbearable")
    ot = w["plan"]["override_t"]
    m(ot + rng.randrange(3, 15), "#eng-coldchain", H("sre_oncall"), "paged 6 times tonight by those low-temp warnings, pager reads the ledger not the channel. set ALERT_MIN_SEVERITY=critical in the override for tonight, will revert in the morning")
    m(ot + rng.randrange(8 * 60, 10 * 60), "#eng-coldchain", H("sre_oncall"), "reverted the override this morning, back to normal")
    at = w["plan"]["archive_t"]
    m(at, "#ops-floor", H("warehouse_manager"), "archived #alerts-coldchain-old, it was only the -40 noise anyway")
    # wedge photo (day 4 night), exif in the wrong timezone
    pt = c.receipt_wedge_t + 6 * 60 + rng.randrange(60, 180)
    c.photo_t = pt
    m(pt, "#ops-floor", H("temp_worker"), f"new toy for the airflow problem in room {inc} 😅 IMG_{2200 + rng.randrange(0, 99)}.jpg")
    m(pt + rng.randrange(20, 60), "#ops-floor", H("night_lead"), "don't leave that in the door mate")
    # night trips noticed? a stray remark
    m(ip["t0"] - rng.randrange(2 * 1440, 3 * 1440), "#ops-floor", H("night_lead"), f"{ctrl[inc]} compressor is clicking on and off again at night, sounds rough, told {c.name('warehouse_manager').split()[0]}")
    # benign lockout ticket chatter
    lk = [e for e in c.sim["lockouts"] if e[1] != inc]
    if lk:
        t = lk[0][0]
        m(t + rng.randrange(15, 60), "#ops-floor", H("receiving_clerk"), f"room {lk[0][1]} stopped cooling after the truck, panel says hold-off, is that normal?")
        m(t + rng.randrange(70, 140), "#ops-floor", H("warehouse_manager"), "runbook says it restarts on its own after the timer, keep the door shut")
    # stability lab
    lt = 13 * 1440 + 9 * 60 + rng.randrange(0, 60)
    m(lt, "#ops-floor", H("qa_manager"), f"customer stability lab flagged lot {c.lab_lot} (came out of room {inc}), asking which other lots were in that room during the excursion window")
    m(lt + rng.randrange(30, 90), "#ops-floor", H("warehouse_manager"), f"what excursion? room {inc} never alarmed")
    m(lt + rng.randrange(100, 200), "#eng-coldchain", H("ops_engineer"), f"ledger has {ctrl[inc]} at -40ish the whole week, dashboard never went above the high limit")
    m(lt + rng.randrange(6 * 60, 8 * 60), "#ops-floor", H("qa_manager"), "postmortem draft in the shared folder; quarantine list pulled from the ledger positions")
    # bot posts
    for t, ch, text in alert_posts:
        m(t, ch, "alerting-bot", text)
    msgs.sort(key=lambda x: x["t"])
    out = []
    for i, x in enumerate(msgs):
        out.append({"id": f"m{i + 1:04d}", "channel": x["channel"], "ts": iso(w, x["t"], c.offs["chat"]), "user": x["user"], "text": x["text"]})
    c.write("people/chat_export.json", json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    body = c.docs_written["people/chat_export.json"]
    c.claim("doc:chat_export", "people/chat_export.json", "reverted the override this morning, back to normal", "config:deploy/config.override.json:ALERT_MIN_SEVERITY")
    c.claim("doc:chat_export", "people/chat_export.json", "they say the new boards have a sensor fault, known issue", "code:gateway/kw7_decode.py:decode_line")
    return out


def tickets(c: Ctx):
    w, rng = c.world, c.rng
    inc, oth, ctrl = c.inc, c.other_flashed, w["zones"]["controller"]
    H, N = c.handle, c.name
    T = []
    n = [400 + rng.randrange(0, 30)]

    def tk(t_open, reporter, title, body, assignee=None, t_close=None, comments=(), tags=()):
        n[0] += rng.randrange(1, 4)
        T.append({"id": f"T-{n[0]:04d}", "created": iso(w, t_open, c.offs["tickets"]), "closed": iso(w, t_close, c.offs["tickets"]) if t_close else None,
                  "reporter": reporter, "assignee": assignee, "title": title, "body": body, "tags": list(tags),
                  "comments": [{"ts": iso(w, ct, c.offs["tickets"]), "user": cu, "text": ctext} for ct, cu, ctext in comments]})
        return T[-1]["id"]

    # historical
    tk(-200 * 1440, H("sre_oncall"), "socket timeouts unreliable on the gateway box", "urllib timeouts fire early/late on the gateway host after the kernel update; moving to deadline-based client.", H("sre_oncall"), -190 * 1440, tags=("gateway",))
    tk(-150 * 1440, H("night_lead"), f"{ctrl[inc]} link drops when room {inc} door is held fully open", f"When the room {inc} door is fully open (against the wall) the controller link goes down and comes back when it closes. Cable in the door-frame conduit is probably pinched. Happens with the dock trolley too.", H("ops_engineer"), None, comments=[(-149 * 1440, H("ops_engineer"), "reproduced. facilities quoted the conduit rework; deferred to the next maintenance window")], tags=("controllers", "facilities"))
    tk(-40 * 1440, H("warehouse_manager"), "HH-2 reads warm vs HH-1", "Clerk's handheld reads about a degree warmer than mine on the same room. Send both for calibration.", H("receiving_clerk"), -30 * 1440, comments=[(-31 * 1440, H("receiving_clerk"), "sent both, certificate in receipts")], tags=("probes",))
    # in-window
    ft = w["ledger"]["firmware_flash"][0]["t"]
    c.t_minus40_ticket = ft + rng.randrange(100, 200)
    tid40 = tk(c.t_minus40_ticket, H("warehouse_manager"), f"rooms {oth} and {inc} reading -40 after vendor visit", f"Dashboard shows both rooms at about -40 C since the technician left. Rooms are fine on the probe. Alerts flapping.", H("ops_engineer"), None,
               comments=[(ft + rng.randrange(300, 400), H("ops_engineer"), "vendor says sensor fault on the new boards; routing the low-temp warnings away for now"),
                         (w["plan"]["hotfix_t"] + 20, H("ops_engineer"), "hotfix deployed (routes.json). leaving open for the vendor fix")], tags=("alerts", "controllers"))
    c.ticket_minus40 = tid40
    lk = [e for e in c.sim["lockouts"] if e[1] != inc]
    if lk:
        t = lk[0][0]
        tk(t + rng.randrange(20, 90), H("receiving_clerk"), f"room {lk[0][1]} compressor stopped after unloading", "Panel showed hold-off after a long truck. Restarted by itself later.", H("warehouse_manager"), t + rng.randrange(400, 900), comments=[(t + rng.randrange(120, 300), H("warehouse_manager"), "per runbook, lockout timer. keep doors shut during unloads")], tags=("controllers",))
    lt = 13 * 1440 + 9 * 60
    c.ticket_lab = tk(lt, H("qa_manager"), f"stability lab: lot {c.lab_lot} degraded, excursion in room {inc}?", f"Customer lab reports degradation consistent with a warm excursion. Need every lot that was in room {inc} in the window. Ledger positions attached.", H("qa_manager"), None,
                      comments=[(lt + 300, H("vendor_tech"), f"fault snapshot pulled from {ctrl[inc]}, attached as text (controller/{ctrl[inc]}_fault_snapshot.txt)"),
                                (lt + 420, H("qa_manager"), "postmortem published; quarantine issued")], tags=("quality", "incident"))
    # red herrings
    rh = [
        (2 * 1440 + 9 * 60, H("forklift_op_2"), "FL-2 battery not holding charge", "Down to 30% by mid shift.", H("warehouse_manager"), 5 * 1440, ("equipment",)),
        (1 * 1440 + 11 * 60, H("warehouse_manager"), "room B corridor light flickering", "Fluorescent tube, corridor B.", None, 6 * 1440, ("facilities",)),
        (3 * 1440 + 15 * 60, H("ops_engineer"), "VPN drops every 4 hours", "IT ticket mirrored here.", None, 9 * 1440, ("it",)),
        (6 * 1440 + 8 * 60, H("receiving_clerk"), "pest control visit rescheduled", "Moved to next Tuesday.", None, 7 * 1440, ("facilities",)),
        (0 * 1440 + 10 * 60, H("qa_manager"), "customer complaint: late delivery", "Unrelated to storage; carrier issue.", None, 2 * 1440, ("customer",)),
        (5 * 1440 + 13 * 60, H("warehouse_manager"), "utility maintenance notice: 30 min outage next month", "Notice from the utility, generator test planned.", None, None, ("facilities",)),
        (8 * 1440 + 12 * 60, H("sre_oncall"), "disk 80% on the gateway box", "Old logs; rotated.", H("sre_oncall"), 8 * 1440 + 14 * 60, ("gateway",)),
        (4 * 1440 + 16 * 60, H("warehouse_manager"), f"speeding warning FL-1", "Telematics flagged 14 km/h in the corridor twice.", None, 4 * 1440 + 17 * 60, ("safety",)),
    ]
    for it in rh[:w["distortion"]["n_red_herrings"]]:
        tk(it[0], it[1], it[2], it[3], it[4], it[5], tags=it[6])
    T.sort(key=lambda x: x["created"])
    c.write("people/tickets.json", json.dumps(T, indent=1) + "\n")
    return T


def photos_and_recall(c: Ctx):
    w, rng = c.world, c.rng
    rows = [("IMG_2201.jpg", -6 * 1440 + 9 * 60, "Pixel 7", c.name("warehouse_manager"), "dock 2 after cleaning"),
            ("IMG_2207.jpg", 1 * 1440 + 10 * 60 + 12, "Pixel 7", c.name("warehouse_manager"), "damaged pallet wrap, receiving"),
            ("IMG_2214.jpg", 2 * 1440 + 15 * 60 + 3, "iPhone 13", c.name("forklift_op_2"), "FL-2 charger fault light"),
            ("IMG_2231.jpg", c.photo_t - rng.randrange(5, 40), "Galaxy A54", c.name("temp_worker"), f"door wedge under room {c.inc} door"),
            ("IMG_2233.jpg", c.photo_t + 1440 * 2 + 60, "Galaxy A54", c.name("temp_worker"), "break room radio"),
            ("IMG_2240.jpg", w["ledger"]["firmware_flash"][0]["t"] + 25, "iPhone 13", c.name("vendor_tech"), f"unit {w['zones']['controller'][c.other_flashed]} after update"),
            ("IMG_2241.jpg", w["ledger"]["firmware_flash"][1]["t"] + 12, "iPhone 13", c.name("vendor_tech"), f"unit {w['zones']['controller'][c.inc]} after update"),
            ("IMG_2250.jpg", 12 * 1440 + 11 * 60, "iPhone 13", c.name("vendor_tech"), f"fault snapshot dump {w['zones']['controller'][c.inc]}"),
            ("IMG_2252.jpg", 13 * 1440 + 14 * 60, "Pixel 7", c.name("qa_manager"), f"quarantine cage, lots from room {c.inc}")]
    # DateTimeOriginal carries the phone's clock (offset channel "exif"); the GPS stamp, present on the photos taken
    # outdoors/near the dock, is satellite time (UTC, correct) -- the offset is exactly recoverable from those rows
    gps_rows = {"IMG_2201.jpg", "IMG_2207.jpg", "IMG_2250.jpg"}
    with open(c.people / "photos_exif.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["filename", "DateTimeOriginal", "GPSDateStamp", "GPSTimeStamp", "camera", "owner", "caption"])
        for fn, t, cam, own, cap in rows:
            gps_d = iso(w, t)[:10] if fn in gps_rows else ""
            gps_t = iso(w, t)[11:19] if fn in gps_rows else ""
            wr.writerow([fn, iso(w, t, c.offs["exif"]).replace("T", " ").replace("Z", ""), gps_d, gps_t, cam, own, cap])
    c.write("people/recall_notice.txt", f"""PRODUCT SAFETY NOTICE  —  Compressor recall
Manufacturer: Nordkälte Kompressoren GmbH        Notice date: {dstr(w, -25 * 1440)}
Affected models: NK-450S and NK-450SX scroll compressors, serial range 7A0001–7A9999, manufactured 2024.
Issue: internal thermal protector may fail closed, allowing the compressor to overheat and stop without alarm.
Action: units in the affected range must be inspected; contact your service partner.
Site note ({c.name('warehouse_manager')}): our rooms use {w['names']['vendor_model']} controllers on NK-380 compressors (serials 5B…), which are NOT in the range; filed for reference.
""")
    c.write("people/hr_note.md", f"""# HR note (confidential)
{dstr(w, 4 * 1440 + 17 * 60)} — Verbal warning issued to {c.name('forklift_op_1')} for corridor speeding (telematics, two occurrences). No further action.
""")


def postmortem_and_lab(c: Ctx, db_lots_in_inc):
    w, rng = c.world, c.rng
    inc, ctrl = c.inc, w["zones"]["controller"]
    ip = c.inc_prop
    lab_t = 13 * 1440 + 9 * 60
    c.write("people/stability_lab_email.md", f"""From: stability-lab@{rng.choice(['helixpharma', 'novaterra-bio', 'quillstone'])}.example
To: quality@{c.info['subs']['DOMAIN']}
Date: {iso(w, lab_t)}
Subject: Lot {c.lab_lot} — potency loss consistent with thermal excursion

We received lot {c.lab_lot} from your site on {dstr(w, 11 * 1440)}. Accelerated stability shows a potency loss that we only see
after several hours above -15 C. Your shipping records show the lot was in cold room {inc} until dispatch. Please confirm
whether room {inc} experienced an excursion in the week before dispatch and list every lot that was in that room at the time.
""")
    wt = w["plan"]["archive_t"]
    lots_txt = "\n".join(f"- {l}" for l in db_lots_in_inc) if db_lots_in_inc else "- (none)"
    rel = "people/postmortem.md"
    c.write(rel, f"""# Postmortem: thermal excursion, cold room {inc}
Author: {c.name('qa_manager')} (QA)    Published: {dstr(w, 13 * 1440 + 16 * 60)}    Status: final

## Summary
On the night of {dstr(w, ip['t0'] - 300)} cold room {inc} experienced a thermal excursion that was not alarmed. A customer stability
lab detected the effect on lot {c.lab_lot} six days later.

## Root cause
Root cause: compressor failure on controller {ctrl[inc]}. The night lead had reported the compressor sounding rough in the
preceding days, and the vendor recall notice on file covers thermal-protector failures in scroll compressors of this generation.

## Contributing factors
- Alert routing for room {inc} had been moved to a legacy channel after a sensor fault on the new firmware boards (ticket {c.ticket_minus40}).
- The night billing rollup locks the ledger at 01:00, so readings around the onset are sparse.

## Timeline (badge system)
- {hhmm(w, ip['t0'] - 180, c.offs['badge'])} night shift on site ({c.name('night_lead')}, {c.name('temp_worker')}).
- {hhmm(w, ip['t0'] - 90, c.offs['badge'])} walk-through, all rooms closed.
- {hhmm(w, ip['t0'] + 30, c.offs['badge'])} (est.) compressor {ctrl[inc]} stops.
- {hhmm(w, ip['t1'] + 3, c.offs['badge'])} room {inc} door opened by the night lead on a routine check; nothing noted.
- {dstr(w, lab_t)} stability lab e-mail received.

## Affected product
Quarantined every lot the ledger shows in room {inc} during the window:
{lots_txt}

## Actions
- Vendor to replace the compressor on {ctrl[inc]} (open).
- Restore alert routing for rooms {c.other_flashed} and {inc} (done).
- Review of night-shift door procedures (open).
""")
    c.claim("doc:postmortem", rel, f"Root cause: compressor failure on controller {ctrl[inc]}", f"physical:door_prop:{inc}")
    c.claim("doc:postmortem", rel, f"room {inc} door opened by the night lead on a routine check; nothing noted", "event:door_close_incident")


def questions_json(c: Ctx, inst_placeholder="pending"):
    w = c.world
    ctrl = w["zones"]["controller"]
    schema = json.loads((ROOT / "contract" / "answer_schema.template.json").read_text())
    enums = {k: v["enum"] for k, v in schema["$defs"].items() if isinstance(v, dict) and "enum" in v}
    units = {}
    for z in c.zones:
        units[f"k_cool.{z}"] = {"unit": "degC/min", "meaning": "cooling rate while the compressor runs"}
        units[f"k_leak.{z}"] = {"unit": "1/min", "meaning": "heat-leak coefficient toward ambient (door closed)"}
        units[f"H.{z}"] = {"unit": "degC", "meaning": "hysteresis band width around the setpoint (compressor on at sp+H/2, off at sp-H/2, as seen by the controller)"}
        units[f"bias.{z}"] = {"unit": "degC", "meaning": "controller air-temperature sensor offset (reported minus true)"}
    units.update({"door_gain": {"unit": "ratio", "meaning": "heat-leak multiplier while a door is open"},
                  "c_adj": {"unit": "1/min", "meaning": "inter-zone coupling coefficient per adjacent room"},
                  "defrost.R_hours": {"unit": "hours", "meaning": "compressor runtime between defrosts"},
                  "defrost.len_min": {"unit": "min", "meaning": "defrost duration"},
                  "defrost.heat_degC": {"unit": "degC", "meaning": "total temperature rise injected by one defrost"},
                  "trip.d_min": {"unit": "min", "meaning": "door-open minutes with the compressor running until a trip"},
                  "lockout.N": {"unit": "count", "meaning": "trips within the window that cause a lockout"},
                  "lockout.W_min": {"unit": "min", "meaning": "trip-counting window"},
                  "lockout.L_min": {"unit": "min", "meaning": "lockout duration"}})
    q = {"instance": inst_placeholder, "zones": c.zones, "controllers": ctrl, "site": w["names"]["site_code"], "company": w["names"]["company"],
         "controller_model": w["names"]["vendor_model"], "evidence_window": {"start": iso(w, 0), "end": iso(w, w["sim"]["days"] * 1440)},
         "mechanism_params": units, "heldout_path": f"controller/{ctrl[c.inc]}_fault_snapshot.txt",
         "id_grammar": json.load(open(ROOT / "contract" / "stub_instance" / "evidence" / "questions.json"))["id_grammar"],
         "enums": enums, "channels": enums["CHANNELS"],
         "notes": ["Actor handles are the chat/ticket usernames; they are not listed here.",
                   "Node ids in causal_chain must follow id_grammar exactly (e.g. commit:<sha7> from the repo history, code:<relpath>:<function>, config:<relpath>:<dotted.key>, physical:<type>:<zone>, data:<type>:<zone>, doc:<file-stem>, firmware:<zone>).",
                   "timeline.events use TRUE time (UTC), not the clock of the record you read it from; clock_offsets_min[channel] = (channel clock) - (true time) in minutes.",
                   "notation.glossary maps each root word to a NOTATION_LABEL; digits and roots the shipped decoder already knows are not scored.",
                   "notation.heldout: one entry per line of the fault snapshot, keyed by the frame's seq; event = label of the clause head (AIR_TEMP, DOOR, TRIP, ...), value in engineering units (degC, bar) when the clause has one.",
                   "false_claims: quote the exact text (>= 8 chars) of a statement in a human document that the evidence shows to be false."]}
    c.write("questions.json", json.dumps(q, indent=1) + "\n")


def render(build, world, sim, nt, info, report, ev, log):
    c = Ctx(build, world, sim, nt, info, report, ev, log)
    rng = c.rng
    # lots physically in the incident zone during the excursion (true); and per the DB (wrong)
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
    # DB positions at the end of the run (what the postmortem used)
    db_pos = {}
    for line in open(build / "ledger.sql"):
        m = re.match(r"INSERT INTO \"?lots\"? VALUES\('([^']+)','[^']*','[^']*','([A-Z])'", line)
        if m:
            db_pos[m.group(1)] = m.group(2)
    db_moves = []
    for line in open(build / "ledger.sql"):
        m = re.match(r"INSERT INTO \"?moves\"? VALUES\(\d+,'?([^',]*)'?,'([^']+)','?([^',]*)'?,'([A-Z])','?([^',]*)'?,'([^']+)'", line)
        if m:
            db_moves.append((m.group(6), m.group(2), m.group(3), m.group(4)))
    # lots the DB shows in the incident zone at the window end (approximation of the postmortem's query: current position)
    db_in_inc = sorted(l for l, z in db_pos.items() if z == c.inc)
    c.db_lots_in_inc = db_in_inc
    c.db_pos = db_pos
    # alert bot posts from the alerting log
    posts = []
    apath = ev / "deploy" / "logs" / "alerting.log"
    if apath.exists():
        for line in open(apath):
            m = re.match(r"(\S+) INFO alerting POST (#\S+): (.*)", line)
            if m:
                t = (seedmod.dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ") - seedmod.dt.datetime.strptime(world["sim"]["start_iso"], "%Y-%m-%dT%H:%M:%SZ")).total_seconds() / 60
                posts.append((t, m.group(2), m.group(3)))
    log(f"docs: true lots in {c.inc} during window={len(c.true_lots_in_inc)} db lots={len(db_in_inc)} alert posts={len(posts)}")
    bi = badge_csv(c)
    forklift_csv(c)
    probe_sheet_csv(c)
    cctv_csv(c)
    submeter_csv(c)
    receipts(c)
    vendor_reports(c)
    statements(c)
    tickets(c)
    chat_export(c, posts)
    photos_and_recall(c)
    postmortem_and_lab(c, db_in_inc)
    questions_json(c)
    (ev / "TASK.md").write_text((ROOT / "contract" / "stub_instance" / "evidence" / "TASK.md").read_text())
    meta = {"false_claims": c.false_claims, "mislabels": c.mislabels, "true_lots_in_inc": c.true_lots_in_inc, "db_lots_in_inc": db_in_inc,
            "db_pos": db_pos, "lab_lot": c.lab_lot, "photo_t": c.photo_t, "receipt_wedge_t": c.receipt_wedge_t, "ticket_minus40": c.ticket_minus40,
            "ticket_lab": c.ticket_lab, "t_minus40_ticket": c.t_minus40_ticket, "vendor_wrong_gloss": c.vendor_wrong_gloss, "badge_holders": bi["holders"]}
    json.dump(meta, open(build / "docs_meta.json", "w"), indent=1)
    return meta
