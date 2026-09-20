# Independent incident reconstruction
## Polaris Pharma Logistics — NGN54

**Scope:** frozen evidence for March 15–April 14, 2026. All times below are UTC. This investigation uses the deployed source, Git history, both log rotations, database dumps, controller snapshot, and independent physical records. It does not treat the company postmortem, a queue job marked `done`, or a dashboard temperature as an authoritative account of physical events.

## 1. Executive findings

**There was a substantial, real warm excursion in E. The best-supported mechanism is an open door, repeated high-pressure protective trips, and timed compressor lockout—not the postmortem's unsupported compressor-failure/recall explanation.** Monitoring then concealed the excursion through a firmware/parser mismatch, missing telemetry, inadequate stale-data alarming, and degraded alert delivery. Separately, a deterministic inventory API defect meant QA's otherwise literal ledger-based quarantine missed the laboratory-flagged lot and seven other exposed lots.

The investigation does **not** establish who held the incident door open or who wrote the severity override. Prior wedge use is evidence about an earlier episode, not identification of the later culprit. Being the on-call SRE is not evidence of deploying an untracked file.

The principal conclusions are:

1. **Physical event:** E's door opened at **March 31 00:46**. VX05's retained snapshot shows trips at **00:53, 01:05, 01:17, 01:29 and 01:41**, followed immediately by lockout. Local controller records survive even though these frames did not reach the gateway.
2. **Communications loss:** E's stream disappeared after the door edge and returned about **04:45**. A door-position-dependent cable defect had already been reproduced and deferred in T-0434. At return, E was still locked out, but the door-open flag was clear. Cooling restarted at **05:05**.
3. **Real warming:** correctly decoded air readings were **−2.0°C at 04:45** and **−1.0°C at 05:05**, not the dashboard's approximately −26.7/−25.7°C. E's sensor reads roughly 0.8°C low, so physical air was warmer still. Recovery continued into the morning. HH-1 independently measured E at **−18.6°C at 09:03**.
4. **Firmware mismatch:** E and A both changed to 3.4 on March 20. The deployed parser added their negative setpoints to already absolute temperatures. The vendor report saying E remained on 3.2 is contradicted by the controller itself.
5. **Product scope:** the supported E cohort contains **ten lots**. QA's nine-lot list overlaps it in only **two**. In particular, LN-29378 was physically delivered to E on March 29 while the ledger remained at its original A position.

**Confidence:** very high in the parser, inventory and observed state-transition findings; high in the incident mechanism; lower in continuous thermal coefficients and inference through the missing stream. Attribution and certain exact times remain unresolved.

## 2. Chronology and clocks

### Clock reconciliation

Offsets mean **record clock minus true UTC**, not a correction to add.

| Channel | Offset, minutes | Basis and limitations |
|---|---:|---|
| Badge | +9 | Repeated room unlocks align with forklift picks, probe visits and door telegrams after subtracting nine minutes. For example, March 16 E probe 09:33 corresponds to Owen's badge 09:42. |
| EXIF wall time | +60 | GPS UTC versus `DateTimeOriginal` in IMG_2201, IMG_2207 and IMG_2250. Applied as the evidenced channel correction; non-GPS captions do not themselves prove the described activity/date. |
| CCTV motion | approximately +2 | Cross-matching retained April probe/access and forklift events gives a two-minute central offset, with minute-scale motion timing scatter. A motion index is not visual identification. |
| Forklift, probe, gateway | 0 | Mutually aligned event clusters; gateway receipt seconds include transport and processing latency. |
| Chat, tickets, Git, submeter | 0 | Consistent with the UTC references: bot alert posts match machine alerts; the route commit matches its reload. Human narrative times and delayed reporting are not additional clock offsets. |

Controller `tick` is **not UTC**. It advances in minutes and resets on reboot. For the incident VX05 segment, tick zero corresponds to **March 20 14:02 UTC**. Overlapping snapshot and gateway sequence/tick pairs establish the translation independently of the claimed snapshot retrieval date. The March 18 boot telegrams were received after the power return; delayed delivery is not evidence that the gateway clock was eight minutes fast.

### Material events

