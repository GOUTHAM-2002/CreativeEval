# Independent findings: Glacier Bay Storage, JPS45

## Executive conclusion

**The official postmortem does not establish either its initiating cause or its named culprit.** The best-supported reconstruction is a door-associated heat load in room E, repeated controller protection trips, and a timed lockout—not a compressor that permanently lost cooling capacity. Multiple independent monitoring and inventory failures then obscured the excursion and misdirected containment.

The evidence establishes a **00:48 UTC door opening on March 26**, four subsequent trip telegrams, and **01:45 lockout**. At **04:10**, when telemetry was again available, the controller reported **+5.19°C**, approximately **+5.6°C after its baseline sensor-bias correction**. It subsequently cooled. The exact unobserved peak and the person responsible for the incident opening are not established.

Both B and E had been upgraded to firmware 3.4. The gateway interpreted their new absolute temperatures as offsets from already-negative setpoints, generating falsely cold readings. Routing changes, a separate severity override, lack of a stale-data alarm, recurring database contention, and a pre-existing door-related communications fault weakened detection further.

The ledger is not a reliable record of physical inventory movement. Its recovered `moves` table is empty, and all 62 lot locations remain at their original import positions. The prolonged overnight E cohort reconstructed from physical movement records is **LN-24754, LN-28604 and LN-26450**. None appears on the postmortem's five-lot list. **LN-25885** entered E during the recovery tail and also needs assessment, without being assigned the overnight lots' much longer exposure.

These are cold-room air and custody findings, **not a pharmaceutical release decision or proof that every exposed lot lost potency**.

## 1. Evidence handling and time reconstruction

I compared both rotations of the service logs, the raw telegrams rather than just decoded database columns, both SQL dumps, deployed code and git history, and independent physical records. Analyses and a complete structured translation are in `/work/answer.json`. No services were re-run and no new external evidence was obtained; calculations operated only on the frozen records.

Offsets below mean **recorded clock minus true UTC**. Icelandic site time is UTC year-round.

| Channel | Offset, minutes | Basis and limits |
|---|---:|---|
| Gateway | 0 | Normal receipt times align with controller counters and independent events. Transmission delay is not clock offset. |
| Forklift | 0 | Repeated scanner/door event agreement, including the independently corroborated March 27 FL-1 move. |
| Badge | −16 | Repeated room-access matches to forklift activity and probe rounds. Add 16 minutes. |
| Probe sheet | −8 | Badge/probe cross-matches and best alignment of calibrated readings to telemetry. Add 8 minutes; database entry time is later still. |
| EXIF local camera time | +60 | GPS anchors in IMG_2201, IMG_2207 and IMG_2250; photo/chat timing provides another check. Subtract one hour. Captions are not infallible. |
| CCTV motion index | approximately +2 | Statistical alignment of retained corridor motion with door activity; jitter makes this less certain than the badge correction. It does not recover expired footage. |
| Chat, tickets, git, submeter | 0 | No systematic offset supported by cross-record comparisons. Human text inside these channels can still quote inaccurate times. |

Controller ticks advance in **minutes**. For the incident TK05 epoch, `true UTC = 2026-03-15 14:41 + tick minutes`. The firmware banner and matching snapshot/gateway frames anchor this translation. The fault snapshot is not undated merely because its tick field is not a wall clock.

At the March 14 power return, boot telegrams were received around 11:19, but subsequent tick/receipt pairs establish a **true 11:11 boot epoch**. Treating every receive timestamp as the time a telegram was generated would manufacture a clock error.

### Three different kinds of missingness

1. **Recurring billing contention:** service logs often retain raw frames that the ledger could not store. A ledger-only analysis loses these observations.
2. **TK05 overnight link loss:** no continuous upstream record survives between 00:48 and 04:08 on March 26. The local snapshot recovers only part of it.
3. **March 26 12:05–15:17 disk-full service-log gap:** this is **not a complete evidentiary blackout**. The ledger retains **231 raw readings absent from the gateway log**, including E's near-setpoint cycling and a door opening at 15:14. Sofia Nguyen's assertion that nothing was written down overstates the loss.

Sources: `deploy/logs/*`, `db/ledger.sql`, `people/tickets.json`, `people/badge_access.csv`, `people/probe_checks_sheet.csv`, `people/photos_exif.csv`, `people/forklift_telematics.csv`, `people/cctv_motion.csv`.

## 2. What happened physically

### Chronology of the incident

