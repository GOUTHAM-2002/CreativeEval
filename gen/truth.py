# Ground truth for one instance: scored facts, tolerances, evidence index, canaries.
from __future__ import annotations
import json
import re
from pathlib import Path

from gen import seed as seedmod

TOL = {"k_cool": (0.006, 0.10), "k_leak": (0.00025, 0.15), "H": (0.25, 0.12), "bias": (0.3, 0.0), "door_gain": (1.0, 0.20),
       "c_adj": (0.0003, 0.35), "defrost.R_hours": (0.5, 0.0), "defrost.len_min": (2, 0.0), "defrost.heat_degC": (0.6, 0.0),
       "trip.d_min": (0.5, 0.0), "lockout.N": (0, 0.0), "lockout.W_min": (5, 0.0), "lockout.L_min": (5, 0.0)}
UNITS = {"k_cool": "degC/min", "k_leak": "1/min", "H": "degC", "bias": "degC", "door_gain": "ratio", "c_adj": "1/min",
         "defrost.R_hours": "hours", "defrost.len_min": "min", "defrost.heat_degC": "degC", "trip.d_min": "min",
         "lockout.N": "count", "lockout.W_min": "min", "lockout.L_min": "min"}
EVENT_HEAD = {"DOOR_OPEN": "DOOR", "DOOR_CLOSE": "DOOR", "TRIP": "TRIP", "LOCKOUT_ENTER": "LOCKOUT", "LOCKOUT_EXIT": "LOCKOUT",
              "DEFROST_ENTER": "DEFROST", "DEFROST_EXIT": "DEFROST", "HEATER_ON": "HEATER", "HEATER_OFF": "HEATER",
              "BOOT": "FIRMWARE", "SETPOINT_SET": "SETPOINT", "QUEUE_OVERFLOW": "QUEUE"}


def iso(world, t):
    return seedmod.world_iso(world, int(round(t)))


def mechanism_block(world):
    p = world["params"]
    params = {}
    for name in ("k_cool", "k_leak", "H", "bias"):
        for z, v in p[name].items():
            a, r = TOL[name]
            params[f"{name}.{z}"] = {"value": v, "abs_tol": a, "rel_tol": r, "unit": UNITS[name]}
    scalars = {"door_gain": p["door_gain"], "c_adj": p["c_adj"], "defrost.R_hours": p["defrost"]["R_hours"], "defrost.len_min": p["defrost"]["len_min"],
               "defrost.heat_degC": p["defrost"]["heat_degC"], "trip.d_min": p["trip"]["d_min"], "lockout.N": p["lockout"]["N"],
               "lockout.W_min": p["lockout"]["W_min"], "lockout.L_min": p["lockout"]["L_min"]}
    for k, v in scalars.items():
        a, r = TOL[k]
        params[k] = {"value": v, "abs_tol": a, "rel_tol": r, "unit": UNITS[k]}
    return {"params": params, "rules": {"defrost_rule_type": "runtime_hours", "stagger_order": p["stagger_order"],
                                        "adjacency_pairs": [list(x) for x in p["adjacency"]]}}


def notation_block(world, sim, nt, ev):
    t = nt.truth()
    inc = world["zones"]["incident_zone"]
    ctrl = world["zones"]["controller"][inc]
    snap = ev / "controller" / f"{ctrl}_fault_snapshot.txt"
    by_seq = {}
    for fr in sim["frames"]:
        if fr["zone"] == inc:
            by_seq.setdefault(fr["seq"], []).append(fr)
    heldout = []
    if snap.exists():
        for line in snap.read_text().splitlines():
            if line.startswith("#") or not line.strip():
                continue
            raw = line.split(" ", 1)[1]
            d = nt.decode(raw, setpoint=None)
            cands = by_seq.get(d["seq"], [])
            fr = cands[-1] if cands else None
            if fr is None:
                continue
            c0 = fr["clauses"][0]
            if c0["kind"] == "READ":
                event, value = c0["sensor"], c0["value"]
            elif c0["kind"] == "STATE":
                event, value = c0["state"], None
            else:
                event, value = EVENT_HEAD[c0["event"]], (c0.get("value") if c0["event"] in ("SETPOINT_SET", "QUEUE_OVERFLOW") else None)
            heldout.append({"seq": d["seq"], "ts": iso(world, fr["t_min"]), "zone": inc, "event": event, "value": value,
                            "tol_value": 0.2, "tol_s": 120})
    gw_text = (ev / "deploy" / "logs" / "gateway.log").read_text(errors="replace") if (ev / "deploy" / "logs" / "gateway.log").exists() else ""
    snap_text = snap.read_text() if snap.exists() else ""
    unscored = sorted(r for r, lab in t["glossary"].items()
                      if r not in t["known_roots"] and not lab.startswith("DIGIT") and (gw_text.count(r) + snap_text.count(r)) < 2)
    epochs = {}
    for z, eps in sim["clock_epochs"].items():
        epochs[world["zones"]["controller"][z]] = [{"from": iso(world, a), "epoch": iso(world, b)} for a, b in eps]
    return {"base": t["base"], "digit_glyphs": t["digit_glyphs"], "clause_order": t["clause_order"], "glossary": t["glossary"],
            "known_roots": t["known_roots"], "unscored_roots": unscored, "affixes": t["affixes"], "v34_change": t["v34_change"], "legacy_roots": t.get("legacy_roots", {}),
            "controller_clock_epochs": epochs, "heldout": heldout}