| True UTC | Event and evidence |
|---|---|
| March 11 23:00 | Ana Larsen's commit `2e44b26` removes `/60.0` from billing. This is a billing change, not proof of the later alert override. |
| March 18 10:19–10:37 | Reported 18-minute utility interruption; submeter and controller reboot/reset evidence support the short outage. It predates the firmware changes and incident. |
| March 18 11:29:13 | Rafael Okafor commits billing conversion fix `6de7902`; the exports do not demonstrate that running billing picked it up. |
| March 19 15:10 | Lena Rivera buys the wedge and extension cord; receipt names reimbursement claimant. |
| March 19 22:33 | Corrected wall EXIF time of IMG_2231, captioned “door wedge under room E door.” She posts it at 22:38. At 23:22 Lena Okafor objects to it blocking the seal; at 23:25 Rivera says “my bad, moving it now.” These concern an earlier episode. |
| March 20 14:02; 14:40 | VX05/E, then VX01/A, emit BOOT `0034` and absolute-temperature status. These times locate reboot completion, not the beginning of the technician's work. |
| March 21 approximately 10:46 | Rafael's `f917296` routes A/E to the old channel; alerting logs reload at 10:46:12, Git at 10:46:13. His 11:04 chat is a later announcement. |
| March 22 11:32 | Sofia Larsen announces archiving `#alerts-coldchain-old` (m0094), before the incident. |
| March 27–April 1 | ROOM-E badge reader outage, T-0441. |
| March 29 06:41–06:46 | Elif Patel moves LN-29378/PL-3290 F→A, then A→E. The physical E drop is 06:46. Forklift and scanner/queue histories agree. |
| March 30 21:49; 21:57 | Corrected main entrance records for Lena Okafor and Lena Rivera. These are entry times, not exact payroll shift boundaries. |
| March 31 00:46 | E door opens, seq 3176, tick 15044. No individual is identified. Link closure follows at 00:47:24. |
| 00:53–01:41 | Five snapshot high-pressure trips; seq 3193 enters lockout at 01:41. |
| About 04:45 | E link reconnects at 04:44:59; 04:45 status shows door closed and lockout active. This bounds the closing time, but is not a recovered close-edge timestamp. |
| 04:48 | Type 63 reports queue overflow/drop count 67. The sequence gap and the diagnostic counter need not be treated as identical counters. |
| 05:05 | Lockout clear, followed by RUN+RECOVERY status. |
| 06:11 | Both night workers exit, after correcting badge clocks. |
| 09:03 | Sofia checks E using HH-1: −18.6°C. Controller door contact independently confirms the visit. |
| 12:03–15:11 | Separate disk-full **log** gap, T-0445. It is not a total evidence blackout: **230 raw reading rows survive in the ledger** during this interval. |
| April 1 11:36 onward | PL-5665/LN-23201: FL-1 records F→A then A→C; scanner claims are independently supported. Telemetry's pick/drop timestamps overlap by minutes, so they should not be polished into invented second-by-second travel times. |
| April 1 approximately 15:06 | PL-5824/LN-25827 scanner claims D→C by Ivan Rivera. FL-2 telemetry is unavailable; the exact physical path is not independently established. |
| April 7 | C sensor recalibration, vendor report/invoice, ticket and changed probe relationship. |
| April 10 09:00 | Customer lab email/T-0448 identifies LN-29378. |
| April 10–11 | T-0448's April 10 16:00 comment says quarantine and publication; the final postmortem is dated April 11 and announced April 11 16:30. Exact publication time and physical quarantine transfer times are not independently fixed. |

The fault-snapshot retrieval date is also not securely established from captions and retrospective accounts: IMG_2250 is dated March 27, the technician says April 9, and the ticket attaches the text April 10. **None overrides the telemetry timestamps of the retained events.**

## 3. Controller protocol reconstruction

The live VX-9 protocol must not be decoded using the old VX-7 field order.

```
$unit,seq,tick,type,w0 w1 ...*cs\n
```

`seq` and `tick` are six-digit hexadecimal counters; words are four-digit hexadecimal unsigned containers. Checksum is bytewise XOR over the ASCII body between `$` and `*`, excluding both delimiters. Sequence and tick reset on reboot; tick advances once per minute. Normal status sampling is about five minutes. Receipt order is not always sequence order: snapshot seq 3181/3182 are presented in the opposite order at the same tick.