| True UTC | Established observation or carefully limited inference |
|---|---|
| March 25, before the night shift | FL-1 delivered LN-28604 to E at 10:29 and LN-24754 at 11:58. FL-2 delivered LN-26450 to E at 16:33 after an F→C→E transfer. |
| March 25, 21:49 / 22:03 | Badge-corrected main-entrance arrivals of Elif Dubois / Noor Costa respectively. Presence is not proof of the later door action. |
| March 25, 22:30–March 26, 00:45 | Snapshot and gateway show ordinary E thermostat cycling near −22 to −21°C. The night lead's approximately 23:18 normal-temperature walk-through is not contradicted by this evidence. |
| March 26, 00:48 | E door opens, snapshot sequence 3240 (`29 0001`). The gateway receives this opening before the long link loss. |
| 00:57, 01:09, 01:21, 01:33 | Four surviving `67 0001` trip telegrams, interspersed with warming and compressor off/on statuses. These are not defrost starts. |
| 01:40 | Snapshot air temperature is −8.69°C, already substantially warm. |
| 01:45 | `55 0001` lockout, sequence 3257. Sequence 3256 is absent. A fifth trip is inferred from the independently observed lockout rule, not inserted as a recovered frame. |
| Approximately 03:15 | A 90-minute lockout would expire here. The shared P1 meter's change is consistent with renewed cooling, but the missing E clear telegram is not claimed as directly observed. |
| 04:08 | TK05 link resumes with `3A 0035`, an overflow/loss count of 53. Closure around this time is the best explanation given the known conduit fault and subsequent closed-door flags; the actual close telegram is missing. |
| 04:10 | Air +5.19°C, RUN, door-open flag clear. The faulty gateway reports approximately −16.5°C instead. The old low-temperature alert clears at 04:10:27. No correct high-temperature alarm results. |
| 05:57 / 06:04 | Badge-corrected departures of Dubois / Costa. |
| 07:42–08:08 | A genuine defrost/heater cycle interrupts recovery and adds heat. This is separate from the earlier trips. |
| 08:20–08:22 | Ana Novak picks LN-26450 from E and drops it in F. This contradicts a claim that nobody approached E after the night lead left. |
| 09:07 | LN-25885 is delivered to E during the warming/recovery tail. |
| About 09:20–09:25 | Bias-corrected sampled E air temperatures cross back through approximately −15°C; ordinary near-setpoint cycling resumes later in the morning. The exact product temperature is unknown. |
| 10:37 | Jonas Nguyen's HH-1 E check, device timestamp 10:29, reads −19.6°C. This is after the prolonged warm period and cannot retrospectively clear it. |

The first several minutes of the event are directly recovered. Seven minutes of concurrent open-door/compressor operation commonly precede a trip; if the compressor is initially idle, the first trip can occur later than seven minutes after opening. Repeated examples in B and D identify approximately five trips in an hour as the lockout trigger and a 90-minute lockout duration. E's air rises during protection cycling and lockout, then falls during sustained running afterward.

### Why this is not the postmortem's compressor-failure story

* The unit was cycling normally before the opening; the snapshot identifies protection events, not an unexplained permanent stop.
* Post-event RUN statuses, coil/air separation and sustained cooling show cooling capacity was subsequently available.
* The recall is for **NK-450S/NK-450SX, serials 7A…**. The site note explicitly identifies **NK-380, serials 5B…**, outside the recall. It is not evidence of a TK05 defect or product-lot recall.
* The short **March 14 10:49–11:11** utility interruption precedes the incident by nearly twelve days. Controller resets and subsequent recovery are visible; it does not establish a continuing March 26 supply failure.

An intermittent mechanical issue cannot be universally excluded without inspection data. What is refuted is the confident assertion that the surviving record demonstrates an initiating permanent compressor failure.

### Door attribution: a necessary distinction

Receipt, photo metadata/caption and March 16 chat support prior wedge use by Costa: the photo's corrected time is **00:40**, a post follows at 00:45, Dubois objects to something breaking the seal, and Costa says she is moving it. This undermines her blanket denial of ever propping a door.

It **does not identify the person responsible for March 26**. ROOM-E's badge reader was offline, incident-week CCTV was overwritten, and a controller door contact contains no identity. Costa, Dubois, another entrant, or a different person leaving a previously opened door unsecured remain competing possibilities. A prior act is not sufficient evidence of this act.

