# Independent reconstruction — NGN54 room E excursion

## Executive finding

Room E did suffer a major warm excursion overnight on 30–31 March 2026. The company's stated root cause—failure of the VX05 compressor—is not supported. The sequence supported by the controller is:

1. VX05 had in fact been upgraded to firmware 3.4 on 20 March, contrary to the vendor service report.
2. Firmware 3.4 changed the status temperature from setpoint-relative to absolute and marks this with status bit 12. The deployed gateway did not understand that change. It treated the absolute value as a delta and added E's -24.7 C setpoint a second time, producing the fictitious roughly -40 to -50 C dashboard values.
3. At **2026-03-31 00:56Z true time**, E's door opened. The fault snapshot then shows repeated high-pressure trips while the compressor repeatedly attempted to run. Five trips within the one-hour window caused protective lockout.
4. Opening E fully was already known to pinch the controller-link cable (T-0434). The link disappeared while the door was open. On reconnection it reported a 67-frame queue overflow. This is why the hottest part of the event is absent from the host record.
5. The first surviving status after the gap was about **-2 C**, with the lockout flag still set. After the 60-minute lockout cleared, the compressor ran in recovery and pulled the room below -15 C at about **08:10Z true time**. Recovery without repair, compressor RUN states, and panel-power data refute compressor failure.

The monitoring failures were real but differ from the postmortem. E's low-temperature warning had been routed to an archived legacy channel, and an override admitted only critical alerts. More fundamentally, the bad decode kept a real warm room classified as implausibly cold. The override suppresses warnings, not critical high-temperature alerts, so it would not itself have blocked a correctly decoded high-temperature alert.

Lot **LN-29378 / pallet PL-3290** was physically moved into E on 29 March and remained there through the event. The final ledger snapshot places it in A only because it records a later state. The postmortem's nine-item quarantine list exactly matches the later `lots` snapshot for E, not an incident-time reconstruction, and even omits LN-29378. The full exposed-lot set cannot be recovered safely from these records.

## Controller and refrigeration behaviour

### Estimated parameters

The structured estimates and confidence for every requested parameter are in `answer.json`. The strongest discrete results are:

- defrost is based on accumulated compressor runtime, threshold 10 hours;
- heater/defrost runs are 27 minutes and add approximately 6 C;
- simultaneous heaters are prevented by staggering, with inferred priority `C, F, D, B, A, E`;
- a trip imposes 7 minutes minimum dead time;
- five trips in a 60-minute window enter lockout for 60 minutes;
- opening a door increases passive gain by approximately 2.5 times;
- shared-wall coupling is small, about 0.0004/min.

The floor-plan adjacency used is A–F, A–B, F–E, F–C, E–D, B–C, C–D, plus the old B–E hatch/shared wall.

Cooling and leakage rates are identifiable from thousands of normal status transitions. Absolute thermal equilibrium `H` and fixed-sensor bias are separately identifiable only where calibrated external probe observations survive. HH-1 is unbiased; HH-2 is documented at +0.7 C. Those comparisons support approximately -0.8 C fixed-sensor biases in A and E, +0.2 C in B, and an initial +0.8 C in C. C is not truly constant: it drifted to approximately +2.7 C before recalibration on 7 April. D and F have no independent probe checks, so their `H` and bias are correctly left null: dynamics reveal only their sum. Assigning separate values would be fabrication.

### Defrost evidence

Types 46 and 8B start and stop together. Starts do not follow the runbook's claimed six-hour wall schedule. They occur when runtime becomes due, then queue in non-overlapping 27-minute slots. Air rises about 6 C, status bit 0 marks defrost, and bit 5 marks subsequent recovery.

## Wire protocol reconstruction

The frame is ASCII:

```
$unit,seq,tick,type,w0 w1 ...*xor
```

`seq` and `tick` are 24-bit hexadecimal; tick is a minute counter, not wall time. Checksum is bytewise XOR of the characters between `$` and `*`.

Observed type map:

| Code | Meaning |
|---|---|
| 3A | STATUS |
| 98 | DOOR |
| D7 | high-pressure TRIP |
| 27 | compressor LOCKOUT / hold-off |
| 46 | DEFROST |
| 8B | HEATER |
| D3 | BOOT/firmware banner |
| 63 | QUEUE_OVERFLOW |

STATUS is **pressure, coil temperature, air temperature, state flags**, not the layout stated in the obsolete integration note. Pressure is tenths; temperatures use `(word - 1000) / 16`. On pre-3.4 firmware that temperature is relative to setpoint. On 3.4 it is absolute, indicated by flag bit 12.

Flag bits are: defrost 0, door-open 2, compressor RUN 4, recovery 5, lockout 6, absolute-temperature 12. `answer.json` translates all 45 fault-snapshot frames. Snapshot tick was aligned to surviving host receipts, then corrected for the gateway's -10 minute clock offset.

## Incident timeline (true UTC)

