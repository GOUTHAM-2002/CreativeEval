# eval_imp contract: generator <-> harness <-> grader

Everything that crosses a module boundary is defined here. Modules may not rely on anything else.

## 1. Instance directory (`gen.assemble` output)

```
instances/<inst_id>/                inst_id = s<seed:04d>_<build8>   (build8 = first 8 hex of sha256 of evidence tar)
  evidence/                         the ONLY thing ever bound into the solver sandbox (read-only, at /evidence)
    TASK.md                         the brief (rules, answer location, no-feedback statement)
    questions.json                  agent-visible instance metadata (see §3)
    ANSWER_SCHEMA.json              jsonschema for /work/answer.json (see §4)
    repo/                           dirty git checkout of the services (with .git, no build artifacts)
    deploy/logs/<service>.log       real service logs from the build run
    db/ledger.sql                   text SQL dump of the ledger SQLite DB
    controller/zoneC_ringbuffer.txt held-out raw frames (never reached the gateway)
    people/...                      human documents and machine CSVs (see gen/docs_gen.py)
  truth.json                        HOST-ONLY (mode 600). Ground truth, tolerances, canaries (see §5)
  world.json                        HOST-ONLY generator internals (ledger, params, distortion table)
  build.log                         HOST-ONLY
```
All files under `evidence/` are text; all mtimes are set to `2026-01-01T00:00:00Z`; no path component or
content may contain any string in `truth.canaries`.

## 2. ID grammar (used in truth.json, ANSWER_SCHEMA enums, and by the solver)

| Type | Form | Example | Where the solver can enumerate them |
|---|---|---|---|
| actor | `actor:<handle>` | `actor:m.rivera` | chat export, tickets, badge CSV, statements |
| commit | `commit:<sha7>` | `commit:3fa9c1e` | `git log` in evidence/repo |
| config | `config:<relpath>:<dotted.key>` | `config:alerting/routes.yml:zones.C.channel` | files in evidence/repo |
| code | `code:<relpath>:<function>` | `code:dispatch/worker.py:move_pallet` | files in evidence/repo |
| firmware | `firmware:<zone>` | `firmware:C` | telegrams, vendor reports |
| physical | `physical:<ptype>:<zone>` | `physical:door_prop:C` | ptype in enum PHYSICAL_TYPES |
| data | `data:<dtype>:<scope>` | `data:lots_wrong:C` | dtype in enum DATA_TYPES |
| doc | `doc:<file-stem>` | `doc:recall_notice` | files under evidence/people |
| ticket / alert / msg | `ticket:<id>` `alert:<id>` `msg:<id>` | `ticket:T-0417` | tickets.json, alerting log, chat_export.json |
| lot / zone / ctrl | `lot:<id>` `zone:<L>` `ctrl:<id>` | `lot:LN-24019` | ledger.sql, telegrams |

Matching rule (grader): exact string equality after `strip().lower()`.

Enums (fixed across seeds; published verbatim in questions.json):
- `PHYSICAL_TYPES = [door_prop, door_open, trip, lockout, defrost, excursion, compressor_fault, sensor_fault, power_loss, frame_burst]`
- `DATA_TYPES = [readings_wrong, lots_wrong, alerts_suppressed, frames_dropped, quarantine_wrong]`
- `CAUSE_CATEGORIES = [physical, firmware, code_defect, config_drift, race_condition, data_format, human_action, decoy]`
- `ACTIONS = [door_prop, door_open, door_close, pallet_move, firmware_flash, config_edit, commit, override_deploy, archive_channel, probe_check, ticket_open, ticket_close, alert_ack, statement, quarantine, shift_start, shift_end, purchase, photo, postmortem_publish]`
- `DEFROST_RULE_TYPES = [runtime_hours, wall_clock, temperature]`
- `V34_CHANGE = [absolute_temp, delta_temp, unit_change, scale_change, none]`
- `AFFIX_ROLES = [ZONE, ASPECT_EVENT, ASPECT_STATE, NEGATION, PLURAL]`
- `NOTATION_LABELS` = HDR, ZONE_A..ZONE_F, RUN, IDLE, DEFROST, RECOVERY, LOCKOUT, TRIP, AIR_TEMP, COIL_TEMP,
  DISCH_PRESSURE, DOOR, HEATER, SETPOINT, COMPRESSOR, FIRMWARE, QUEUE, READ, ENTER, EXIT, SET, FAULT, CLEAR,
  BOOT, OPEN, CLOSED, ON, OFF, HIGH, LOW, STALE, ABS, OVERFLOW, DIGIT_0 .. DIGIT_11