| Type | Meaning | Payload |
|---|---|---|
| 3A | STATUS | Four words, described below |
| 98 | DOOR | 1 open, 0 closed |
| D7 | TRIP | 1 high-pressure cut-out |
| 27 | LOCKOUT | 1 entered, 0 cleared |
| 46 | DEFROST | 1 start, 0 end |
| 8B | HEATER | 1 on, 0 off; tracks defrost and heater power, not a second door contact |
| D3 | BOOT / firmware | `0032` is 3.2, `0034` is 3.4; version digits are not decimal integer 50/52 temperatures |
| 63 | QUEUE_OVERFLOW | Count of dropped/overflowed entries |

There is **no observed SETPOINT telegram** in the union of logs and ledger raw frames. I have not fabricated a type code or payload layout for it.

STATUS order is:

1. discharge pressure;
2. evaporator coil temperature;
3. air temperature;
4. state flags.

Temperature conversion is `(word − 1000)/16`. For 3.2 this is relative to the room setpoint; for 3.4, when bit 12 is set, it is absolute Celsius. Both temperature words show the format change. Pressure is rendered as `word/10` in the reconstructed nominal bar convention; this engineering-unit inference has lower confidence than the temperature map because no calibrated pressure reference/data sheet survives.

| Flag | Bit, zero-based | Mask |
|---|---:|---:|
| DEFROST | 0 | 0x0001 |
| DOOR_OPEN | 2 | 0x0004 |
| RUN | 4 | 0x0010 |
| RECOVERY | 5 | 0x0020 |
| LOCKOUT | 6 | 0x0040 |
| ABS_TEMP | 12 | 0x1000 |

Examples: `1014` means absolute format, running, door open; `1040` means absolute format and locked out; `1030` means absolute format, running and recovering.

**All 45 snapshot frames are translated in `answer.json`: 38 status frames each yield four quantities, and seven event frames yield one event each, for 159 records.** Each carries the real sequence number and reconstructed UTC timestamp. The first frame is seq 3149 at March 30 22:35, with air −24.625°C; the final frame is seq 3193, lockout at March 31 01:41. These are sensor engineering values, not bias-corrected product temperatures. The snapshot does not include the later peak or lockout clear.

## 4. Refrigeration mechanism and estimates

The effective temperature model used for estimation is:

```
dTz/dt ≈ k_leak[z] × (ambient − Tz) × door_multiplier
          − k_cool[z] × RUN
          + c_adj × sum(Tneighbor − Tz)
          + heater_input
sensor_air = Tz + bias[z](t)
```

The submeter room-temperature channel supplies the ambient covariate. Fits use raw re-decoded status, door/state changes, probe corrections, and shared-wall geometry. Stable-state five-minute differences and longer integral fits provide a sensitivity check. Sampling, noise, short door openings and unobserved sub-five-minute transitions prevent laboratory precision. The coefficients below are **effective field estimates**, not factory settings or a uniquely identified complete heat-transfer model.

| Room | Cooling °C/min | Leak 1/min | Hysteresis half-band °C | Baseline sensor bias °C |
|---|---:|---:|---:|---:|
| A | 0.123 | 0.00105 | 0.76 | −0.8 |
| B | 0.082 | 0.00099 | 0.83 | +0.2 |
| C | 0.135 | 0.00115 | 1.20 | about +0.7, time-varying drift described below |
| D | 0.030 | 0.00142 | 1.14 | **not established** |
| E | 0.115 | 0.00110 | 1.11 | −0.8 |
| F | 0.029 | 0.00173 | 1.14 | **not established** |

H denotes approximately setpoint±H switching, not the full band width. Bias means sensor minus physical temperature. D and F lack independent calibrated probe observations: a precise absolute bias is not defensibly recoverable separately from the fitted thermal intercepts. Their heat-leak estimates are correspondingly conditional and lower-confidence. Independent reference probes would settle this.

Other estimates/rules:

- **Door gain:** roughly **3.25×** ambient heat leakage; this is less precisely identified than discrete state timing.
- **Shared-wall coupling:** approximately **0.00028/min**. Connections are A–F, A–B, F–E, F–C, E–D, B–C, C–D and the sealed but thermally relevant B–E pass-through. Coupling and leak estimates covary.
- **Defrost:** approximately **10 accumulated compressor-running hours to eligibility**; **27-minute** cycles, roughly **4.2°C integrated heater contribution** after passive gains. Eligible rooms are staggered in priority order **C, F, D, B, A, E**, with no overlapping heaters. Eligibility/queue waits can make runtime between observed starts exceed ten hours. The runbook's fixed six-hour wall-clock account is wrong.
- **Trips:** about **seven minutes of sustained open-door running** precedes a pressure trip; repeated trips are commonly 12 minutes apart, including about five minutes off/hold-off.
- **Lockout:** **five trips within approximately 60 minutes**, then **60 minutes hold-off**. Five trips spanning 55–56 minutes produce lockout; examples spanning 63 minutes do not. Thus 60 is a supported nominal estimate, not proof of an exact cutoff to the minute. Multiple C entry/clear pairs establish the 60-minute duration directly.

### Probe discrepancy in C

The February certificate explicitly fails HH-2 at **+0.7°C**; its readings must be corrected downward. HH-1 passes at the reference point. Corrected comparisons show baseline C bias near +0.7°C, then gradual additional positive drift of roughly +2.7°C before April 7, removed by recalibration. HH-1 independently confirms the trend, so it is not merely HH-2 error. The panel increasingly reads **warmer**, not colder, than the physical room; the corresponding ticket gets the direction wrong. This can lead to excess cooling and is separate from E's incident.

### What the missing interval permits

The snapshot directly proves the first lockout. The returned locked-out status and P1 power pattern support further protective cycling, but **do not uniquely identify every lost transition**. P1 supplies both E and F. Nor does a 45-entry snapshot establish the exact peak or initial −15°C crossing. The returned readings alone establish over three hours of physical air above approximately −15°C during recovery, with earlier warming also evident. The exposure is consistent with the laboratory's “several hours” assessment; exact product-core temperatures require product/pallet instrumentation and stability analysis.

## 5. How monitoring failed

### Firmware/parser compatibility, not a demonstrated sensor-board fault

`gateway/rh7_decode.py` always executes `setpoint + (word−1000)/16`; it ignores ABS_TEMP. After 3.4, E's value is wrong by **−24.7°C** and A's by **−29.3°C**. The E status at 04:45 says −2.0°C, but the gateway stores −26.7°C, below the configured high limit of −17.7°C. Even after reconnection, this prevents the expected critical excursion alarm.

Raw BOOT/status, the two-unit invoice and probe checks contradict the “E left on 3.2” and “known sensor-board fault” explanations. The decoder was indeed inherited from Dana Whitcombe; that provenance does not make a later incompatible upgrade safe or establish malicious authorship.

### Routing, suppression and stale-data design

- Rafael's tracked hotfix changes the **zone channel**, affecting both high and low alarms, despite its low-warning description.
- Sofia archives the destination on March 22. Her statement that this happened only after the incident is false. The frozen routes still point there; no restoration reload appears.
- `config.override.json` sets minimum severity to critical. Its file is intentionally untracked, the ledger audit table is empty, and no surviving authenticated deployment record identifies its writer. Discussion on March 22 and later suppression logs establish awareness/effect, not authorship or an exact installation instant. The first surviving explicit suppression occurs March 28 at 05:05.
- The override suppresses **warnings**, not critical alarms. It must not be described as a universal alarm mute.
- `alerting.evaluate` reads latest values without testing their age. The gateway watchdog creates `controller_stale` ledger events, but alerting does not consume them. Trips/lockout are unknown activity telegrams, not decoded fault pages. The E stale stream therefore does not yield an effective independent loss-of-monitoring alarm.

### Three distinct data-loss mechanisms

1. **Door-linked E cable loss:** begins before 01:00 and lasts approximately four hours. T-0434 documented and reproduced precisely this door-position link failure months earlier. This is the probable immediate explanation, though a direct cable inspection is needed to prove the physical defect.
2. **Nightly billing transaction:** Git-recovered `billing/nightly.py` takes `BEGIN EXCLUSIVE` and performs slow per-lot work while holding the transaction. Logs show roughly 33–46-minute runs, ledger write locks, gateway deadlines and missed acknowledgments. WAL does not eliminate writer contention. This independently damages observability; local refrigeration is not turned off by a database lock.
3. **March 31 afternoon disk-full log gap:** services stayed up, and ledger raw rows survive. It is not the overnight event and should not be used to imply all evidence disappeared.

