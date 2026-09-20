# Independent incident reconstruction — Borealis Coldchain, ZLH62

**Scope:** frozen evidence, June 4–July 4, 2026. All times below are UTC (also site local time). No equipment was tested, no live system was queried, and no person was interviewed. Findings distinguish observed events from model estimates and missing evidence. The accompanying `answer.json` contains the structured findings, parameter estimates, chronology, exact disputed quotations, and expanded translation of every surviving snapshot frame.

## 1. Executive findings

The company postmortem is not a reliable causal or inventory reconstruction.

1. **Room E suffered a real warm excursion following a sustained door opening at 00:38 on June 20.** The recovered controller snapshot shows increasing temperature and discharge pressure, three high-pressure trips, then protective lockout at 01:34. Normal cycling precedes the opening. Subsequent automatic restart and cooling do not support the asserted initiating compressor hardware failure or an upward-drifting setpoint. The filed compressor recall explicitly excludes the site's equipment.
2. **The monitoring stack concealed the excursion through several independent defects.** Firmware 3.4 changed temperature representation on **both C and E**, but the gateway continued adding their negative setpoints to temperatures already expressed absolutely. Normal rooms therefore appeared approximately −40 °C. E's fully opened door also interrupted its controller communication through a previously reproduced, unrepaired cable fault. Alerting kept evaluating the old temperature without testing freshness. After reconnection, even the hottest surviving E reading was misdecoded to the configured high limit rather than above it.
3. **Routing and severity suppression compounded these defects, but responsibility must be separated.** Maya Larsen's June 9 routing commit is attributable. Priya Novak's June 10 archival of the destination channel is attributable. **The author and exact deployment time of the critical-only override are not established.** The postmortem cannot properly assign that deployment to the on-call SRE.
4. **The person responsible for the incident-night door opening is not identifiable.** Maya Mensah's earlier wedge use contradicts her categorical denial, but is not proof that she opened the door on June 20. E's badge reader was broken and incident-night CCTV had expired.
5. **The ledger is not a valid physical inventory history.** A route-shadowing bug causes individual-lot reads to return the entire collection. Every reconciliation then fails on the missing `zone` key, yet its queue job is marked `done`. The surviving ledger contains **zero moves** and all **66 lots remain at their imported positions**. The postmortem's twelve quarantined lots reproduce imported E inventory, not demonstrated excursion-time residence. It omits the degraded lot LN-22416, physically delivered into E before the incident, and includes LN-25578, physically in C across the incident on the available movement evidence.

**Disposition implication:** do not release material based on the current ledger, a queue `done` flag, a normal-looking historical dashboard, or the postmortem list. Conduct a qualified product-risk assessment using independent movement evidence and actual temperature uncertainty; room-air telemetry alone does not establish individual product-core thermal dose.

## 2. Evidence handling and clock reconciliation

I parsed the raw telegrams in **both** gateway rotations, rather than trusting the stored `air_temp` interpretation. There are 51,060 raw frames in those logs, including 47,302 status messages. The ledger has 50,052 reading rows; it is not a complete substitute for the raw gateway record. All 51,060 logged frames and all 45 supplied snapshot frames pass the XOR checksum. The snapshot adds otherwise missing controller history. SQL dumps were loaded only into local working databases for inspection. Source and git history were read, not deployed or rerun.

Offsets below mean **recorded channel time minus true time**:

| Channel | Offset, minutes | Basis / limitation |
|---|---:|---|
| Badge | −7 | Repeated room unlocks align with forklift pickup and controller-door activity after adding seven minutes. Entrance times use the same correction. |
| EXIF `DateTimeOriginal` | −120 | Several photographs have independent GPS date/time exactly two hours later. Apply this correction to camera time, not to GPS time. A photograph time is not necessarily the time of the work it depicts. |
| CCTV motion index | −5 | Repeated late-June room-door/movement matches. Example: D motion June 27 17:31 corresponds to D opening/pickup 17:36; A motion 17:32 corresponds to opening 17:37. |
| Forklift, gateway, chat, tickets, git, submeter | 0 | Cross-record agreement supports no systematic minute offset. Receipt latency, binning and delayed human reporting remain; these are not clock offsets. |
| Probe sheet | 0 | No firm independent clock displacement demonstrated. Comparison to interpolated telemetry has minute-scale/noise uncertainty; entered-at is not taken-at. |