Ticket **T-0410** records a reproduced link failure when E's door is fully against the wall, attributed to pinched conduit wiring and deferred repair. Its relation to the 00:48–04:08 silence is much stronger than a theory that the silent controller was safely at its last reported temperature.

## 3. Why monitoring did not protect the shipment

### Firmware compatibility failure

Raw `BA 0034` banners establish TK05/E's successful 3.4 reboot at **March 15 14:41**, and TK02/B's at **15:33**. Visitor access, the two-unit service invoice, and subsequent bit-14 status words corroborate the work. The firmware service report's “inspected only” statement about TK05 is false.

In 3.2, the air and coil words represent a temperature difference from the configured setpoint. In 3.4 they represent an **absolute temperature**, with the same numerical scale/offset and a distinguishing flag. `gateway/rh7_decode.py` always adds the configured setpoint. Thus E's displayed temperature is approximately **21.7°C too cold**, and B's **18.1°C too cold**. The −40°C dashboard values are explained without a defective temperature sensor.

The decoder also discards coil temperature, pressure, door, trip, lockout, recovery and defrost semantics. Treating every non-status frame as a generic dispatch activity event does not create a safety alarm.

### Three distinct alerting changes or omissions

1. **Ivan Novak's `1a83340`, March 16 12:19:13:** changes the B/E **zone channels**, not severity thresholds. Because channel selection is per-zone, **critical as well as warning** alerts use the legacy destination. Alerting reloads it at 12:19:15.
2. **Jonas Nguyen's March 17 10:03 archive:** admitted in chat, before the excursion—not afterward as his statement says. Archived-channel posts are accepted but unseen.
3. **Untracked critical-only override:** `deploy/config.override.json` contains `ALERT_MIN_SEVERITY: critical`; config layering and suppression logs establish its effect. The surviving evidence does **not establish its author or exact deployment time**. Sofia's frustration is evidence of frustration, not deployment. Ivan's route-only diff neither proves nor disproves a separate untracked action.

Even perfect routing would not correct falsely cold readings. Conversely, fixing the decoder alone would leave routing and freshness defects in place.

The gateway posts `controller_stale` events and reports stale IDs from its health endpoint. Alerting, however, reads **only latest temperature rows**, without a freshness test and without consuming those events. There is no independent stale-controller notification path in the recovered implementation.

### Shared-database and deployment failures

Billing takes `BEGIN EXCLUSIVE` and holds the writer transaction while scanning 62 lots, including a 30-second per-lot sleep in the git version. The observed nightly jobs last roughly 31–45 minutes from 01:00. Ledger insert failures, gateway write failures and unacknowledged frames recur in those intervals. WAL does not make this writer transaction harmless; the logs show the actual contention. The controller link does not resend missed frames.

The billing working-tree files are absent from this snapshot; the relevant implementation remains available in git and must not be confused with a verified live binary. This deployment distinction matters elsewhere too: `a99c183` introduced minutes-as-hours, and `37f6e9e` fixes that expression in git, yet later exports still bill **1440 hours rather than 24**. That is a 60-fold unit error, not evidence of longer physical exposure.

Sources: gateway, alerting, ledger, common HTTP/config and dispatch source; git history; both log rotations; billing exports; tickets; chat. No undisclosed deployment audit has been presumed.

## 4. Inventory reconstruction and product scope

### A concrete failure, not just a vague race condition

`common/httpd.py` dispatches the first matching URL prefix. In the ledger route map, GET `/lots` precedes GET `/lots/<id>`. A request for a specific lot therefore returns the collection object, with a `lots` field but **no top-level `zone`**. `dispatch.apply_move` then raises `KeyError('zone')` before reaching the update.

The dispatch worker catches that exception and still sets the job's state to **done**. Thousands of matching errors, zero `moves` rows and unchanged import timestamps confirm the failure in the recovered runtime. A `202 queued` response to a handheld, or a `done` dispatch row, is not proof of a successful location update.

The pipeline has additional defects: slow, serialized WMS lookup before enqueue/response; a single gateway notification worker; timeout/retry without idempotency; and no atomic compare-and-update protection in the later move path. The queue contains repeated identical payloads with distinct job IDs. These are genuine reliability defects, but I do **not** claim a successful out-of-order replay overwrote lot positions in this run: the observed failure occurs earlier.

### Cohort supported by physical records