Dispatch webhook work is posted from a **background worker**, not synchronously awaited on the controller receive path. Its backlog must not be asserted as the direct cause of the door-linked E telemetry loss without evidence.

## 6. Inventory, quarantine and billing

### Deterministic inventory failure

`common/httpd.py` dispatches by the first matching prefix. The earlier GET `/lots` route therefore catches GET `/lots/LN-...`; the later `/lots/` detail handler never gets that request. Dispatch receives `{"lots": [...]}`, tries `cur["zone"]`, and fails with **`'zone'`**. The worker catches the exception and still sets the job state to `done`.

This is corroborated, not merely suggested, by repeated dispatch errors, **zero rows in `moves`**, and all **63 lots retaining their March 14 import positions/timestamps**. It is not a case where only one operator's scanner disagrees with an otherwise accurate ledger.

Inline serialized WMS lookup before queueing, scanner bursts, webhook deadlines and retries without deduplication add delay and duplicate jobs. Queue `created_at` can be much later than scanner `recv`; neither `done` nor job count proves successful physical movement or ledger reconciliation. Physical telematics and original scan payloads must be used with duplicate handling.

### Exposure cohort and quarantine comparison

The following reconstruction uses physical forklift destinations through the incident and checks original queue payloads, rather than taking late duplicates as new movements. No recorded E movement occurs from 00:46 through 10:40 on March 31.

| Supported E cohort | On QA's list? |
|---|---|
| LN-21319 | No |
| LN-22986 | No |
| LN-24719 | No |
| LN-24829 | Yes |
| LN-25158 | No |
| LN-25914 | No |
| LN-26290 | Yes; remained in its original E position |
| LN-26980 | No |
| LN-27211 | No |
| **LN-29378** | **No; the laboratory-flagged lot** |

The seven QA-listed lots moved elsewhere before the incident are LN-21026, LN-24790, LN-25661, LN-26766, LN-29303, LN-29333 and LN-29796. This is **not** permission to release them without reviewing their own histories. It establishes that QA's list is not the incident exposure cohort.

Victor's narrower assertion that he quarantined every lot **the ledger showed** in E is consistent with the evidence. The failure is reliance on an unvalidated location system, not proof that he intentionally omitted a known ledger entry. LN-29378 illustrates the defect directly: FL-1 deposited it in E on March 29 while the failed jobs left the database at A.

### Two operator accounts must not be conflated

PL-5665/LN-23201 has independent FL-1 confirmation of the April 1 F→A→C sequence; its scans are not evidence of scanner malfunction. For PL-5824/LN-25827, a D→C scanner event and Ivan's account are plausible and consistent with earlier/later physical records, but **FL-2 has no contemporaneous trail** during its battery failure. The missing paper sheets and expired footage prevent an independent exact-path finding. An unchanged A ledger location does not decide between a correct scan, an unrecorded intervening move or a mis-scan.

### Separate billing defect

Git identifies the removal and later source restoration of division by 60. Nonetheless **every supplied daily export** reports 1440 hours for a stationary lot-day. Example: LN-23683 is charged 604.80 at 0.42/hour instead of 10.08 for 24 hours—a **60× unit-conversion error**. The same stale locations and whole-history temperature averages also contaminate rollups. A commit is not proof of deployment; the missing billing working-tree files and surviving logs/exports do not establish the precise live restart/version history. There is no evidence here sufficient to call this intentional fraud.

## 7. Statements contradicted, versus claims not proved

`answer.json` quotes the exact contradicted text. The principal contradictions are:

- Firmware report: E “inspected only” and left on 3.2 — contradicted by BOOT `0034` and status bit 12.
- Sofia: old channel archived only after the incident — contradicted by March 22 m0094.
- Agency worker: never propped any cold-room door — contradicted by the earlier wedge metadata, receipt and removal exchange. **This does not prove she caused the March 31 event.**
- Owen: HH-2 “reads fine” — contradicted by its failed calibration certificate.
- Night lead: nobody went near E after the morning departure — contradicted by the 09:03 probe/contact and subsequent activity.
- Engineer's board-fault interpretation — contradicted by the precise additive decode error and independent temperature checks; the content of his claimed phone call is not independently recoverable.
- QA's suggestion the recall was issued once this excursion was identified — the notice is dated February 18 and excludes the fitted models.
- Postmortem: compressor root cause and restored E alert routing — contradicted by the observed protective sequence and still-legacy routing.
- Runbook: fixed six-hour defrost; bench report: 8B as door; C ticket: increasing handheld-warm discrepancy — each contradicted by the corresponding machine/probe data.