The old integration note is useful for ASCII framing and checksum, but not the current word layout or event codes. The vendor bench labels and runbook were also tested against observed state transitions, not accepted as ground truth.

### Principal record gaps

* E link failure June 20 shortly after 00:38; reconnection about 04:53:40, first surviving status 04:55. Other rooms continued to report.
* The controller snapshot is **45 entries**, ending at a lockout trigger; it is not a full recording of the communication outage. Its wire sequence skips 3556.
* Recurring ledger write failures during nightly billing occur even when gateway raw frames exist.
* All gateway logs are absent June 20 12:00–15:00 (disk full; T-0418), a different and later incident.
* ROOM-E badge reader failed June 16–21 (T-0411); FL-2 telemetry failed June 20–22 (T-0416).
* CCTV retention is seven days, so the July 4 motion export cannot identify a June 20 actor.
* The ledger audit table is empty; no preserved authenticated deployment record attributes the severity override.

## 3. Controller protocol and physical mechanism

### Wire reconstruction

A line is `$unit,seq,tick,type,w0 w1 ...*cs`. Sequence and tick are unsigned 24-bit hexadecimal fields; words are 16-bit hexadecimal. Checksum is XOR of the ASCII bytes between `$` and `*`. Sequence/tick epochs restart at controller reboot. Tick increments **six per minute**, hence ten seconds per tick. Normal status cadence is five minutes (30 ticks), not a 30-second cadence.

| Current type | Interpretation | Payload |
|---|---|---|
| F8 | STATUS | Four words, detailed below |
| 4D | DOOR | 1 open, 0 closed |
| 74 | TRIP | 1 high-pressure trip |
| 1D | LOCKOUT | 1 entered, 0 cleared |
| BD | DEFROST | 1 started, 0 ended; not the bench report's condenser fan |
| 50 | HEATER | 1 on, 0 off; paired with defrost windows |
| 62 | BOOT / firmware | `0032` = version 3.2; `0034` = 3.4 (version digits, not decimal 50/52 as engineering versions) |
| 34 | QUEUE_OVERFLOW | Lost-entry count; e.g. `0041` = 65 after E reconnects |

**No SETPOINT type is observed.** I have not invented a ninth code from the obsolete documentation or from a parser branch that never executes.

Status word order is **air temperature, discharge pressure, state flags, coil temperature**. Temperature scale is ten counts/°C, encoding offset 1000. Under older firmware, decode as `setpoint + (word−1000)/10`; with the absolute flag set, decode as `(word−1000)/10`. Pressure is `word/100` in bar. Coil temperatures drop approximately six degrees below air while running, supporting its identification; the pressure word rises under loaded running and before trips.

Flags are RUN bit 15, ABS_TEMP bit 14, DOOR_OPEN bit 12, LOCKOUT bit 6, RECOVERY bit 2, DEFROST bit 1. Thus snapshot `D000` means running, absolute representation, door open; `5000` means absolute/open with compressor stopped. `4040` after reconnection means absolute representation plus lockout, not compressor running.

E's 3.4 boot has tick zero at **June 8 15:02**. Matching surviving snapshot and gateway sequences verifies the epoch. Snapshot time is that epoch plus `tick × 10 seconds`. Engineering temperatures in the translation are decoded **sensor readings**, before probe-bias correction. Raw STATE_FLAGS and an additional RUN/IDLE interpretation are both supplied; these are multiple observations from one frame, not extra received frames.

### Thermal behavior and estimates

A useful approximate balance is:

`dTz/dt = k_leak,z × (ambient − Tz) × [door open ? door_gain : 1] − k_cool,z × RUN + c_adj × Σ(Tneighbor − Tz) + defrost heating`.