| Lot | E custody evidence relevant to this event | Assessment |
|---|---|---|
| **LN-28604 / PL-6184** | A pickup March 25 10:27; E delivery 10:29 | Overnight E cohort; ledger incorrectly says F. |
| **LN-24754 / PL-7664** | A pickup March 25 11:57; E delivery 11:58 | Overnight E cohort; ledger incorrectly says D. |
| **LN-26450 / PL-8620** | F→C→E March 25 16:30–16:33; E pickup March 26 08:20; F delivery 08:22 | Overnight cohort; lab-flagged lot; ledger incorrectly remains F. |
| **LN-25885 / PL-3681** | Delivered E March 26 09:07 | Recovery-tail exposure; shorter and not interchangeable with overnight exposure. |

No overnight removal is present for the first three. Scanner records agree with the relevant physical entries. Later FL-2 gaps limit precise reconstruction of some subsequent departures; that does not erase the documented pre-incident E deliveries.

The five postmortem lots had already moved elsewhere: **LN-24872→A; LN-26219→D; LN-26259→D; LN-28595→F; LN-29864→D**. The QA manager may indeed have quarantined every lot the *ledger* showed in E. That does not make the ledger-derived set the *physical* exposure set. Other events in those rooms may require separate assessment; “not in E that night” is not a general release authorization.

### Two operator statements deserve different treatment

* **Ana Novak, PL-1904/LN-22738, March 27:** FL-1 independently records F pickup **07:32** and B drop **07:34**, matching the scanner report. Job `967059da522f` fails with `'zone'` at 07:32:44. Her statement is corroborated; the speeding note is irrelevant to whether this move happened.
* **Ingrid Schulz, PL-9519/LN-25934, March 27:** the F→D scanner submission around **19:14** and failed job `84ed7f216f71` survive. FL-2's telematics is absent and the pertinent CCTV is expired. The actual physical completion remains **undetermined**, not refuted by the stale ledger and not established solely by the scan.

The lab describes a signature **consistent with** hours above −15°C. The reconstructed E exposure fits that account. The evidence does not establish exclusive causation, product-core temperature, or potency loss in every other lot; their wider room/transport histories and validated stability limits are also relevant.

## 5. Refrigeration/controller model

The approximate model used for estimates separates compressor cooling, ambient leakage multiplied by door state, shared-wall heat transfer and defrost heat:

`dT/dt ≈ −k_cool × RUN + k_leak × (ambient−T) × door_multiplier + c_adj × Σ(neighbour−T) + defrost_heat/26 while defrosting`.

Decoded temperature is sensor temperature. Bias below means **sensor minus independent true temperature**. Fits use state-conditioned slopes and ambient submeter measurements, exclude ambiguous state transitions where possible, and treat D's changing offset separately. These are effective estimates from noisy, mostly five-minute observations—not precisely recovered controller configuration values.

| Room | k_cool, °C/min | k_leak, /min | H, °C | Baseline bias, °C |
|---|---:|---:|---:|---:|
| A | 0.185 | 0.00160 | 0.6 | −0.6 |
| B | 0.060 | 0.00068 | 1.0 | −0.8 |
| C | 0.031 | 0.00133 | 1.1 | **Not established** |
| D | 0.113 | 0.00073 | 0.6 | −1.1, before additional drift |
| E | 0.115 | 0.00127 | 0.7 | −0.4 |
| F | 0.030 | 0.00155 | 0.7 | **Not established** |

Here H denotes an empirical **half-band**: start near setpoint+H, stop near setpoint−H. Sampling delay and measurement noise make raw first-RUN/first-IDLE temperatures imperfect threshold estimates.

Other estimates:

* Door leakage multiplier: **approximately 7.5**; shared-wall coefficient **approximately 0.00028/min**. These are less tightly identified than cooling rates.
* Defrost: approximately **8 accumulated compressor-running hours**, with shared scheduling delaying requests; **26-minute** cycles; approximately **3.7°C** additional heater contribution per cycle. All 200 surviving paired start/end cycles are 26 minutes. The record does not support a six-hour wall-clock cycle in each room.
* No overlapping recovered defrost/heater intervals. A **complete fixed priority/stagger order is not confidently recovered**; event order is also affected by readiness and gaps. I have not inserted a guessed permutation in the structured rules.
* Trip: commonly after **7 minutes** of simultaneous open-door/running operation. Repeated open-door trip cycles are commonly 12 minutes apart, consistent with a short hold-off before renewed running.
* Lockout: **5 trips**, approximately **60-minute rolling window**, **90-minute duration**. The surviving positive/negative examples bound the rolling-window cutoff to roughly 56–62 minutes; 60 is an estimate, not a recovered configuration register.
* Thermal neighbours from the floor plan: **B–C, C–D, E–F, F–A, B–E, C–F, D–A**, plus the old **A–E** pass-through wall. Electrical panel pairing is a different relation: P1=A/E, P2=C/F, P3=B/D.