def causal_block(world, sim, report, meta, win):
    inc = world["zones"]["incident_zone"]
    hot = next((c for c in report["commits"] if c["message"].startswith("hotfix")), None)
    dec = next((c for c in report["commits"] if c["message"].startswith("billing")), None)
    adj = [b if a == inc else a for a, b in world["params"]["adjacency"] if inc in (a, b)]
    nb_defrost = [z for z in adj if any(sim["state"][z][t] == "DEFROST" for t in range(win[0], win[1]))]
    n = {
        "prop": f"physical:door_prop:{inc}", "trip": f"physical:trip:{inc}", "lock": f"physical:lockout:{inc}", "exc": f"physical:excursion:{inc}",
        "fw": f"firmware:{inc}", "dec": "code:gateway/rh7_decode.py:decode_line", "rw": f"data:readings_wrong:{inc}",
        "sup": f"data:alerts_suppressed:{inc}", "hot": f"commit:{hot['sha7']}" if hot else "commit:unknown",
        "route": f"config:alerting/routes.json:zones.{inc}.channel", "ovr": "config:deploy/config.override.json:ALERT_MIN_SEVERITY",
        "drop": f"data:frames_dropped:{inc}", "apply": "code:dispatch/server.py:apply_move", "notify": "code:gateway/server.py:notify_dispatch",
        "lots": f"data:lots_wrong:{inc}", "quar": f"data:quarantine_wrong:{inc}",
    }
    cat = {n["prop"]: "human_action", n["trip"]: "physical", n["lock"]: "physical", n["exc"]: "physical", n["fw"]: "firmware",
           n["dec"]: "data_format", n["rw"]: "data_format", n["sup"]: "config_drift", n["hot"]: "config_drift", n["route"]: "config_drift",
           n["ovr"]: "config_drift", n["drop"]: "physical", n["apply"]: "race_condition", n["notify"]: "race_condition",
           n["lots"]: "race_condition", n["quar"]: "human_action"}
    edges = [(n["prop"], n["trip"]), (n["trip"], n["lock"]), (n["lock"], n["exc"]), (n["prop"], n["exc"]),
             (n["fw"], n["rw"]), (n["dec"], n["rw"]), (n["rw"], n["sup"]), (n["hot"], n["route"]), (n["route"], n["sup"]),
             (n["ovr"], n["sup"]), (n["prop"], n["drop"]), (n["drop"], n["sup"]),
             (n["apply"], n["lots"]), (n["notify"], n["lots"]), (n["lots"], n["quar"])]
    for z in nb_defrost:
        node = f"physical:defrost:{z}"
        cat[node] = "physical"
        edges.append((node, n["exc"]))
    nodes = list(cat.keys())
    roots = [x for x in nodes if not any(b == x for a, b in edges)]
    decoys = [f"physical:compressor_fault:{inc}", "doc:recall_notice", "code:billing/nightly.py:run_once", f"physical:sensor_fault:{inc}"]
    if dec:
        decoys.append(f"commit:{dec['sha7']}")
    return {"nodes": nodes, "edges": [list(e) for e in edges], "roots": roots, "decoys": decoys, "node_categories": cat,
            "affected_lots": [f"lot:{l}" for l in meta["true_lots_in_inc"]],
            "excursion": {"zone": inc, "start": iso(world, win[0]), "end": iso(world, win[1]), "tol_s": 900},
            "db_lots_in_inc": [f"lot:{l}" for l in meta["db_lots_in_inc"]]}


def timeline_block(world, report, meta):
    A = world["actors"]
    H = lambda r: f"actor:{A[r]['handle']}"
    inc = world["zones"]["incident_zone"]
    ip = [d for d in world["ledger"]["props"] if d.get("incident")][0]
    plan = world["plan"]
    hot = next((c for c in report["commits"] if c["message"].startswith("hotfix")), None)
    dec = next((c for c in report["commits"] if c["message"].startswith("billing")), None)
    ff = world["ledger"]["firmware_flash"]
    ev = []

    def add(eid, role, action, t, tol, ref=""):
        ev.append({"event_id": f"event:{eid}", "actor": H(role), "action": action, "t": iso(world, t), "tol_s": tol, "ref": ref})

    add("flash_incident_zone", "vendor_tech", "firmware_flash", ff[0]["t"], 900, f"firmware:{ff[0]['zone']}")
    add("flash_other_zone", "vendor_tech", "firmware_flash", ff[1]["t"], 900, f"firmware:{ff[1]['zone']}")
    add("ticket_minus40", "warehouse_manager", "ticket_open", meta["t_minus40_ticket"], 300, f"ticket:{meta['ticket_minus40']}")
    if hot:
        add("hotfix_commit", "ops_engineer", "commit", plan["hotfix_t"], 300, f"commit:{hot['sha7']}")
    if dec and plan.get("decoy_commit_t") is not None:
        add("billing_commit", "ops_engineer", "commit", plan["decoy_commit_t"], 300, f"commit:{dec['sha7']}")
    add("override_deploy", "sre_oncall", "override_deploy", plan["override_t"], 300, "config:deploy/config.override.json:ALERT_MIN_SEVERITY")
    add("archive_channel", "warehouse_manager", "archive_channel", plan["archive_t"], 3600, "")
    add("purchase_wedge", "temp_worker", "purchase", meta["receipt_wedge_t"], 3600, "doc:hardware_receipt_wedge")
    add("photo_wedge", "temp_worker", "photo", meta["photo_t"], 3600, "doc:photos_exif")
    shift = [b for b in world["ledger"]["badge"] if b["actor"] == A["temp_worker"]["handle"] and b["kind"] == "shift_start" and 0 < ip["t0"] - b["t"] < 600]
    if shift:
        add("shift_start_temp_incident_night", "temp_worker", "shift_start", shift[-1]["t"], 300, "")
    for i, d in enumerate([x for x in world["ledger"]["props"] if not x.get("incident")][:3]):
        add(f"door_prop_earlier_{i + 1}", "temp_worker", "door_prop", d["t0"], 300, f"zone:{inc}")
    add("door_prop_incident", "temp_worker", "door_prop", ip["t0"], 300, f"zone:{inc}")
    add("door_close_incident", "night_lead", "door_close", ip["t1"], 300, f"zone:{inc}")
    add("lab_ticket", "qa_manager", "ticket_open", 13 * 1440 + 9 * 60, 300, f"ticket:{meta['ticket_lab']}")
    add("quarantine", "qa_manager", "quarantine", 13 * 1440 + 9 * 60 + 420, 3600, "")
    add("postmortem_publish", "qa_manager", "postmortem_publish", 13 * 1440 + 16 * 60, 3600, "doc:postmortem")
    return {"events": ev, "clock_offsets_min": world["distortion"]["clock_offsets_min"], "false_claims": meta["false_claims"]}