The controller switches normal cooling around setpoint ± H, overrides normal thermostat operation for defrost/lockout, and performs recovery after defrost. Bias is **sensor minus actual air temperature**. The numerical fits are not claimed to be recovered factory settings: five-minute state sampling, probe noise, unobserved intermediate switching and the distinction between panel-room ambient and actual heat-transfer environment limit precision.

| Room | Cooling, °C/min | Leak, /min | H, approximate half-width °C | Baseline sensor bias, °C |
|---|---:|---:|---:|---:|
| A | 0.031 | 0.0011 | 0.9 | +1.5 |
| B | 0.093 | 0.00070 | 0.7 | **Undetermined** |
| C | 0.070 | 0.00075 | 1.0 | +0.4 |
| D | 0.066 | 0.00068 | 0.5 | +1.2, plus time-varying drift |
| E | 0.120 | 0.0011 | 0.7 | +1.0 |
| F | 0.030 | 0.0018 | 1.1 | **Undetermined** |

Interval fits suggest door gain roughly 6.5–8.2, represented as 7.5, and small adjacency coupling around 0.0001–0.0002/min. Leakage and especially coupling have lower confidence than the discrete state rules. B/F have no calibrated probe coverage; thermal assumptions are not a substitute for direct absolute-bias calibration. Their approximate dynamic coefficients should not be mistaken for independent bias measurements.

The floor plan establishes shared walls D–C, C–E, D–B, C–F, E–A, B–F, F–A, plus the sealed D–F hatch. Panel pairings are **C/E on P1, B/D on P2, A/F on P3**; electrical grouping is not adjacency.

Defrost becomes due after approximately **five accumulated running hours**. Integrating intermittent RUN observations after filling short sampling gaps supports a lower envelope near five hours; elapsed wall-clock intervals vary considerably. Due rooms can wait for shared heater arbitration. The most supported priority order is **C, A, F, B, D, E**; it is not the literal order of every observed start because some rooms are not yet due. Defrost/heater durations are consistently **24 minutes**, with modeled added heat about **4.5 °C** and subsequent recovery. The runbook's fixed six-hour claim fails this test.

Sustained open-door running produces a trip after about **ten minutes**, then approximately five minutes of stopped cooling before another attempt. **Four trips** within the qualifying look-back enter lockout. The evidence brackets the look-back at **84 to under 90 minutes**, represented approximately as 85; it does not measure an exact register boundary. For example D locks out June 25 after trips at 13:15, 13:30, 13:45 and 14:39 (span 84 minutes), whereas the June 6 sequence spanning 90 minutes does not. Three visible enter/clear pairs establish **90-minute lockout** independently. Reopening/continued loading can cause a new sequence after expiry.

### Room D calibration is a separate issue

Correct HH-2 readings by subtracting **0.8 °C**: its April 16 certificate says **OUT OF TOLERANCE**, not that it reads correctly. HH-1 is the better reference. Probe comparisons show D's baseline positive bias and gradual additional positive drift over mid-June, reaching approximately +3.2 °C extra before the June 27 service. Afterwards the extra drift disappears; the baseline offset should not be silently treated as zero. This is distinct from C/E's abrupt representational discontinuity after firmware changes.

## 4. Incident chronology and alert failure