### Separate D sensor and handheld issues

HH-1's calibration reference offset is zero. HH-2's certificate records **+1.1°C and OUT OF TOLERANCE**, with removal/adjustment recommended. Its readings must be reduced by 1.1°C before use as a reference.

Corrected probe comparisons indicate A/B/E's baseline offsets and D's baseline near −1.1°C. D then acquires approximately **+3.1°C additional drift**, followed by an April 3 reset toward baseline. This is separate from B/E's firmware-format error and from E's door/lockout event. The trend contradicts the ticket's description of HH-2 becoming increasingly warmer than the panel.

Neither probe round samples C or F. Their absolute biases are therefore `null` in the structured answer. Electricity and the controller's own sensor are not independent calibration references.

## 6. Recovered wire protocol

Framing is LF-terminated printable ASCII:

`$<unit>,<seq>,<tick>,<type>,<16-bit hex words>*<checksum>`

Sequence and tick fields are six hexadecimal digits; sequence resets on reboot. The checksum is the sum of ASCII bytes between `$` and `*`, modulo 256. Fault-snapshot checksums agree. Tick units are minutes, identified from matched traffic—not assumed from the obsolete manual.

| Type | Meaning | Observed payload |
|---|---|---|
| `56` | STATUS | Four words, described below |
| `29` | DOOR | 1 open, 0 closed |
| `67` | TRIP | 1 trip; associated with protection cycling |
| `55` | LOCKOUT | 1 enter, 0 clear |
| `EB` | DEFROST | 1 start, 0 end |
| `11` | HEATER | 1 on, 0 off; tracks defrost |
| `BA` | BOOT/firmware banner | `0032` = 3.2; `0034` = 3.4, not decimal firmware 50/52 |
| `3A` | QUEUE_OVERFLOW | Lost/overflow frame count |

No SETPOINT opcode is identified in the surviving traffic; none has been invented.

Status layout: **w0 coil temperature; w1 air temperature; w2 flags; w3 discharge pressure**. Temperature scaling is `(word−500)/16`; add the zone setpoint on 3.2, not on 3.4 when ABS_TEMP is set. The fourth word behaves as discharge pressure, but **its absolute engineering unit and divisor are not independently established**. The old note refers to a compressor data sheet that is absent. For example, 1140 could mean 114 units at scale 10 or 11.4 at scale 100; pressure/state correlations cannot distinguish a change of units. Accordingly, `press_scale` is omitted and engineering pressure values are `null` in the structured translation. The appendix retains the exact raw pressure words rather than inventing units.

Flag bit positions: **RUN 6, DEFROST 13, LOCKOUT 7, RECOVERY 3, DOOR_OPEN 10, ABS_TEMP 14**. Idle is the absence of RUN, not a separate wire bit. The old TK-7 card's pressure/coil positions and event opcodes must not be applied to this TK-5. The bench report's second “defrost” code is contradicted by the trips' one-way payloads, cycling, pressure behaviour and eventual lockout.

The appendix below translates **every one of the 45 surviving snapshot frames**. `answer.json` additionally represents all four status quantities as separate entries sharing the sequence and event timestamp. It does not interpolate a missing sequence.

## 7. Statements disproved, versus allegations not settled

The exact quotations are maintained in `answer.json`. Principal disproved propositions are:

* Postmortem: “Root cause: compressor failure on controller TK05.” The asserted initiating permanent failure is not what the recovered protection/cooling sequence shows.
* Firmware service report: “Unit TK05 (room E): inspected only, no changes made”. Its 3.4 boot and format change contradict this.
* Warehouse manager: “I archived the old alert channel only after the incident, once I was confident nothing further needed to come through it.” His March 17 chat admission predates the incident.
* Costa: “I have never propped open any cold-room door.” The earlier wedge evidence contradicts this blanket claim, not necessarily her innocence regarding the incident-night opening.
* Receiving clerk: “My handheld was calibrated last month and reads fine”. Calibration records say out of tolerance, not fine.
* Night lead: “nobody went near room E after that”. The next morning's FL-1 pickup contradicts that assertion.
* Bench report: “0x67: defrost cycle”; runbook: “Defrost runs on a fixed schedule every 6 hours per room”. Both conflict with the recovered controller behaviour.
* T-0421: “HH-2 reads warmer than the panel on room D by more and more each day.” Corrected longitudinal measurements show the opposite developing relation.
* On-call statement: “there's simply nothing written down for it.” The midday disk-full interval retains ledger readings despite missing service logs.