def evidence_index(world, causal, timeline, notation, ev):
    inc = world["zones"]["incident_zone"]
    ctrl = world["zones"]["controller"][inc]
    snap = f"controller/{ctrl}_fault_snapshot.txt"
    A = world["actors"]
    st = lambda role: f"people/statements/{role}_{A[role]['handle']}.md"
    idx = {}
    gw, led, sub, probe = "deploy/logs/gateway.log", "db/ledger.sql", "people/utility_submeter.csv", "people/probe_checks_sheet.csv"
    for pid in notation and []:
        pass
    for z in world["zones"]["order"]:
        idx[f"k_cool.{z}"] = [gw, led, sub]
        idx[f"k_leak.{z}"] = [gw, led, sub]
        idx[f"H.{z}"] = [gw, led]
        idx[f"bias.{z}"] = [gw, probe, "people/receipts/calibration_certificate_handhelds.txt"]
    idx.update({"door_gain": [gw, "people/badge_access.csv", "people/forklift_telematics.csv"],
                "c_adj": [gw, sub, "repo/docs/floor_plan.md"],
                "defrost.R_hours": [gw, sub], "defrost.len_min": [gw, sub], "defrost.heat_degC": [gw, sub],
                "trip.d_min": [gw, snap, "people/forklift_telematics.csv"], "lockout.N": [gw, snap, "people/forklift_telematics.csv"],
                "lockout.W_min": [gw, snap], "lockout.L_min": [gw, snap, sub]})
    for root, lab in notation["glossary"].items():
        if root in notation["known_roots"] or lab.startswith("DIGIT"):
            continue
        idx[root] = [gw, snap, "people/vendor_service_reports/bench_report_unit01.md"]
    n = {x: x for x in causal["nodes"]}
    files = {
        f"physical:door_prop:{inc}": ["people/receipts/hardware_receipt_wedge.txt", "people/photos_exif.csv", "people/cctv_motion.csv", gw, "people/chat_export.json"],
        f"physical:trip:{inc}": [gw, snap], f"physical:lockout:{inc}": [gw, snap, sub],
        f"physical:excursion:{inc}": [snap, "people/stability_lab_email.md", sub],
        f"firmware:{inc}": ["people/vendor_service_reports/service_report_firmware_visit.md", "people/badge_access.csv", gw, "people/receipts/vendor_invoice_firmware_service.txt", "people/photos_exif.csv"],
        "code:gateway/rh7_decode.py:decode_line": ["repo/gateway/rh7_decode.py", gw, probe],
        f"data:readings_wrong:{inc}": [gw, led, probe], f"data:alerts_suppressed:{inc}": ["deploy/logs/alerting.log", "repo/alerting/routes.json", "repo/deploy/config.override.json"],
        f"config:alerting/routes.json:zones.{inc}.channel": ["repo/alerting/routes.json", "deploy/logs/alerting.log", "people/chat_export.json"],
        "config:deploy/config.override.json:ALERT_MIN_SEVERITY": ["repo/deploy/config.override.json", "deploy/logs/alerting.log", "people/chat_export.json"],
        f"data:frames_dropped:{inc}": [gw, snap, "people/tickets.json"],
        "code:dispatch/server.py:apply_move": ["repo/dispatch/server.py", "deploy/logs/dispatch.log"],
        "code:gateway/server.py:notify_dispatch": ["repo/gateway/server.py", gw, "deploy/logs/dispatch.log"],
        f"data:lots_wrong:{inc}": [led, "people/forklift_telematics.csv", gw, "deploy/logs/dispatch.log"],
        f"data:quarantine_wrong:{inc}": ["people/postmortem.md", led, "people/forklift_telematics.csv"],
    }
    for node in causal["nodes"]:
        if node.startswith("commit:"):
            idx[node] = ["repo/.git", "deploy/logs/alerting.log", "people/chat_export.json"]
        elif node.startswith("physical:defrost:"):
            idx[node] = [gw, sub]
        else:
            idx[node] = files.get(node, [gw])
    for a, b in causal["edges"]:
        idx[f"{a}->{b}"] = sorted(set(idx.get(a, [])[:2] + idx.get(b, [])[:2]))
    ev_files = {"flash": ["people/badge_access.csv", gw, "people/vendor_service_reports/service_report_firmware_visit.md"],
                "ticket": ["people/tickets.json", "people/chat_export.json"], "commit": ["repo/.git", "people/chat_export.json"],
                "override": ["repo/deploy/config.override.json", "people/chat_export.json", "deploy/logs/alerting.log"],
                "archive": ["people/chat_export.json", st("warehouse_manager")], "purchase": ["people/receipts/hardware_receipt_wedge.txt", "people/chat_export.json"],
                "photo": ["people/photos_exif.csv", "people/chat_export.json"], "shift": ["people/badge_access.csv", "people/chat_export.json"],
                "door_prop": [gw, "people/cctv_motion.csv", snap], "door_close": ["people/badge_access.csv", "people/cctv_motion.csv", gw],
                "lab": ["people/tickets.json", "people/stability_lab_email.md"], "quarantine": ["people/tickets.json", "people/postmortem.md"],
                "postmortem": ["people/postmortem.md", "people/chat_export.json"]}
    for e in timeline["events"]:
        key = next((k for k in ev_files if k in e["event_id"]), "commit")
        idx[e["event_id"]] = ev_files[key]
    claim_files = {"event:door_prop_incident": [gw, "people/cctv_motion.csv", "people/receipts/hardware_receipt_wedge.txt"],
                   "event:door_close_incident": ["people/badge_access.csv", "people/cctv_motion.csv", gw],
                   "event:archive_channel": ["people/chat_export.json", "deploy/logs/alerting.log"],
                   "code:gateway/rh7_decode.py:decode_line": ["repo/gateway/rh7_decode.py", probe, "people/vendor_service_reports/service_report_firmware_visit.md"],
                   "config:deploy/config.override.json:ALERT_MIN_SEVERITY": ["repo/deploy/config.override.json", "deploy/logs/alerting.log"],
                   "bias": ["people/receipts/calibration_certificate_handhelds.txt", probe, "people/tickets.json"],
                   f"firmware:{inc}": ["people/badge_access.csv", gw, "people/receipts/vendor_invoice_firmware_service.txt"],
                   f"physical:door_prop:{inc}": ["people/receipts/hardware_receipt_wedge.txt", "people/cctv_motion.csv", gw]}
    for fc in timeline["false_claims"]:
        idx[fc["claim_id"]] = claim_files.get(fc["truth_ref"], [gw, "people/chat_export.json"])
    return idx