| UTC | What is established |
|---|---|
| June 7, 10:58–11:25 | Planned utility interruption reported in T-0406; submeter supports loss of load. Controller boot frames arrive at 11:33, after gateway restart. This is not a channel clock offset. |
| June 8, 15:02 / 15:43 | E / C respectively reboot into 3.4. E's service report claim of inspection only is false. Invoice bills two firmware services. |
| June 9, 01:21 | Corrected time of Mensah's wedge-under-E-door photograph. Chat at 01:59 and the lead's response at 02:37 corroborate an earlier wedge episode. |
| June 9, 11:36:13 | Larsen's commit 761f81a changes C/E destination routes. It does not identify an override author. |
| June 10, 09:54 | Novak announces archival of the legacy alert channel, **before** the excursion. |
| June 19, 14:57–14:59 | Samuel Tanaka physically picks LN-22416 in C and drops it in E. |
| June 19, 21:49 / 22:02 | Corrected main-entrance arrivals of Mensah / Hana Tanaka, not their alleged joint 21:38 arrival. |
| June 20, 00:27–00:28 | A brief E opening/closure in the snapshot. No actor is identifiable. |
| 00:38 | Sustained E door opening. The gateway logs it, then the link closes at 00:38:45. |
| 00:49, 01:04, 01:19 | Three recovered high-pressure trips. The compressor resumes between them, with rising pressure and room temperature. |
| 01:00–01:41 | Concurrent nightly billing transaction blocks ledger writes for other reporting controllers. This does not explain the already-open E link. |
| 01:30 | Last snapshot temperature: reported −9.8 °C, approximately −10.8 °C actual air after baseline bias correction. |
| 01:34 | Lockout entry; snapshot ends. A fourth trip is supported by the established rule and missing predecessor sequence, but its absent telegram is **not** fabricated in the translation. |
| About 04:53–04:55 | Link returns. First surviving status reports +6.2 °C with LOCKOUT set and DOOR_OPEN clear. Closure is inferred by then; the precise close telegram is missing. |
| 04:56 | Overflow message reports 65 lost entries. |
| 05:25 | Reported +7.0 °C, approximately +6.0 °C actual air. This is a surviving sample, not a proven global peak. |
| 05:29 | Lockout clears. RUN and falling coil/air temperatures follow without a recorded compressor repair. Further unrecorded lockout during the blackout is probable; a unique complete sequence cannot be recovered. |
| 05:58 / 06:05 | Corrected departures of Mensah / Hana. |
| 06:16–06:20 | Sofia Larsen moves LN-21643 from C into E during recovery. |
| 06:23–06:26 | Another E opening and closure, contradicting the lead's claim that no one approached E after departure. |
| 07:02–07:26 | A 24-minute E defrost interrupts recovery; later RUN+RECOVERY resumes. |
| About 10:05–10:20 | Surviving samples return through the vicinity of −15 °C, depending on whether sensor reading or bias-corrected air is used. |
| 12:00–15:00 | Separate disk-full logging gap. |
| June 21, 12:41–12:45 | Sofia Larsen physically moves PL-9143/LN-25578 from C to B; scanner and queue agree. |
| June 30, 09:00 | Customer lab email and incident ticket identify LN-22416 potency loss consistent with prolonged warm storage. The report bears July 1 publication date; a June 30 ticket already claims publication/quarantine. Exact administrative issue time is not established. |

### Why the high alarm never protected product

* `rh7_decode.decode_line` unconditionally adds E's −19.3 °C setpoint to the absolute sensor value. C similarly gets an extra −19.8 °C.
* `gateway.handle_line` acknowledges only after a ledger write. Non-reading controller messages are treated as generic dispatch activity, not decoded safety events. The gateway's stale watchdog writes ledger events, but `alerting.evaluate` does not consume those events.
* `latest_readings` retains the last stored temperature. `evaluate` neither rejects an old `recv` nor alarms on loss of telemetry. During E's blackout the data therefore remain reassuringly, but falsely, cold.
* Even after reconnection, +7.0 °C becomes **−12.3 °C**, exactly E's upper alarm limit. The comparison is **strictly `>`**. Lower samples remain below that limit. The raw measurements were not a correctly generated high alarm subsequently silenced by a person.
* The critical-only override suppresses warning severity, not correctly generated critical highs. Separately, the routing hotfix applies to **all alerts for C/E**, and the legacy destination was archived. These are genuine defense failures, but neither replaces the decoder/freshness explanation.

## 5. Inventory, shipment and software accountability

### The decisive inventory defect

`common/httpd.py` matches the **first prefix** in insertion order. In `ledger/server.py`, `GET /lots` is registered before `GET /lots/`. A request for `/lots/LN-25578` therefore invokes `get_lots`, returning `{"lots": [...]}` with HTTP 200, not the selected lot. `dispatch.apply_move` immediately accesses `cur["zone"]` and fails. Logs repeatedly record **`failed: 'zone'`**. The worker catches the exception and unconditionally sets `state='done'`.