By contrast, I do **not** label either engineer's override denial false, do not declare the incident door actor known, and do not treat the six reported pages as independently disproved merely because this archive lacks a separate paging-system audit. A mistaken technical theory is not automatically proof of dishonesty.

## 8. What would settle the outstanding questions

| Open question | Competing explanations / required evidence |
|---|---|
| Incident door actor/object | Repeated wedge use by Rivera; another authorized person; an unattended obstruction/door fault. Need incident footage, functioning E access records, corroborated contemporaneous witness records or physical evidence. Retained April motion records cannot reconstruct March 31 identity. |
| Override author/time | Ana, Rafael, another operator or automation. Need authenticated sudo/shell/deployment records, file provenance or configuration-management history—not only Git, since the file was ignored. |
| Exact peak and lost protective cycles | Sustained opening with repeated trips fits the data, but additional transitions are possible. Need a longer controller history, independent E-only electrical monitoring and calibrated continuous temperature logger. |
| D/F absolute bias and precise thermal constants | Independent reference probes and a controlled, documented thermal survey; current fits have correlated leak, bias and adjacency effects. |
| FL-2 exact move path | Recover paper move sheets, scanner raw acquisition records and independent location records; the lost telematics cannot be recreated by trusting the failed ledger. |
| Individual-lot damage and shipping contribution | Product/pallet temperature histories, shipping chain-of-custody/loggers, validated time-temperature stability limits and testing. Air exposure identifies candidates, not potency outcomes for every unit. |
| Billing fix actually running / publication chronology | Process/deployment manifests and immutable release/document logs. Existing contradictions should remain visible rather than being filled with invented dates. |

## 9. Recommended actions

### Immediately

1. Expand product containment and trace shipping against the reconstructed cohort, including LN-29378. Keep prior holds until their independent histories are reviewed. Quality should make lot-specific dispositions using validated stability evidence, not this room-air model alone.
2. Correct the decoder by firmware/ABS_TEMP flag and replay the preserved raw data into a separate corrected analytical ledger. Retain the original readings and explain every correction. Test 3.2, 3.4, both temperature words, all flags and event types.
3. Restore and verify live alert delivery. Remove/expire unauthorized overrides; alert independently on stale controllers, link loss, queue overflow, trips and lockout. A stale value must never be silently treated as a current safe reading.
4. Repair and validate the E door-frame communication defect and door closure. Add an independent temperature/door alarm path so a single door action cannot disable its monitoring.
5. Stop using the current inventory ledger as physical truth. Fix route specificity, validate response schemas, make failed jobs visibly failed/retryable, and reconcile all 63 lots from independent records.

### Correct the systemic controls

- Require authenticated, time-limited, audited configuration overrides and dual authorization for safety-alarm changes. Audit channel status and delivery, not just a route string.
- Decouple telemetry acknowledgment/persistence from long ledger locks; use durable buffering, replay and explicit loss counters. Run billing against a snapshot/read replica without holding a long write transaction.
- Add scanner idempotency keys and per-lot ordering/version checks. Move slow WMS lookup out of the synchronous enqueue path. Preserve original scan time separately from enqueue and apply times.
- Remove or adjust HH-2; use calibrated references in **every** room, not just the pick route. Validate C recalibration and trend sensor-reference differences.
- Recompute invoices, investigate credits, and verify deployed process versions rather than relying on a committed fix. Correct rollups to use actual time-weighted zone histories and daily time windows.
- Retain access, controller, deployment and camera evidence long enough for delayed stability findings. Standardize clocks but also record receipt latency and uncertainty.
- Replace the postmortem with a version separating observed facts, model estimates, uncertain attribution and product-scope limitations. Address maintenance deferral and system design failures rather than assigning unsupported personal blame.

## Reproducibility note

Analysis artifacts in `/work` include parsed gateway frames, the union with database-only frames, temperature/probe calculations, regression sensitivity scripts, and physical-inventory reconciliation. The original evidence was not modified. Billing source absent from the working tree was inspected through Git. Structured results, parameter confidence/limitations, all snapshot translations, event timestamps and exact false-claim quotations are maintained in `/work/answer.json`.