def build(build, world, sim, nt, info, report, ev, log):
    meta = json.load(open(build / "docs_meta.json"))
    win = sim["checks"]["incident_window"]
    mech = mechanism_block(world)
    nota = notation_block(world, sim, nt, ev)
    causal = causal_block(world, sim, report, meta, win)
    tl = timeline_block(world, report, meta)
    idx = evidence_index(world, causal, tl, nota, ev)
    canaries = ["eval_imp", "frostline_gen", "mechanism.py", "docs_gen", "repo_gen", "assemble.py", "truth.json", "world.json", "sub_seed",
                f"seed={world['seed']}", "faketime", "FAKETIME", "libfaketime", "/build/", "/home/goutham", "claude",
                "docs_meta", "sim_series", "driver_report", "incident_zone", "red_herring", "canar"]
    truth = {"instance": "pending", "seed": world["seed"], "tier": world["tier"], "mechanism": mech, "notation": nota, "causal": causal,
             "timeline": tl, "evidence_index": idx, "canaries": canaries,
             "build": {"sub_seed": world.get("sub_seed"), "incident_window_min": list(win), "checks": sim["checks"], "driver": {k: report[k] for k in ("sent", "unacked", "dropped_radio", "unsent_linkdown", "late_max_s", "moves_posted", "probes_posted", "snapshot")},
                       "lots_wrong": sorted(set(meta["db_lots_in_inc"]) ^ set(meta["true_lots_in_inc"])), "mislabels": meta["mislabels"]}}
    log(f"truth: params={len(mech['params'])} unknown_roots={sum(1 for r in nota['glossary'] if r not in nota['known_roots'] and not nota['glossary'][r].startswith('DIGIT'))} unscored={len(nota['unscored_roots'])} heldout={len(nota['heldout'])} nodes={len(causal['nodes'])} edges={len(causal['edges'])} events={len(tl['events'])} claims={len(tl['false_claims'])} lots_wrong={len(truth['build']['lots_wrong'])}")
    return truth