The database confirms the operational result: **zero `moves`**, every `lots.updated_at` still at the import, 66 unchanged inventory positions. This is stronger evidence than generic speculation about a worker race. There is no evidence of successfully applied but reordered move writes in this snapshot.

### Other real failure paths, kept separate

* WMS lookup is serialized and runs **before enqueue**. A client timeout does not cancel server work. Retrying without an idempotency key can create another job; exact duplicate queue payloads exist. This needs repair, but does not explain the already-failing individual-lot reads.
* `netutil` implements deadlines on `time.time()`, not a monotonic clock. This is a robustness defect, but no surviving evidence establishes a wall-clock step as this incident's trigger.
* Billing code is missing from the checked-out working tree but survives in git. It opens an exclusive transaction and sleeps 30 seconds per lot while processing all 66 lots. Billing start/end logs and ledger/gateway errors establish prolonged writer blockage despite the nominal WAL configuration. The June 7 unit-conversion commit changes billed minutes to hours; it does **not** remove the long transaction.
* The billing exports inherit frozen locations and misdecoded temperatures. They are not independent corroboration of physical residence or safe storage.

### Product consequences and limits

* **LN-22416 / PL-6443:** ledger says B; physical records put it into E June 19 at 14:59. Customer received it June 27 and reported degradation June 30. This directly invalidates a quarantine exercise that only selected ledger-E rows. Its full residence/thermal history cannot be certified: other origin entries are inconsistent and a later physical pickup is in D without a complete intervening trail.
* **LN-25578 / PL-9143:** ledger says E; June 19 B→C and June 21 C→B physical and scanner records support C residence across the night. Its inclusion in the postmortem list is not evidence it was exposed in E. Sofia Larsen's specific move account is corroborated; her unrelated speeding warning is not relevant causal evidence.
* **LN-23197 / PL-9173:** import says D, but the first June 4 physical pickup and scanner source say C. Thus even the starting inventory contains a source error; fixing dispatch alone would not retroactively validate the import.
* **LN-21643:** a morning physical delivery into the still-warm E room is another reason not to limit review to a single static midnight inventory snapshot.
* Other physical chains, including LN-22116 and LN-28611, have gaps or origin changes that require conservative tracing. A complete authoritative exposed-lot list is **undetermined**, not reconstructed by treating every queue payload as a distinct physical move or by assuming all missing scans imply misconduct.

The evidence supports the customer's warm-exposure concern, not a product-specific potency prediction for every listed lot. An independent stability disposition and shipping-chain review remain necessary.

## 6. Attribution, contradictions and unresolved questions

**Established attribution:** Okafor was the service technician for the two-unit firmware visit; Larsen authored the routing change; Novak archived the channel; Mensah bought and earlier photographed a wedge in E; identified forklift operators made the corroborated movements; QA relied on an invalid location record. Dana Whitcombe's authorship of the partial decoder is supported by git—Larsen's claim to have inherited that code is not disproved.

**Not established:** who deployed the severity override; who left E open on the excursion night; whether the lead knew of the actual warm excursion before the lab email; exact offline temperature peak; exact intermediate moves in the blind spots. Do not convert a denial, an old purchase, a suspicious coincidence or a person's job title into an attribution.

The structured answer quotes only contradicted text, not merely unverified text. In particular, the postmortem's allegations against the agency worker and SRE are **not** listed as proven false quotations: their attribution is unproved. The firmware report, the fixed-six-hour runbook, the bench fan label, the claim of post-incident channel archival, the handheld-accuracy claim, and the categorical never-propped denial do have specific contrary evidence.

### What would settle the remaining questions