**Not classified as disproved:** the two engineers' denials of deploying the severity override, the identity of the incident door opener, Ingrid's physical move completion, or the night lead's normal earlier walk-through. Unsupported accusations are not converted into proven lies. Discrepancies between publication dates, ticket comments and photo captions also do not justify inventing an exact quarantine/publication instant.

## 8. What would settle the remaining questions

| Unresolved issue | Competing possibilities / evidence needed |
|---|---|
| Incident door actor and intent | Costa, Dubois or another entrant; opening versus leaving open may involve different people. Need actual incident-week access/CCTV evidence or independently corroborated contemporaneous records. These are not in this snapshot. |
| Severity override author/time | Either named engineer or another host administrator. Need shell/session, configuration-management, file audit or deployment records attributable to a person. Git route authorship does not substitute. |
| Overnight peak and full hidden thermal path | Different door/reopening/heat-input histories can share the surviving endpoints. Need continuous independent room/product logger data or a longer controller record. The two-room P1 sum is not a unique per-room reconstruction. |
| Ingrid's March 27 movement | Correct physical move with failed database update versus an incomplete/wrong scan. Need FL-2 trail, pallet custody evidence or retained video of the move. |
| Exact thermal settings / arbitration order | Effective statistical estimates versus precise configuration. Need controller parameter export, firmware scheduler documentation and controlled engineering acceptance tests. |
| C/F absolute sensor bias | Zero or nonzero constant offset. Need calibrated independent room reference readings. |
| Product disposition | Warehouse exposure alone versus additional storage/transit contributions, and different susceptibility across lots. Need full custody temperatures, product loggers, validated stability data and lot-specific QA assessment. |

## 9. Recommendations, in priority order

1. **Contain by reconstructed custody, not current ledger location.** Trace and hold the three overnight lots and assess LN-25885's shorter recovery-tail exposure. Reconcile customer shipments, testing and all subsequent custody. Do not automatically release the original five holds solely because they were elsewhere that night.
2. **Restore independent safety monitoring.** Repair E's door-conduit link; use independent calibrated room/product loggers and audited door-open/stale-data alarms. Treat absent data as a safety condition, not a normal last-known value.
3. **Make the decoder firmware-aware.** Validate checksum, word layout, absolute/relative flag and every safety state against captured frames, including this snapshot. Retain raw data and firmware identity, and gate firmware changes on end-to-end compatibility tests.
4. **Restore and test notification paths.** Route B/E to staffed channels, remove the maintenance override under controlled change, test warning/critical/stale/controller-fault delivery and acknowledgement, and alert on archived destinations. Record attributable config changes and expiry for overrides.
5. **Repair inventory semantics before trusting another reconciliation.** Fix URL dispatch specificity; add API contract tests; fail jobs honestly; persist and deduplicate moves; apply location changes transactionally with ordering/version checks. Rebuild custody from corroborated scans/telematics rather than blindly replaying duplicates.
6. **Remove billing from the safety write path.** Use a consistent read snapshot/replica, no long writer lock or sleeps in a transaction, bounded work, monotonic deadlines and durable ingestion before acknowledgements. Verify actual deployment and correct the 60-fold billing error separately.
7. **Restore evidence quality.** Retire/adjust HH-2, expand reference rounds to all rooms, verify D after calibration, repair FL-2 and access readers, synchronize clocks and monitor drift. Send logs/audits off-host and size retention for investigations rather than seven days only.
8. **Replace the postmortem with this bounded causal account.** Separate proven acts, system design defects, inferred mechanisms and genuinely unknown attribution. Do not make a disciplinary finding against either the agency worker or on-call engineer on the present evidence alone.

## Appendix — complete TK05 snapshot translation

Temperatures are controller-sensed °C, before the approximately −0.4°C E baseline bias correction. Pressure is shown as raw counts because its engineering scaling is unresolved. Times are true UTC. `ABS`=bit 14; `RUN`=bit 6; `DOOR`=bit 10. Absence of RUN means idle/off, not proof of a mechanical failure.