# ---------------------------------------------------------------- v2: facts (determinable / undeterminable / ill-posed)
def facts_block(world, sim, report, meta, win, causal, tl):
    A = world["actors"]
    H = lambda r: f"actor:{A[r]['handle']}"
    inc = world["zones"]["incident_zone"]
    ctrl = world["zones"]["controller"]
    ip = [d for d in world["ledger"]["props"] if d.get("incident")][0]
    plan = world["plan"]
    hot = next((c for c in report["commits"] if c["message"].startswith("hotfix")), None)
    ff = world["ledger"]["firmware_flash"]
    drift = world["ledger"]["sensor_drift"]
    po = plan["power_outage"]
    df, bro, fo = plan["diskfull"], plan["badge_reader_outage"], plan["fl2_outage"]
    gw, snap = "deploy/logs/gateway.log", f"controller/{ctrl[inc]}_fault_snapshot.txt"
    claims = {c["claim_id"]: c for c in meta["false_claims"]}
    def trap(cid, text=None):
        c = claims.get(cid)
        return [{"doc_id": c["doc_id"], "text": c["text"], "claim_id": cid}] if c else []
    F = []
    def det(fid, topic, q, ans, ev, tol=None, traps=()):
        F.append({"id": fid, "topic": topic, "kind": "determinable", "question": q, "answer": ans, **({"tol": tol, "tol_unit": "minutes"} if tol else {}),
                  "evidence_for": ev, "trap_claims": list(traps)})
    def undet(fid, topic, q, hyps, supported, why, ev_for, ev_missing, traps=()):
        F.append({"id": fid, "topic": topic, "kind": "undeterminable", "question": q, "answer": None, "hypotheses": hyps,
                  "supported": supported, "why_undeterminable": why, "evidence_for": ev_for, "evidence_missing": ev_missing, "trap_claims": list(traps)})
    def ill(fid, topic, q, reframing, ev, traps=()):
        F.append({"id": fid, "topic": topic, "kind": "ill_posed", "question": q, "answer": reframing, "evidence_for": ev, "trap_claims": list(traps)})
    # --- determinable
    det("F01", "door_propped", f"Was the room {inc} door held open on the incident night?", "yes: held fully open for several hours (controller link drops whenever that door is fully open; trips and a lockout follow in the fault snapshot; a rubber wedge was bought and photographed under that door two weeks earlier)", [gw, snap, "people/receipts/hardware_receipt_wedge.txt", "people/tickets.json"], traps=trap("fc01"))
    det("F02", "prop_start", "When did the door go fully open (true UTC)?", iso(world, ip["t0"]), [gw, snap], tol=6)
    det("F03", "prop_end", "When was the door closed (true UTC)?", iso(world, ip["t1"]), [gw, "db/ledger.sql", "db/queue.sql"], tol=6)
    lock = next((e for e in sim["lockouts"] if e[1] == inc and ip["t0"] <= e[0] <= ip["t1"] + 60), None)
    if lock:
        det("F04", "lockout", f"Did controller {ctrl[inc]} lock out that night, and when?", f"yes, at {iso(world, lock[0])}", [snap, gw], tol=10)
    det("F05", "excursion_occurred", f"Did room {inc} exceed its product limit?", f"yes, from about {iso(world, win[0])} until about {iso(world, win[1])} (recovery curve after the link returned; lab result)", [gw, "people/stability_lab_email.md", "people/utility_submeter.csv"], tol=45)
    det("F06", "flash_incident_zone", f"Was unit {ctrl[inc]} flashed to firmware 3.4 during the vendor visit?", f"yes, on {iso(world, ff[0]['t'])}: its readings decode about {abs(world['zones']['setpoint'][inc]):.0f} C lower from then on, the invoice bills two units, and the technician's badge opened room {inc}", [gw, "people/receipts/vendor_invoice_firmware_service.txt", "people/badge_access.csv", "people/photos_exif.csv"], traps=trap("fc05"))
    det("F07", "flash_other_zone", f"Which other unit was flashed?", f"{ctrl[ff[1]['zone']]} (room {ff[1]['zone']}) at {iso(world, ff[1]['t'])}", [gw, "people/vendor_service_reports/service_report_firmware_visit.md"], tol=30)
    det("F08", "decoder_defect", "Why did the flashed rooms read about -40 C?", f"the gateway decoder assumes the firmware-3.2 delta encoding; firmware 3.4 sends absolute temperatures (flagged in the status word), so the decoded value equals true temperature plus the setpoint", ["repo/gateway/rh7_decode.py", gw, "people/probe_checks_sheet.csv"], traps=trap("fc03"))
    det("F09", "not_sensor_fault", "Were the -40 readings a sensor fault?", "no: handheld probe checks on those rooms agree with the true temperatures; the raw frames decode correctly under the 3.4 format", ["people/probe_checks_sheet.csv", gw, "people/vendor_service_reports/service_report_firmware_visit.md"], traps=trap("fc03"))
    if hot:
        det("F10", "hotfix_routing", "What did the hotfix commit change?", f"commit {hot['sha7']} routed rooms {ff[1]['zone']}/{inc} low-temperature alerts to #alerts-coldchain-old, a channel the manager then archived", ["repo/.git", "deploy/logs/alerting.log", "people/chat_export.json"])
    det("F11", "archive_timing", "When was #alerts-coldchain-old archived relative to the incident?", f"before it, on {iso(world, plan['archive_t'])}", ["people/chat_export.json", "deploy/logs/alerting.log"], tol=120, traps=trap("fc02"))
    det("F12", "override_active", "Was a minimum-severity override active during the incident?", f"yes: deploy/config.override.json sets ALERT_MIN_SEVERITY=critical; the alerting log shows warnings suppressed from {iso(world, plan['override_t'])} onward and it is still present in the deployed tree", ["repo/deploy/config.override.json", "deploy/logs/alerting.log", "people/chat_export.json"], tol=15)
    det("F13", "override_not_reverted", "Was the override reverted?", "no: the file is still in the deployed tree and suppression continues to the end of the logs", ["repo/deploy/config.override.json", "deploy/logs/alerting.log"])
    det("F14", "compressor_not_faulty", f"Did the {ctrl[inc]} compressor fail?", "no: it cooled normally before and after the lockout; the lockout is the controller's trip-count rule; the recall notice covers a different compressor model", [snap, gw, "people/recall_notice.txt"], traps=trap("fc06"))
    det("F15", "race_bug", "Why does the ledger disagree with physical pallet positions?", "the gateway retries the dispatch webhook after a timeout and dispatch applies moves without checking the current position, so a delayed duplicate of an earlier move overwrites a later move (dispatch log 'zone mismatch' warnings)", ["deploy/logs/dispatch.log", "repo/dispatch/server.py", "repo/gateway/server.py", "people/forklift_telematics.csv"])
    det("F16", "affected_lots_determinable", f"Which lots were physically in room {inc} during the excursion (those the surviving records establish)?", ", ".join(causal["affected_lots_determinable"]) or "(none)", ["people/forklift_telematics.csv", gw, "repo/deploy/inventory_import.csv"])
    det("F17", "quarantine_wrong", "Was the quarantine list correct?", f"no: it was taken from the corrupted ledger; it includes lots that were not in the room and omits some that were", ["people/postmortem.md", "db/ledger.sql", "people/forklift_telematics.csv"])
    det("F18", "sensor_drift", f"What happened to the room {drift['zone']} sensor?", f"its reading drifted upward by about {abs(drift['rate_per_min'] * (drift['t1'] - drift['t0'])):.1f} C between {iso(world, drift['t0'])[:10]} and {iso(world, drift['t1'])[:10]} (handheld checks diverge from the panel), and was recalibrated on {iso(world, plan['recal_t'])[:10]}", ["people/probe_checks_sheet.csv", gw, "people/vendor_service_reports/service_report_recalibration.md"])
    det("F19", "power_outage", "What happened during the generator test?", f"site power was off from {iso(world, po['t0'])} to {iso(world, po['t1'])}: every controller rebooted (sequence and clock reset), the gateway host rebooted and its logs rotated", [gw, "deploy/logs/gateway.log.1", "people/tickets.json", "people/utility_notice.txt"], tol=5)
    det("F20", "log_gap", "Why are there no service logs for a window after the incident?", f"the gateway host disk was full from {iso(world, df['t0'])} to {iso(world, df['t1'])}; services kept running (the ledger database has readings for the window) but nothing was appended to the log files", ["people/tickets.json", "db/ledger.sql", gw], tol=20)
    det("F21", "badge_reader_offline", f"Why are there no badge records for the room {inc} reader that week?", f"the reader was offline from {iso(world, bro['t0'])[:10]} to {iso(world, bro['t1'])[:10]} (facilities ticket); doors were opened with the key", ["people/tickets.json", "people/badge_access.csv"])
    det("F22", "fl2_offline", "Why does the forklift telematics have a gap for FL-2?", f"its telematics battery failed; no trail from {iso(world, fo['t0'])[:10]} to {iso(world, fo['t1'])[:10]} although the scanner kept posting moves", ["people/tickets.json", "people/forklift_telematics.csv", gw])
    det("F23", "defrost_rule", "How are defrosts scheduled?", "by compressor runtime (about every R runtime-hours, inside fixed daily windows, one room at a time in a fixed priority order), not every 6 hours as the runbook says", [gw, "people/utility_submeter.csv", "repo/docs/runbook.md"])
    det("F24", "hh2_bias", "Is the clerk's handheld accurate?", f"no: HH-2 reads +{world['handheld'][A['receiving_clerk']['handle']][1]:.1f} C high per the calibration certificate, so the clerk's sheet overstates", ["people/receipts/calibration_certificate_handhelds.txt", "people/probe_checks_sheet.csv"], traps=trap("fc04"))
    det("F25", "earlier_props", f"Was the room {inc} door held open on earlier nights?", f"yes: the controller link dropped on {len([d for d in world['ledger']['props'] if not d.get('incident')])} earlier nights during the night shift, each with trips in the snapshot-style pattern", [gw, "people/badge_access.csv"])
    det("F26", "wedge_purchase", "Who bought the door wedge and when?", f"{A['temp_worker']['name']} on {iso(world, meta['receipt_wedge_t'])[:10]} (receipt submitted for reimbursement; photo posted in chat the same night)", ["people/receipts/hardware_receipt_wedge.txt", "people/chat_export.json", "people/photos_exif.csv"])
    det("F27", "nightlead_claim_false", "Is the night lead's statement that nobody went near the room after the walk-through true?", "no: the link drop, trips and lockout show the door was fully open for hours after it", [gw, snap], traps=trap("fc01"))
    det("F28", "clock_offsets", "Which record channels have clock errors?", ", ".join(f"{k} {v:+d} min" for k, v in world["distortion"]["clock_offsets_min"].items() if v), ["people/badge_access.csv", "people/forklift_telematics.csv", "people/photos_exif.csv", "people/cctv_motion.csv"])
    # --- undeterminable
    undet("U01", "door_prop_actor", f"Who held the room {inc} door open on the incident night?", [H("temp_worker"), H("night_lead")],
          "someone held it open for hours; both were on site all night", f"the room {inc} badge reader was offline all week (ticket {meta['ticket_badge']}); corridor CCTV retention is 7 days and the incident night was overwritten before export; both had access and a wedge (the temp worker's purchase, the dock wedge)",
          [gw, snap, "people/receipts/hardware_receipt_wedge.txt"], [f"people/badge_access.csv (ROOM-{inc} rows)", "people/cctv_motion.csv (incident night)"], traps=trap("fc07"))
    undet("U02", "override_actor", "Who deployed the minimum-severity override?", [H("sre_oncall"), H("ops_engineer")],
          f"it was deployed at about {iso(world, plan['override_t'])} (alerting log) as an untracked file", "the file is untracked (no author, uniform mtimes), both engineers deny it in statements and chat, both were on call with deploy access",
          ["repo/deploy/config.override.json", "deploy/logs/alerting.log", "people/chat_export.json"], ["deploy shell history / audit trail (not collected)"], traps=trap("fc08"))
    undet("U03", "peak_temperature", f"What peak temperature did room {inc} reach?", ["a few degrees above the product limit (roughly -10 C)", "near or above 0 C (the door stood open for hours; the recovery curve is consistent with either)"],
          "it exceeded the product limit for hours", "no telemetry reached the gateway while the door was open (link down) and the fault snapshot ends at the lockout; only the recovery curve after the door closed survives",
          [gw, snap], ["controller frames during the open-door period"])
    for z in plan["probe_excluded"]:
        undet(f"U0{4 + plan['probe_excluded'].index(z)}", f"bias_{z}", f"What is the sensor offset of room {z}?", ["the sensor reads low (negative offset)", "the sensor reads high (positive offset)"],
              "nothing", f"room {z} is not on either probe route, so no independent temperature reference exists for it", [], ["people/probe_checks_sheet.csv (room " + z + " rows)"])
    if causal.get("affected_lots_undeterminable"):
        undet("U06", "gap_lots", f"Which lots were moved into or out of room {inc} during the disk-full window?", ["the moves the ledger shows for that window", "additional moves the ledger lost to the race"],
              "some moves happened (dispatch queue rows exist)", "the gateway scanner lines for the window were never written (disk full) and FL-2's telematics was offline, so the ledger is the only record and the ledger is known to be corrupted",
              ["db/queue.sql", "db/ledger.sql"], ["deploy/logs/gateway.log (scanner lines in the gap)", "people/forklift_telematics.csv (FL-2 rows)"])
    undet("U07", "nightlead_awareness", "Did the night lead see the propped door before it was closed?", ["saw it and closed it", "closed it without noticing the wedge", "someone else closed it"],
          "the door was closed at the time the link returned", "no badge record (reader offline), no CCTV (retention), and the only account is the night lead's own statement",
          [gw], ["people/badge_access.csv", "people/cctv_motion.csv"])
    undet("U08", "vendor_intent", "Did the technician knowingly misreport which units were flashed?", ["clerical error", "deliberate"],
          "the report is wrong about the incident room", "intent is not recoverable from these records", ["people/vendor_service_reports/service_report_firmware_visit.md"], ["vendor's internal job record"])
    # --- ill-posed
    ill("I01", "single_root_cause", "What is the single root cause of the missed alarm?",
        "there is no single cause: the alarm was independently prevented by (1) the decoder's delta assumption after the 3.4 flash (readings never crossed the high limit), (2) the routing hotfix to an archived channel, (3) the minimum-severity override, and (4) the link loss while the door was open; removing any one alone would not have raised a page",
        ["repo/gateway/rh7_decode.py", "deploy/logs/alerting.log", "repo/deploy/config.override.json", gw], traps=trap("fc06"))
    ill("I02", "quarantine_by_ledger", "Which lots should be quarantined according to the ledger?",
        "the ledger cannot answer it: its positions were corrupted by the dispatch race; the physical positions must be rebuilt from the inventory import, the forklift telematics and the scanner lines, and for the disk-full window they cannot be rebuilt at all",
        ["db/ledger.sql", "deploy/logs/dispatch.log", "people/forklift_telematics.csv"])
    return F