| Question | Missing discriminating evidence |
|---|---|
| Incident-night door actor | Preserved identity-bearing CCTV, working door access/key logs, or a reliable contemporaneous witnessed account. The retained motion index cannot recover overwritten footage. |
| Severity override author/time | Authenticated host/deployment audit, sudo/SSH session history, file-write audit or configuration-management records. File content and a routing commit are insufficient. |
| Exact controller trajectory and peak | Full controller ring-buffer/engineering history or independent time-synchronized logger. P1 submeter combines C and E, so unique load attribution is impossible from it alone. |
| Every exposed lot and unrecorded move | Scanner offline journals, WMS event IDs, shipping/pick manifests, contemporaneous physical counts and destination receipt records. Queue completion is not proof of successful update. |
| B/F sensor biases and exact thermal parameters | Traceably calibrated probes in those rooms and higher-frequency synchronized air, coil, ambient, door and actuator measurements. |
| Unseen SETPOINT code / exact look-back register | Correct VX-5 firmware protocol/register documentation or a controlled, independently logged bench capture. These would be future tests, not evidence already obtained here. |

## 7. Recommendations, in priority order

1. **Contain product risk now.** Suspend ledger-only releases; trace LN-22416 and subsequent E deliveries; independently inventory all rooms, reconcile manifests, and obtain QA/stability disposition for plausibly affected lots. Preserve the frozen evidence and add any authenticated shipping records before retention expires.
2. **Restore independent temperature protection.** Install calibrated independent logging/alarming and door-duration alarms; repair the reproduced E conduit/link fault. Alarm on loss of telemetry and stale values as critical conditions, independently of temperature thresholds.
3. **Fix and validate the decoder.** Handle firmware banners and ABS_TEMP; decode pressure, door, trip, lockout, defrost, heater and overflow. Maintain versioned schemas and unit tests with these raw frames. Reject unsupported firmware rather than silently assuming offsets.
4. **Repair alert governance.** Verify end-to-end human delivery to live channels; remove unjustified override; require named authenticated changes, reason, bounded scope and automatic expiry. Test missing-data and threshold-equality behavior. Document that severity and routing are different controls.
5. **Repair inventory before trusting it.** Match exact/parameterized routes before collection prefixes; test individual-lot response shape; make updates and move audit atomic; mark failed jobs failed, not done; retry safely using stable scanner event IDs and idempotency. Move WMS enrichment off the enqueue path. Rebuild location history from independent physical evidence and audit the original import.
6. **Remove telemetry dependence on long billing writes.** Use a read-only snapshot or replica; perform computation outside transactions; decouple durable telemetry receipt/ACK from downstream availability, with replay and deduplication. Use monotonic deadlines. Alert on overflow and failed writes, not just process uptime.
7. **Correct calibration and documentation.** Remove/adjust HH-2, independently recalibrate D and measure B/F, replace obsolete protocol/runbook guidance, and require before/after downstream checks on every firmware service.
8. **Improve evidence retention and accountability.** Centralize append-only deployment/audit logs, monitor clock synchronization, extend incident-preservation retention, and repair badge/telematics faults promptly. Replace the blame-centered postmortem with this multi-layer causal account and its explicit uncertainties.

## Appendix A — all 45 surviving snapshot frames

All belong to E/VX05. Temperatures are sensor engineering values, not bias-corrected room air. Sequence is the decimal **wire** sequence, not the left-hand extraction row number.

