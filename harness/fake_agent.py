"""Scripted zero-API solver: drives the real Executor through every tool, writes an invalid then a valid
/work/answer.json, validates, stops. Exercises executor, logging, snapshots, transcript and usage files."""
from __future__ import annotations

import json
import time
from pathlib import Path

from harness import prompts
from harness.tools import Executor

VALID_ANSWER = {
    "schema_version": "1",
    "mechanism": {"parameters": {"k_cool.A": 0.08, "lockout.N": 3},
                  "rules": {"defrost_rule_type": "runtime_hours", "stagger_order": ["A", "B", "C"], "adjacency_pairs": [["A", "B"]]}},
    "notation": {"glossary": {"pola": "HDR"}, "affixes": {"-ka": "ZONE"}, "v34_change": "absolute_temp",
                 "heldout": [{"seq": 1, "ts": "2026-03-09T02:41:00Z", "zone": "C", "event": "AIR_TEMP", "value": -6.4}]},
    "causal_chain": {"roots": ["physical:door_prop:C"], "nodes": ["physical:door_prop:C", "data:lots_wrong:C"],
                     "edges": [["physical:door_prop:C", "data:lots_wrong:C"]], "decoys_rejected": ["doc:recall_notice"],
                     "affected_lots": ["lot:LN-24019"],
                     "excursion": {"zone": "C", "start": "2026-03-09T02:00:00Z", "end": "2026-03-09T04:00:00Z"}},
    "timeline": {"events": [{"actor": "actor:m.rivera", "action": "door_prop", "t": "2026-03-09T01:50:00Z", "ref": ""}],
                 "clock_offsets_min": {"badge": 11, "exif": -60},
                 "false_claims": [{"doc_id": "doc:postmortem", "quote": "the compressor failed"}]},
    "confidence": {"mechanism": 0.3, "notation": 0.5, "causal_chain": 0.4, "timeline": 0.2},
}


VALID_ANSWER_V2 = {
    "schema_version": "2",
    "mechanism": {"parameters": {"k_cool.A": {"value": 0.08, "confidence": 0.5}, "bias.D": {"value": None, "confidence": 0.0, "note": "no probe checks"}},
                  "rules": {"defrost_rule_type": "runtime_hours", "stagger_order": ["A", "B", "C"], "adjacency_pairs": [["A", "B"]]}},
    "protocol": {"types": {"3a": "STATUS", "6e": "DEFROST"}, "status_words": ["DISCH_PRESSURE", "AIR_TEMP", "COIL_TEMP", "STATE_FLAGS"],
                 "temp_scale": 10, "temp_offset": 500, "press_scale": 10, "flag_bits": {"RUN": 10, "ABS_TEMP": 15}, "v34_change": "absolute_temp",
                 "heldout": [{"seq": 1, "ts": "2026-03-09T02:41:00Z", "zone": "E", "event": "AIR_TEMP", "value": -6.4}]},
    "findings": [{"claim": "The room E door was held open for several hours on the incident night.", "status": "established", "confidence": 0.8, "evidence": ["deploy/logs/gateway.log"]},
                 {"claim": "Who held the door open cannot be determined from the surviving records.", "status": "undetermined", "confidence": 0.5, "evidence": ["people/tickets.json"], "alternatives": ["the agency worker", "the night lead"]}],
    "timeline": {"events": [{"actor": "actor:m.rivera", "action": "commit", "t": "2026-03-09T01:50:00Z", "ref": ""}],
                 "clock_offsets_min": {"badge": 11, "exif": -60},
                 "false_claims": [{"doc_id": "doc:postmortem", "quote": "Root cause: compressor failure"}]},
    "confidence": {"mechanism": 0.3, "protocol": 0.5, "findings": 0.4, "timeline": 0.2},
}
REPORT_V2 = "# Findings\n\nThe door was held open; the compressor did not fail. Who propped it cannot be determined.\n"


def script(version: str = "1") -> list:
    valid = json.dumps(VALID_ANSWER_V2 if version == "2" else VALID_ANSWER, indent=1)
    extra = [("Writing the report.", "bash", {"cmd": f"cat > /work/report.md <<'EOF'\n{REPORT_V2}EOF"})] if version == "2" else []
    return extra + [
        ("Reading the brief.", "read_file", {"path": "TASK.md"}),
        ("Where is the answer schema referenced?", "grep", {"pattern": "answer", "path": "/evidence", "flags": "-i -l"}),
        ("Listing the evidence tree.", "bash", {"cmd": "ls -R /evidence | head -50"}),
        ("Draft answer (deliberately broken JSON).", "bash", {"cmd": "cat > /work/answer.json <<'EOF'\n{\"schema_version\": \"1\",\nEOF"}),
        ("Checking the draft.", "validate_answer", {}),
        ("Writing a schema-valid answer.", "bash", {"cmd": f"cat > /work/answer.json <<'EOF'\n{valid}\nEOF\nwc -c /work/answer.json"}),
        ("Final validation.", "validate_answer", {}),
    ]


def _schema_version(run_dir) -> str:
    try:
        sch = json.load(open(Path(run_dir) / "evidence" / "ANSWER_SCHEMA.json"))
        return str(sch.get("properties", {}).get("schema_version", {}).get("const", "1"))
    except Exception:  # noqa: BLE001
        return "1"


def run_fake(run_dir, tier: str = "default", max_tool_calls: int = 600, **_) -> dict:
    run_dir = Path(run_dir)
    t0 = time.time()
    ex = Executor(run_dir, tier)
    tr = open(run_dir / "transcript.jsonl", "a")
    us = open(run_dir / "usage.jsonl", "a")
    i = 0

    def row(r):
        nonlocal i
        r["i"] = i
        r["t"] = round(time.time() - t0, 2)
        tr.write(json.dumps(r, ensure_ascii=False) + "\n")
        tr.flush()
        i += 1

    row({"role": "user", "text": prompts.KICKOFF, "tool_calls": [], "result_preview": None, "context_tokens": None})
    end_reason = "stopped"
    for n, (text, tool, args) in enumerate(script(_schema_version(run_dir))):
        if ex.n_calls >= max_tool_calls:
            end_reason = "tool_cap"
            break
        cid = f"call_{n}"
        row({"role": "assistant", "text": text, "tool_calls": [{"id": cid, "name": tool, "args": args}], "result_preview": None, "context_tokens": 0})
        us.write(json.dumps({"i": i - 1, "input_tokens": 0, "cache_read": 0, "cache_write": 0, "output_tokens": 0, "context_tokens": 0, "cost_usd": 0.0}) + "\n")
        res = ex.call(tool, args)
        row({"role": "tool", "name": tool, "tool_use_id": cid, "text": "", "tool_calls": [], "result_preview": res["text"][:600],
             "is_error": res["is_error"], "context_tokens": None})
    row({"role": "assistant", "text": "Answer validated; stopping.", "tool_calls": [], "result_preview": None, "context_tokens": 0})
    tr.close()
    us.close()
    return {"route": "fake", "model_id_observed": "fake/scripted", "end_reason": end_reason, "end_detail": "script exhausted",
            "wall_s": round(time.time() - t0, 1), "cost_usd": 0.0, "cost_source": "none", "cost_estimate_usd": 0.0,
            "invalid_markers": [], "n_tool_calls_stream": ex.n_calls}