def timeline_block_v2(world, report, meta):
    """Only events whose actor the evidence establishes (undeterminable actors live in facts)."""
    tl = timeline_block(world, report, meta)
    drop = {"door_prop_incident", "door_close_incident", "override_deploy"} | {e["event_id"].split(":")[1] for e in tl["events"] if e["event_id"].startswith("event:door_prop_earlier")}
    tl["events"] = [e for e in tl["events"] if e["event_id"].split(":")[1] not in drop]
    A = world["actors"]
    plan = world["plan"]
    tl["events"].append({"event_id": "event:recalibration_visit", "actor": f"actor:{A['vendor_tech']['handle']}", "action": "firmware_flash" if False else "probe_check", "t": iso(world, plan["recal_t"]), "tol_s": 1800, "ref": f"zone:{plan['drift_zone']}"})
    tl["events"].append({"event_id": "event:diskfull_cleanup", "actor": f"actor:{A['sre_oncall']['handle']}", "action": "ticket_close", "t": iso(world, plan["diskfull"]["t1"]), "tol_s": 1800, "ref": ""})
    tl["events"].append({"event_id": "event:badge_ticket", "actor": f"actor:{A['warehouse_manager']['handle']}", "action": "ticket_open", "t": iso(world, plan["badge_reader_outage"]["t0"]), "tol_s": 600, "ref": f"ticket:{meta['ticket_badge']}"})
    tl["events"].append({"event_id": "event:drift_ticket", "actor": f"actor:{A['receiving_clerk']['handle']}", "action": "ticket_open", "t": iso(world, world["ledger"]["sensor_drift"]["t0"] + 10 * 1440), "tol_s": 600, "ref": f"ticket:{meta['ticket_drift']}"})
    return tl