| Wire seq | UTC | Translation |
|---:|---|---|
| 3512 | 2026-06-19T22:25:00Z | STATUS: air -18.7 °C; pressure 10.9 bar; flags 0x4000; coil -19.0 °C; IDLE |
| 3513 | 2026-06-19T22:30:00Z | STATUS: air -18.9 °C; pressure 11.8 bar; flags 0xC000; coil -25.0 °C; RUN |
| 3514 | 2026-06-19T22:35:00Z | STATUS: air -19.4 °C; pressure 11.8 bar; flags 0xC000; coil -25.2 °C; RUN |
| 3515 | 2026-06-19T22:40:00Z | STATUS: air -19.6 °C; pressure 11.8 bar; flags 0xC000; coil -25.5 °C; RUN |
| 3516 | 2026-06-19T22:45:00Z | STATUS: air -19.6 °C; pressure 10.9 bar; flags 0x4000; coil -20.2 °C; IDLE |
| 3517 | 2026-06-19T22:50:00Z | STATUS: air -19.4 °C; pressure 10.9 bar; flags 0x4000; coil -19.9 °C; IDLE |
| 3518 | 2026-06-19T22:55:00Z | STATUS: air -19.5 °C; pressure 10.9 bar; flags 0x4000; coil -20.0 °C; IDLE |
| 3519 | 2026-06-19T23:00:00Z | STATUS: air -19.4 °C; pressure 11.0 bar; flags 0x4000; coil -19.9 °C; IDLE |
| 3520 | 2026-06-19T23:05:00Z | STATUS: air -19.1 °C; pressure 10.9 bar; flags 0x4000; coil -19.6 °C; IDLE |
| 3521 | 2026-06-19T23:10:00Z | STATUS: air -19.5 °C; pressure 11.0 bar; flags 0x4000; coil -20.1 °C; IDLE |
| 3522 | 2026-06-19T23:15:00Z | STATUS: air -18.7 °C; pressure 10.8 bar; flags 0x4000; coil -19.2 °C; IDLE |
| 3523 | 2026-06-19T23:20:00Z | STATUS: air -19.1 °C; pressure 11.8 bar; flags 0xC000; coil -25.3 °C; RUN |
| 3524 | 2026-06-19T23:25:00Z | STATUS: air -19.5 °C; pressure 11.8 bar; flags 0xC000; coil -25.4 °C; RUN |
| 3525 | 2026-06-19T23:30:00Z | STATUS: air -20.1 °C; pressure 11.9 bar; flags 0xC000; coil -25.7 °C; RUN |
| 3526 | 2026-06-19T23:35:00Z | STATUS: air -19.8 °C; pressure 10.8 bar; flags 0x4000; coil -20.3 °C; IDLE |
| 3527 | 2026-06-19T23:40:00Z | STATUS: air -19.8 °C; pressure 10.9 bar; flags 0x4000; coil -20.2 °C; IDLE |
| 3528 | 2026-06-19T23:45:00Z | STATUS: air -19.3 °C; pressure 10.9 bar; flags 0x4000; coil -20.1 °C; IDLE |
| 3529 | 2026-06-19T23:50:00Z | STATUS: air -19.5 °C; pressure 10.9 bar; flags 0x4000; coil -19.9 °C; IDLE |
| 3530 | 2026-06-19T23:55:00Z | STATUS: air -19.5 °C; pressure 10.9 bar; flags 0x4000; coil -20.0 °C; IDLE |
| 3531 | 2026-06-20T00:00:00Z | STATUS: air -19.0 °C; pressure 10.9 bar; flags 0x4000; coil -19.2 °C; IDLE |
| 3532 | 2026-06-20T00:05:00Z | STATUS: air -19.1 °C; pressure 11.9 bar; flags 0xC000; coil -25.2 °C; RUN |
| 3533 | 2026-06-20T00:10:00Z | STATUS: air -19.7 °C; pressure 11.9 bar; flags 0xC000; coil -26.1 °C; RUN |
| 3534 | 2026-06-20T00:15:00Z | STATUS: air -19.5 °C; pressure 11.9 bar; flags 0xC000; coil -25.5 °C; RUN |
| 3535 | 2026-06-20T00:20:00Z | STATUS: air -20.1 °C; pressure 11.0 bar; flags 0x4000; coil -20.6 °C; IDLE |
| 3536 | 2026-06-20T00:25:00Z | STATUS: air -19.6 °C; pressure 10.9 bar; flags 0x4000; coil -20.0 °C; IDLE |
| 3537 | 2026-06-20T00:27:00Z | DOOR=1 |
| 3538 | 2026-06-20T00:28:00Z | DOOR=0 |
| 3539 | 2026-06-20T00:30:00Z | STATUS: air -19.1 °C; pressure 10.8 bar; flags 0x4000; coil -19.3 °C; IDLE |
| 3540 | 2026-06-20T00:35:00Z | STATUS: air -18.8 °C; pressure 11.0 bar; flags 0x4000; coil -19.3 °C; IDLE |
| 3541 | 2026-06-20T00:38:00Z | DOOR=1 |
| 3542 | 2026-06-20T00:40:00Z | STATUS: air -18.0 °C; pressure 12.0 bar; flags 0xD000; coil -23.9 °C; RUN |
| 3543 | 2026-06-20T00:45:00Z | STATUS: air -17.3 °C; pressure 12.7 bar; flags 0xD000; coil -23.1 °C; RUN |
| 3544 | 2026-06-20T00:49:00Z | TRIP=1 |
| 3545 | 2026-06-20T00:50:00Z | STATUS: air -16.9 °C; pressure 11.0 bar; flags 0x5000; coil -17.5 °C; IDLE |
| 3546 | 2026-06-20T00:55:00Z | STATUS: air -15.5 °C; pressure 12.0 bar; flags 0xD000; coil -21.6 °C; RUN |
| 3547 | 2026-06-20T01:00:00Z | STATUS: air -14.6 °C; pressure 12.7 bar; flags 0xD000; coil -20.8 °C; RUN |
| 3548 | 2026-06-20T01:04:00Z | TRIP=1 |
| 3549 | 2026-06-20T01:05:00Z | STATUS: air -14.2 °C; pressure 11.0 bar; flags 0x5000; coil -14.4 °C; IDLE |
| 3550 | 2026-06-20T01:10:00Z | STATUS: air -12.7 °C; pressure 12.2 bar; flags 0xD000; coil -18.3 °C; RUN |
| 3551 | 2026-06-20T01:15:00Z | STATUS: air -12.2 °C; pressure 12.8 bar; flags 0xD000; coil -17.9 °C; RUN |
| 3552 | 2026-06-20T01:19:00Z | TRIP=1 |
| 3553 | 2026-06-20T01:20:00Z | STATUS: air -11.7 °C; pressure 11.0 bar; flags 0x5000; coil -12.1 °C; IDLE |
| 3554 | 2026-06-20T01:25:00Z | STATUS: air -10.7 °C; pressure 12.3 bar; flags 0xD000; coil -16.6 °C; RUN |
| 3555 | 2026-06-20T01:30:00Z | STATUS: air -9.8 °C; pressure 12.8 bar; flags 0xD000; coil -15.9 °C; RUN |
| 3557 | 2026-06-20T01:34:00Z | LOCKOUT=1 |