- `CHANNELS = [badge, exif, cctv, forklift, chat, tickets, git, submeter, gateway, probe]` (clock-offset channels)
- `MECH_PARAM_IDS` = `k_cool.<Z>`, `k_leak.<Z>`, `H.<Z>`, `bias.<Z>` for Z in zones, plus `door_gain`, `c_adj`,
  `defrost.R_hours`, `defrost.len_min`, `defrost.heat_degC`, `trip.d_min`, `lockout.N`, `lockout.W_min`, `lockout.L_min`

## 3. questions.json (agent-visible)
```json
{"instance": "<inst_id>", "zones": ["A","B","C","D","E","F"], "controllers": {"A":"K7-01", ...},
 "mechanism_params": {"k_cool.A": {"unit": "degC/min"}, ..., "lockout.N": {"unit": "count"}},
 "heldout_path": "controller/zoneC_ringbuffer.txt",
 "id_grammar": {...the table above...}, "enums": {...all enums above...},
 "channels": [...], "notes": "Actor handles are not listed; find them in the evidence."}
```

## 4. /work/answer.json (solver output; ANSWER_SCHEMA.json is generated from contract/answer_schema.template.json)
```json
{"schema_version": "1",
 "mechanism": {"parameters": {"k_cool.A": 0.08, ...},
               "rules": {"defrost_rule_type": "runtime_hours", "stagger_order": ["C","A","E","B","D","F"],
                         "adjacency_pairs": [["A","B"], ...]}},
 "notation": {"glossary": {"<root>": "<NOTATION_LABEL>", ...}, "affixes": {"<affix>": "<AFFIX_ROLE>"},
              "v34_change": "absolute_temp",
              "heldout": [{"seq": 4412, "ts": "2026-03-09T02:41:00Z", "zone": "C", "event": "AIR_TEMP", "value": -6.4}, ...]},
 "causal_chain": {"roots": ["<id>"], "nodes": ["<id>"], "edges": [["<id>","<id>"]],
                  "decoys_rejected": ["<id>"], "affected_lots": ["lot:..."],
                  "excursion": {"zone": "C", "start": "<iso>", "end": "<iso>"}},
 "timeline": {"events": [{"actor": "actor:<h>", "action": "<ACTION>", "t": "<iso>", "ref": "<id or ''>"}],
              "clock_offsets_min": {"badge": 11, "exif": -60, ...},
              "false_claims": [{"doc_id": "doc:<stem>", "claim_id": "<id>"}]},
 "confidence": {"mechanism": 0.3, "notation": 0.5, "causal_chain": 0.4, "timeline": 0.2}}
```
`heldout[].event` is the NOTATION_LABEL of the clause's main token (AIR_TEMP, COIL_TEMP, DISCH_PRESSURE, DOOR,
TRIP, LOCKOUT, DEFROST, HEATER, ...); `value` is degC for temps, bar for pressure, omitted otherwise.
`false_claims[].claim_id` refers to claim markers the generator embeds as stable ids? NO — the solver cannot see
claim ids. Instead `false_claims[]` = `{"doc_id": "doc:<stem>", "quote": "<verbatim substring of the doc>"}`;
the grader matches a quote to a truth claim if the quote overlaps the claim's recorded character span.