def build_v2(build, world, sim, nt, info, report, ev, log):
    meta = json.load(open(build / "docs_meta.json"))
    win = sim["checks"]["incident_window"]
    mech = mechanism_block(world)
    for z in world["plan"]["probe_excluded"]:
        mech["params"][f"bias.{z}"]["undeterminable"] = True
    wire = nt.truth()
    if "types" in wire or "protocol" in wire:
        proto = wire.get("protocol", wire)
        inc = world["zones"]["incident_zone"]
        nota = notation_block(world, sim, nt, ev) if False else None
        # held-out frames via the shared decoder path
        proto_block = dict(proto)
        proto_block["heldout"] = heldout_frames(world, sim, nt, ev)
        proto_block["controller_clock_epochs"] = clock_epochs(world, sim)
        logs = "".join(p.read_text(errors="replace") for p in (ev / "deploy" / "logs").glob("gateway.log*")) + "".join(p.read_text() for p in (ev / "controller").glob("*.txt"))
        proto_block["unscored_types"] = sorted(code for code in proto["types"] if (logs.count(f",{code.upper()},") + logs.count(f",{code.lower()},")) < 2)
    else:
        proto_block = notation_block(world, sim, nt, ev)
    causal = causal_block(world, sim, report, meta, win)
    causal["affected_lots_determinable"], causal["affected_lots_undeterminable"] = lots_determinability(world, meta, win)
    tl = timeline_block_v2(world, report, meta)
    facts = facts_block(world, sim, report, meta, win, causal, tl)
    idx = evidence_index(world, causal, tl, proto_block if "glossary" in proto_block else {"glossary": {}, "known_roots": []}, ev)
    for f in facts:
        if f["kind"] == "determinable":
            idx[f["id"]] = f["evidence_for"]
    canaries = ["eval_imp", "frostline_gen", "mechanism.py", "docs_gen", "repo_gen", "assemble.py", "truth.json", "world.json", "sub_seed",
                f"seed={world['seed']}", "faketime", "FAKETIME", "libfaketime", "/build/", "/home/goutham", "claude", "docs_meta", "sim_series",
                "driver_report", "incident_zone", "red_herring", "canar", "fact_sheet", "undeterminable", "trap_claim"]
    truth = {"instance": "pending", "seed": world["seed"], "tier": world["tier"], "version": 2, "mechanism": mech, "protocol": proto_block,
             "notation": proto_block if "glossary" in proto_block else {"base": 0, "digit_glyphs": [], "clause_order": "", "glossary": {}, "known_roots": [], "affixes": {}, "v34_change": proto_block.get("v34_change", "absolute_temp"), "heldout": proto_block.get("heldout", [])},
             "causal": causal, "timeline": tl, "facts": facts, "evidence_index": idx, "canaries": canaries,
             "build": {"sub_seed": world.get("sub_seed"), "incident_window_min": list(win), "checks": sim["checks"],
                       "driver": {k: report.get(k) for k in ("sent", "unacked", "dropped_radio", "unsent_linkdown", "late_max_s", "moves_posted", "probes_posted", "snapshot", "outages")},
                       "lots_wrong": sorted(set(meta["db_lots_in_inc"]) ^ set(meta["true_lots_in_inc"])), "mislabels": meta["mislabels"]}}
    n_det = sum(1 for f in facts if f["kind"] == "determinable"); n_un = sum(1 for f in facts if f["kind"] == "undeterminable"); n_ill = len(facts) - n_det - n_un
    log(f"truth v2: params={len(mech['params'])} (undet {sum(1 for p in mech['params'].values() if p.get('undeterminable'))}) heldout={len(proto_block.get('heldout', []))} facts det/undet/ill={n_det}/{n_un}/{n_ill} events={len(tl['events'])} claims={len(meta['false_claims'])} lots det/undet={len(causal['affected_lots_determinable'])}/{len(causal['affected_lots_undeterminable'])}")
    return truth