Sequence 3556 is absent from the supplied snapshot. No translation entry has been invented for it.

## Appendix B — exact contradicted quotations

* **doc:postmortem**: “Root cause: compressor failure on controller VX05.”
* **doc:postmortem**: “The failure caused the room E setpoint to drift upward over several hours without triggering an audible or dispatched alarm to any on-shift personnel.”
* **doc:service_report_firmware_visit**: “Unit VX05 (room E): inspected only, no changes made”
* **doc:bench_report_unit01**: “message type 0xbd: condenser fan”
* **doc:runbook**: “Defrost runs on a fixed schedule every 6 hours per room; the rooms take turns so the heaters never overlap.”
* **doc:temp_worker_m.mensah**: “I deny propping any cold-room door, ever.”
* **doc:temp_worker_m.mensah**: “I never used that wedge or anything else on room E or any other room door.”
* **doc:warehouse_manager_p.novak**: “room E and room C aren't rooms I'm walking every day with that unit.”
* **doc:warehouse_manager_p.novak**: “I archived the old alert channel only after the incident”
* **doc:receiving_clerk_p.dubois**: “My handheld was calibrated last month and reads fine”
* **doc:night_lead_h.tanaka**: “I came on shift at about 9:38 pm on Fri 19 Jun, together with the agency worker Maya Mensah”
* **doc:night_lead_h.tanaka**: “all the rooms were closed and nobody went near room E after that.”
* **doc:ops_engineer_m.larsen**: “the -40 readings are a known sensor fault on the 3.4 boards”