| Seq (hex / decimal) | UTC | Translation |
|---|---|---|
| 000C8C / 3212 | 2026-03-25T22:30:00Z | STATUS: coil -21.0000°C; air -20.8750°C; pressure raw 1050; flags 0x4000 (ABS, IDLE) |
| 000C8D / 3213 | 2026-03-25T22:35:00Z | STATUS: coil -27.3750°C; air -21.5000°C; pressure raw 1140; flags 0x4040 (ABS, RUN) |
| 000C8E / 3214 | 2026-03-25T22:40:00Z | STATUS: coil -27.6875°C; air -21.6875°C; pressure raw 1150; flags 0x4040 (ABS, RUN) |
| 000C8F / 3215 | 2026-03-25T22:45:00Z | STATUS: coil -28.6875°C; air -22.1875°C; pressure raw 1130; flags 0x4040 (ABS, RUN) |
| 000C90 / 3216 | 2026-03-25T22:50:00Z | STATUS: coil -27.6875°C; air -22.0000°C; pressure raw 1140; flags 0x4040 (ABS, RUN) |
| 000C91 / 3217 | 2026-03-25T22:55:00Z | STATUS: coil -22.8125°C; air -22.6250°C; pressure raw 1040; flags 0x4000 (ABS, IDLE) |
| 000C92 / 3218 | 2026-03-25T23:00:00Z | STATUS: coil -22.3125°C; air -22.1250°C; pressure raw 1040; flags 0x4000 (ABS, IDLE) |
| 000C93 / 3219 | 2026-03-25T23:05:00Z | STATUS: coil -22.6875°C; air -21.8750°C; pressure raw 1040; flags 0x4000 (ABS, IDLE) |
| 000C94 / 3220 | 2026-03-25T23:10:00Z | STATUS: coil -21.8750°C; air -21.5000°C; pressure raw 1050; flags 0x4000 (ABS, IDLE) |
| 000C95 / 3221 | 2026-03-25T23:15:00Z | STATUS: coil -22.1875°C; air -21.6875°C; pressure raw 1050; flags 0x4000 (ABS, IDLE) |
| 000C96 / 3222 | 2026-03-25T23:20:00Z | STATUS: coil -21.3750°C; air -21.1250°C; pressure raw 1040; flags 0x4000 (ABS, IDLE) |
| 000C97 / 3223 | 2026-03-25T23:25:00Z | STATUS: coil -27.3750°C; air -21.3125°C; pressure raw 1130; flags 0x4040 (ABS, RUN) |
| 000C98 / 3224 | 2026-03-25T23:30:00Z | STATUS: coil -27.3750°C; air -21.3750°C; pressure raw 1140; flags 0x4040 (ABS, RUN) |
| 000C99 / 3225 | 2026-03-25T23:35:00Z | STATUS: coil -27.3750°C; air -21.3750°C; pressure raw 1150; flags 0x4040 (ABS, RUN) |
| 000C9A / 3226 | 2026-03-25T23:40:00Z | STATUS: coil -27.8750°C; air -22.1250°C; pressure raw 1140; flags 0x4040 (ABS, RUN) |
| 000C9B / 3227 | 2026-03-25T23:45:00Z | STATUS: coil -22.8125°C; air -22.3750°C; pressure raw 1050; flags 0x4000 (ABS, IDLE) |
| 000C9C / 3228 | 2026-03-25T23:50:00Z | STATUS: coil -22.1250°C; air -21.8750°C; pressure raw 1050; flags 0x4000 (ABS, IDLE) |
| 000C9D / 3229 | 2026-03-25T23:55:00Z | STATUS: coil -22.6250°C; air -22.3750°C; pressure raw 1050; flags 0x4000 (ABS, IDLE) |
| 000C9E / 3230 | 2026-03-26T00:00:00Z | STATUS: coil -21.3750°C; air -21.3125°C; pressure raw 1040; flags 0x4000 (ABS, IDLE) |
| 000C9F / 3231 | 2026-03-26T00:05:00Z | STATUS: coil -22.6250°C; air -21.6875°C; pressure raw 1050; flags 0x4000 (ABS, IDLE) |
| 000CA0 / 3232 | 2026-03-26T00:10:00Z | STATUS: coil -21.6250°C; air -21.1250°C; pressure raw 1050; flags 0x4000 (ABS, IDLE) |
| 000CA1 / 3233 | 2026-03-26T00:15:00Z | STATUS: coil -27.3750°C; air -21.3125°C; pressure raw 1140; flags 0x4040 (ABS, RUN) |
| 000CA2 / 3234 | 2026-03-26T00:20:00Z | STATUS: coil -27.3125°C; air -21.1875°C; pressure raw 1140; flags 0x4040 (ABS, RUN) |
| 000CA3 / 3235 | 2026-03-26T00:25:00Z | STATUS: coil -28.1250°C; air -22.0000°C; pressure raw 1130; flags 0x4040 (ABS, RUN) |
| 000CA4 / 3236 | 2026-03-26T00:30:00Z | STATUS: coil -28.3125°C; air -22.3750°C; pressure raw 1140; flags 0x4040 (ABS, RUN) |
| 000CA5 / 3237 | 2026-03-26T00:35:00Z | STATUS: coil -22.3750°C; air -21.8125°C; pressure raw 1050; flags 0x4000 (ABS, IDLE) |
| 000CA6 / 3238 | 2026-03-26T00:40:00Z | STATUS: coil -22.6250°C; air -22.1250°C; pressure raw 1050; flags 0x4000 (ABS, IDLE) |
| 000CA7 / 3239 | 2026-03-26T00:45:00Z | STATUS: coil -22.1250°C; air -21.3750°C; pressure raw 1050; flags 0x4000 (ABS, IDLE) |
| 000CA8 / 3240 | 2026-03-26T00:48:00Z | DOOR = 1 |
| 000CA9 / 3241 | 2026-03-26T00:50:00Z | STATUS: coil -27.0000°C; air -21.1250°C; pressure raw 1160; flags 0x4440 (ABS, RUN, DOOR) |
| 000CAA / 3242 | 2026-03-26T00:55:00Z | STATUS: coil -25.6875°C; air -19.3750°C; pressure raw 1220; flags 0x4440 (ABS, RUN, DOOR) |
| 000CAB / 3243 | 2026-03-26T00:57:00Z | TRIP = 1 |
| 000CAC / 3244 | 2026-03-26T01:00:00Z | STATUS: coil -18.6250°C; air -18.0000°C; pressure raw 1070; flags 0x4400 (ABS, IDLE, DOOR) |
| 000CAD / 3245 | 2026-03-26T01:05:00Z | STATUS: coil -22.8750°C; air -17.0000°C; pressure raw 1200; flags 0x4440 (ABS, RUN, DOOR) |
| 000CAE / 3246 | 2026-03-26T01:09:00Z | TRIP = 1 |
| 000CAF / 3247 | 2026-03-26T01:10:00Z | STATUS: coil -15.6250°C; air -15.0000°C; pressure raw 1060; flags 0x4400 (ABS, IDLE, DOOR) |
| 000CB0 / 3248 | 2026-03-26T01:15:00Z | STATUS: coil -20.1875°C; air -14.1875°C; pressure raw 1180; flags 0x4440 (ABS, RUN, DOOR) |
| 000CB1 / 3249 | 2026-03-26T01:20:00Z | STATUS: coil -19.6875°C; air -13.5000°C; pressure raw 1240; flags 0x4440 (ABS, RUN, DOOR) |
| 000CB2 / 3250 | 2026-03-26T01:21:00Z | TRIP = 1 |
| 000CB3 / 3251 | 2026-03-26T01:25:00Z | STATUS: coil -12.8125°C; air -12.3125°C; pressure raw 1070; flags 0x4400 (ABS, IDLE, DOOR) |
| 000CB4 / 3252 | 2026-03-26T01:30:00Z | STATUS: coil -16.6250°C; air -10.6250°C; pressure raw 1220; flags 0x4440 (ABS, RUN, DOOR) |
| 000CB5 / 3253 | 2026-03-26T01:33:00Z | TRIP = 1 |
| 000CB6 / 3254 | 2026-03-26T01:35:00Z | STATUS: coil -10.6875°C; air -10.0000°C; pressure raw 1060; flags 0x4400 (ABS, IDLE, DOOR) |
| 000CB7 / 3255 | 2026-03-26T01:40:00Z | STATUS: coil -14.6250°C; air -8.6875°C; pressure raw 1200; flags 0x4440 (ABS, RUN, DOOR) |
| 000CB9 / 3257 | 2026-03-26T01:45:00Z | LOCKOUT = 1 |

**Missing sequence:** 000CB8 / 3256 is not present in the 45-entry export. No fabricated frame is included.