def heldout_frames(world, sim, nt, ev):
    inc = world["zones"]["incident_zone"]
    ctrl = world["zones"]["controller"][inc]
    snap = ev / "controller" / f"{ctrl}_fault_snapshot.txt"
    by_seq = {}
    for fr in sim["frames"]:
        if fr["zone"] == inc:
            by_seq.setdefault(fr["seq"], []).append(fr)
    out = []
    if not snap.exists():
        return out
    for line in snap.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        raw = line.split(" ", 1)[1]
        try:
            d = nt.decode(raw, setpoint=None)
        except ValueError:
            continue
        cands = by_seq.get(d["seq"], [])
        fr = cands[-1] if cands else None
        if fr is None:
            continue
        c0 = fr["clauses"][0]
        if c0["kind"] == "READ":
            event, value = c0["sensor"], c0["value"]
        elif c0["kind"] == "STATE":
            event, value = c0["state"], None
        else:
            event, value = EVENT_HEAD[c0["event"]], (c0.get("value") if c0["event"] in ("SETPOINT_SET", "QUEUE_OVERFLOW") else None)
        out.append({"seq": d["seq"], "ts": iso(world, fr["t_min"]), "zone": inc, "event": event, "value": value, "tol_value": 0.2, "tol_s": 120})
    return out


def clock_epochs(world, sim):
    return {world["zones"]["controller"][z]: [{"from": iso(world, a), "epoch": iso(world, b)} for a, b in eps] for z, eps in sim["clock_epochs"].items()}


def lots_determinability(world, meta, win):
    """A lot's presence in the incident room is determinable if its last move before the window end is covered by
    telematics (correct clock) or by scanner lines outside the disk-full gap; otherwise only the corrupted ledger knows."""
    plan = world["plan"]
    inc = world["zones"]["incident_zone"]
    fo, df = plan["fl2_outage"], plan["diskfull"]
    last_move = {}
    for mv in sorted(world["ledger"]["moves"], key=lambda m: m["t_sec"]):
        if mv["t_sec"] // 60 <= win[1]:
            last_move[mv["lot"]] = mv
    det, undet = [], []
    for lot in meta["true_lots_in_inc"]:
        mv = last_move.get(lot)
        if mv is None:
            det.append(f"lot:{lot}")          # never moved: inventory import + no moves
            continue
        t = mv["t_sec"] // 60
        telem_ok = not (mv["forklift"] == fo["forklift"] and fo["t0"] <= t <= fo["t1"])
        scanner_ok = not (df["t0"] <= t <= df["t1"])
        (det if (telem_ok or scanner_ok) else undet).append(f"lot:{lot}")
    return det, undet