## 5. truth.json (host-only)
```json
{"instance": "<inst_id>", "seed": 1, "tier": "default",
 "mechanism": {"params": {"k_cool.A": {"value": 0.081, "abs_tol": 0.008, "rel_tol": 0.10, "unit": "degC/min"}, ...},
               "rules": {"defrost_rule_type": "runtime_hours", "stagger_order": [...], "adjacency_pairs": [[..],..]}},
 "notation": {"base": 8, "digit_glyphs": ["ka", ...], "clause_order": "VSO",
              "glossary": {"<root>": "<LABEL>"},            // ALL roots
              "known_roots": ["<root>", ...],               // subset shipped in kw7_decode.py (unscored)
              "affixes": {"<affix>": "<ROLE>"}, "v34_change": "absolute_temp",
              "controller_clock_epoch": {"K7-01": "<iso>", ...},
              "heldout": [{"seq": 4412, "ts": "<iso>", "zone": "C", "event": "AIR_TEMP", "value": -6.4, "tol_value": 0.2, "tol_s": 120}, ...]},
 "causal": {"nodes": ["<id>", ...], "edges": [["<id>","<id>"], ...], "roots": ["<id>"], "decoys": ["<id>"],
            "node_categories": {"<id>": "<CAUSE_CATEGORY>"},
            "affected_lots": ["lot:..."], "excursion": {"zone": "C", "start": "<iso>", "end": "<iso>", "tol_s": 900}},
 "timeline": {"events": [{"event_id": "event:<id>", "actor": "actor:<h>", "action": "<ACTION>", "t": "<iso>", "tol_s": 300, "ref": "<id or ''>"}],
              "clock_offsets_min": {"badge": 11, "exif": -60, "cctv": -4, "forklift": 0, "git": 0, ...},
              "false_claims": [{"claim_id": "fc01", "doc_id": "doc:<stem>", "path": "people/statements/<file>", "span": [start, end], "text": "...", "truth_ref": "event:<id>"}]},
 "evidence_index": {"<fact_id>": ["<evidence-relative path>", ...]},      // fact_id = param id | root | node id | edge "a->b" | event id | claim id
 "canaries": ["<seed literal>", "<param value literals>", "<generator identifiers>", ...]}
```

## 6. Notation clause IR (gen/mechanism.py -> gen/notation.py -> runtime/driver.py)
```
Frame  = {"ctrl_id": "K7-03", "zone": "C", "seq": int, "t_ctrl_min": int, "fw": "3.2"|"3.4", "clauses": [Clause,...]}
Clause = {"kind":"READ",  "sensor": "AIR_TEMP"|"COIL_TEMP"|"DISCH_PRESSURE", "zone": "C", "value": float}
       | {"kind":"STATE", "state": "RUN"|"IDLE"|"DEFROST"|"RECOVERY"|"LOCKOUT", "zone": "C"}
       | {"kind":"EVENT", "event": "DOOR_OPEN"|"DOOR_CLOSE"|"TRIP"|"LOCKOUT_ENTER"|"LOCKOUT_EXIT"|"DEFROST_ENTER"|
                          "DEFROST_EXIT"|"HEATER_ON"|"HEATER_OFF"|"BOOT"|"SETPOINT_SET"|"QUEUE_OVERFLOW", "zone": "C", "value": float|null}
```
`notation.Notation(seed_rng).encode(frame) -> str` (one line, ASCII), `.decode(line) -> Frame` (truth decoder),
`.render_partial_decoder() -> str` (source of the shipped `gateway/kw7_decode.py`, decoding only `known_roots`;
unknown tokens are emitted as `unk=<token>`), `.render_quickref() -> str` (obsolete v2 card),
`.truth() -> dict` (the `notation` block of §5 minus `heldout`). Temperature encoding: v3.2 value = round((T - setpoint)*10) + 500;
v3.4 value = round(T*10) + 500 with an extra ABS qualifier token in the clause. Pressure: round(bar*10).
Numbers: bijective-free plain positional base-b using per-seed digit glyphs (leading digit non-zero except the number 0).

## 7. Sandbox surface (harness -> solver)
Tools (names as the model sees them, under MCP server `sandbox`): `read_file(path, start_line?, end_line?)`,
`grep(pattern, path, flags?)`, `bash(cmd, timeout_s?)`, `validate_answer()`. Mounts: `/evidence` ro,
`/work` rw (cwd), `/tmp` tmpfs, `/home/agent` rw. No network. Default tier: `/usr` ro (python3 available);
`no_compute` tier: whitelist from `sandbox/toolbox.txt`.

## 8. Run directory (harness -> grader)
```
runs/<tag>/<model_key>/<inst_id>/
  episode.json        {model, model_id_observed, route, inst_id, tier, end_reason, n_tool_calls, n_validate_calls,
                       wall_s, cost_usd, cost_source, invalid_markers[], started, ended}
  transcript.jsonl    normalised rows {i, role, text, tool_calls[], result_preview, t, context_tokens}
  tool_log.jsonl      authoritative executor log {seq, tool, args, exit, stdout_len, stderr_len, t}
  usage.jsonl         per assistant message {i, input_tokens, cache_read, cache_write, output_tokens, context_tokens, cost_usd}
  answer_history/NNNN.json   snapshot of /work/answer.json after each tool call that changed it
  answer.json         final graded submission (copy of last valid snapshot; absent if none)
  score.json          grader output {measured:{...}, authored:{...}, sections:{...}, aggregate, solved, calibration}
```