- **2026-03-19 15:10** — Lena Rivera buys the rubber wedge.
- **2026-03-19 22:33** — phone metadata places her wedge-under-E-door photo here; she posts it shortly afterward.
- **2026-03-20 14:12** — VX05 boots with firmware banner `0034`.
- **2026-03-20 14:50** — VX01 boots with banner `0034`.
- **2026-03-21 10:46:13** — Rafael Okafor commits routing A/E low warnings to the legacy channel (`f917296`).
- **2026-03-22 11:42** — Sofia Larsen archives that legacy channel.
- **2026-03-27 08:00** — E badge-reader outage ticket opens (ticket clock corrected by -60 minutes).
- **2026-03-31 00:56** — VX05 door-open telegram; controller link then vanishes.
- **about 01:00–01:50** — retained snapshot shows warming, repeated trips, and lockout. It ends before the peak.
- **2026-03-31 04:55** — host telemetry resumes; air is about -2 C, door flag is clear, lockout remains set, and overflow count is 67.
- **2026-03-31 05:15** — lockout clears; recovery cooling begins.
- **2026-03-31 08:10** — E first returns below -15 C.
- **2026-04-10** — customer report arrives; QA issues quarantine based on an unsuitable current ledger snapshot.
- **2026-04-11** — postmortem published.

Channel offsets are `(channel clock) - (true time)`: badge 0, EXIF +60, CCTV -5, forklift -10, chat -10, tickets +60, git 0, submeter 0, gateway -10, and probe -15 minutes. Relative offsets are supported by repeated co-occurrence of forklift, badge, controller-door, CCTV, probe and bot-alert events. EXIF is anchored directly by GPS time; the ticket offset is also explicit in T-0436's timestamp versus its stated outage end.

## What is established

- E was warm enough to explain the lab result; at least the recorded recovery interval alone gives more than three hours above -15 C.
- The firmware/decode incompatibility hid the true temperature.
- Both A and E received 3.4, despite the report saying E did not.
- A door-open event initiated the E sequence; trips and protective lockout, not an inert failed compressor, explain the loss of cooling.
- Alert routing and channel archival were unsafe contributing controls.
- LN-29378 was in E during the event and was omitted from the postmortem list.
- The override was present, but could not suppress a correctly decoded critical high-temperature alarm.

## What cannot be determined

### Person who held E open

The evidence does **not** identify the incident actor. The E badge reader was already down, FL-2's telematics subsequently failed, and CCTV retains only seven days and therefore has no incident footage. Lena Rivera owned a wedge and had earlier photographed it under E's door, which makes her one plausible hypothesis and disproves her categorical statement that she had never propped any cold-room door. It does not prove she used it on 31 March. A night lead or another key holder is also compatible with the surviving evidence.

**What would settle it:** retained corridor video, a working room-E access log, agency-worker scanner/audit records, or a contemporaneous witness record.

### Exact peak and start above -15 C

The retained 45-frame snapshot ends near the first lockout. The pinched link then loses frames, and overflow proves they cannot be recovered. Temperature is still below -15 C at the snapshot end but is -2 C on reconnect. Thus crossing and peak lie inside the missing interval.

**What would settle it:** a full controller ring-buffer image rather than the 45-frame fault snapshot, an independent logger, or product time-temperature indicators.

### Complete exposed inventory

`moves` is empty; `lots` is only a later current-state snapshot. The gateway retried scanner moves, creating many duplicate jobs, and two dispatch workers applied stale `from` states concurrently. FL-2 also has a telematics gap. Forklift data can establish LN-29378, but some other pallet trails conflict.

**What would settle it:** immutable scanner event IDs, WMS history, paper sheets for the FL-2 gap, shipping manifests, and customer receipt records. Until then, use the union of plausible E occupants, not the postmortem list, for risk disposition.

## Demonstrably false statements

Exact quotations are listed in `answer.json`. Material examples are the service report's “VX05 ... no changes made,” the postmortem's “Root cause: compressor failure,” the claim that the severity override would block any residual notification, the warehouse manager's claim that she archived the legacy channel only after the incident, the engineer's “known sensor fault” diagnosis, and the agency worker's categorical denial of ever propping a cold-room door.

## Recommendations

1. **Quarantine broadly now.** Reconstruct the union of every pallet plausibly in E and notify customers; do not use the nine-lot postmortem list as the exposure boundary.
2. **Fix and test decoding.** Make protocol maps firmware-specific; reject unknown firmware/layout combinations rather than silently emitting temperatures. Validate against a calibrated probe after every flash.
3. **Restore independent monitoring.** Install a calibrated, battery-backed logger whose alarm path does not share controller firmware, serial cable, gateway parser, or chat routing.
4. **Repair E's cable and access reader.** Move the serial path away from the door frame, alarm on link loss once (not once per minute), and retain access/CCTV evidence for the validated product-retention period.
5. **Make alerts fail safe.** Never route production alerts to archived channels. Test high and low synthetic alarms per zone. Expire maintenance overrides automatically and require approval and audit identity.
6. **Make moves idempotent.** Use a scanner-generated event ID, a uniqueness constraint, atomic compare-and-set of `from` location, and immutable movement history. Do not perform slow WMS lookup before enqueueing.
7. **Treat protective events as alarms.** Page on each trip series, lockout, queue overflow, firmware change, and controller stale/link-down condition independent of temperature.
8. **Correct governance.** Withdraw the current postmortem, issue a corrected causal analysis, preserve raw frames, and require evidence review before naming an individual culprit.
