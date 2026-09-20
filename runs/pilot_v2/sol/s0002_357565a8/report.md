# Independent reconstruction — Borealis Coldchain room E

## Executive finding

The internal postmortem identifies the wrong mechanism and overstates what can be known about both culpability and product scope. VX05's compressor did not mechanically fail and its setpoint did not drift. Room E's door was held open beginning at approximately **2026-06-20 00:30Z**. The open door also interrupted the already-known pinched VX05 communications link. The controller continued operating locally: increasing load led to high-pressure trips at roughly 15-minute spacing and then a four-trip lockout. It remained locked out for 90 minutes and subsequently restarted and cooled the room.

The raw firmware-3.4 air word crossed **-15 C near 00:50Z**, peaked at about **+7 C**, and did not return below -15 C until approximately **10:12Z** (a defrost/recovery cycle slowed the pull-down). Correcting the independently estimated +0.9 C VX05 sensor bias puts the physical threshold crossings at roughly 00:58Z and 09:57Z and the peak near +6.1 C. This exposure is consistent with the customer's result for LN-22416.

The warm condition was invisible to the deployed alarm logic because both VX03 and VX05 had in fact been flashed to firmware 3.4 on 8 June. Firmware 3.4 reports absolute temperature and sets status bit 14; the old gateway continued treating the word as an offset and added the room setpoint. Thus a real -19 C appeared near -39 C, and even a real +7 C appeared near -12.3 C. The resulting low-temperature warning had already been moved to an archived channel. A local `ALERT_MIN_SEVERITY=critical` override also suppressed warning-level alerts, although the evidence cannot identify who placed that ignored, unversioned file.

## Reconstructed sequence (true UTC)

Clock corrections used here are record-clock minus true time: badge +2 min, CCTV +3, gateway/service logs +8, git +8, chat +8, forklift +9, probe +10, EXIF camera -120; tickets and submeter are treated as 0. These offsets come from matching door contacts, motion, forklift and probe observations to controller events; the EXIF offset is directly demonstrated by GPS time.

- **8 June 14:54 / 15:35** — Felix Okafor flashes VX05 / VX03 to 3.4. Each unit emits a `62,0034` boot banner and thereafter sets ABS_TEMP. The invoice charges two units. This directly contradicts the service report's claim that VX05 was unchanged.
- **8 June 17:15; 9 June 01:21** — Maya Mensah buys a door wedge and photographs it under the room-E door. At 01:51 true time she posts “new toy for the airflow problem in room E”; Hana warns not to leave it in the door.
- **9 June 11:28** — Maya Larsen commits the C/E route change (`761f81a`), moving low-temperature warnings to `#alerts-coldchain-old`. The change does not create the severity override.
- **10 June 09:46** — Priya Novak archives that old channel.
- **19 June 14:50** — FL-2 records LN-22416/PL-6443 dropped into E.
- **19 June 21:40 / 21:53** — Maya Mensah and Hana Tanaka badge in for night shift.
- **20 June 00:19–00:20** — an ordinary one-minute E door opening and closure.
- **20 June 00:30** — E door opens again and remains open. The controller link disappears as documented in T-0402. Attribution to Mensah is strong but circumstantial: she is present, bought and photographed the wedge, and joked about using it; the E badge reader was broken and CCTV had expired. It is therefore “probable,” not established.
- **00:41, 00:56, 01:11** — three high-pressure trip telegrams occur. The omitted sequence 3556 at 01:26 is consistent with the fourth trip; sequence 3557 is the resulting lockout. Independent D/B sequences establish the same four trips within 90 minutes rule.
- **about 04:47** — communications return with DOOR_OPEN clear, establishing closure by then, but not who closed it.
- **05:21** — the 90-minute lockout clears; VX05 runs and cools normally. This behavior refutes compressor failure.
- **05:49 / 05:56** — Mensah and Hana badge out.
- **30 June 09:00** — QA opens T-0421 after the customer's stability email.

## Controller protocol recovered

Frames are ASCII lines of the form `$unit,seq,tick,type,words*XOR`. Sequence and tick are hexadecimal. The tick is a free-running counter in **10-second units**, not wall time. For status (`F8`), the deployed four-word order is:

1. air temperature;
2. discharge pressure;
3. state flags;
4. coil temperature.

Temperatures use `(word - 1000) / 10`. Before 3.4 this is a delta from setpoint; in 3.4 it is absolute C and bit 14 is set. Pressure uses a divisor of 10. Flag bits are: RUN 15, ABS_TEMP 14, DOOR_OPEN 12, LOCKOUT 6, RECOVERY 2, and DEFROST 1.

Observed type map: `F8` STATUS, `4D` DOOR, `74` TRIP, `1D` LOCKOUT/hold-off, `BD` DEFROST, `50` HEATER, `62` BOOT/firmware banner, and `34` QUEUE_OVERFLOW. The old vendor note has both a stale status layout and stale event codes. `answer.json` translates all 45 snapshot entries; each F8 frame is represented by its primary air-temperature observation. Its timestamps are anchored to the 3.4 boot and tick counter.

## Refrigeration behavior inferred

A joint fit of clean five-minute status intervals to ambient, RUN state, door state and shared-wall temperatures gives the following rates (degC/min for cooling, 1/min for leakage):

| Room | k_cool | k_leak | hysteresis H (C) | controller bias (C) |
|---|---:|---:|---:|---:|
| A | 0.03 | 0.0012 | 0.8 | +1.3 |
| B | 0.09 | 0.0007 | 0.6 | unknown |
| C | 0.07 | 0.0008 | 0.8 | +0.3 |
| D | 0.06 | 0.0006 | 0.4 | about +1.0 baseline |
| E | 0.12 | 0.0012 | 0.6 | +0.9 |
| F | 0.03 | 0.0017 | 1.0 | unknown |

There are no calibrated reference checks for B or F, so their additive biases are not identifiable and are deliberately null in the structured answer. D's bias later drifted toward the independently measured +3.2 C and was reset on 27 June; the baseline estimate is consequently less certain.

Door opening multiplies leakage by about 7; shared-wall coupling is approximately 0.00015/min. Shared walls are D-C, C-E, D-B, C-F, E-A, B-F, F-A, and the sealed D-F hatch wall. Defrost is based on roughly five accumulated compressor-runtime hours, not six wall-clock hours. It lasts 24 minutes, adds nominally 4.5 C, and is serialized in priority order C-A-F-B-D-E. Four pressure trips within 90 minutes trigger a 90-minute lockout; attempts are separated by a 15-minute minimum.

## Alerting and responsibility

Established acts are narrow:

- Larsen made the versioned route change; her denial of a severity change in that commit is supported by the diff.
- Novak said in chat that she archived the legacy channel.
- The critical-only override exists, is ignored by git, and was active. There is no surviving creation timestamp, audit record, commit, deployment log, or shell history. Both Larsen and Kowalski deny placing it. Assigning it to Kowalski, as the postmortem does, is not supported.
- Mensah's door use is probable but not directly observed. The broken badge reader and expired CCTV prevent elevating that attribution to established fact.

The override was contributory, but not the principal reason a warm alarm was missed: it suppresses warning, whereas high-temperature alarms are critical. The stale decoder prevented the 3.4 absolute value from reliably crossing the configured critical-high threshold.

## Product scope and records

LN-22416 was probably in E: forklift telemetry records its drop at 14:50 true time, well before the event, and the lab finding is consistent with the reconstructed exposure. Exact causation remains probabilistic because a stability signature is not uniquely identifying.

The complete exposed-lot list cannot be recovered. The ledger's `moves` table is empty and every `lots.updated_at` remains the initial import time. Dispatch calls `PUT /lots/<lot>/zone`, while ledger only routes an exact `PUT /lots`; therefore queued “done” jobs never update the system of record. Forklift telemetry is the better physical source but has wrong-room/duplicate scan evidence and FL-2 lost telemetry from 20–22 June. The postmortem list is merely the stale initial E list and notably cannot establish physical scope. This cannot be repaired by choosing one source over another.

To settle product scope, obtain the WMS/handheld native scan audit, any off-site NVR backup, shipment pick records and pallet-level customer receipts. To settle door attribution and override authorship would require, respectively, retained CCTV/working access logs and host filesystem/audit/shell history; none survives here.

## Other false leads and demonstrably false statements

- The Nordkälte recall covers NK-450S/SX serial 7A; the site note identifies NK-380 serial 5B. It is irrelevant.
- Room D really had a separate sensor drift, but that does not explain E. HH-2 was itself certified +0.8 C out of tolerance, contrary to Dubois's statement that it “reads fine.”
- The three-hour gateway text-log gap is real, but ledger records and alerting logs continued, so “nothing was being logged at all” is false.
- The exact false quotations and document identifiers are listed in `answer.json`; claims that are merely unprovable are not mislabeled as false.

## Recommendations

1. Immediately quarantine LN-22416 and reconstruct all pallet positions from native scanner/WMS and shipping records; do not use the stale ledger list as disposition evidence.
2. Validate and version protocol maps by firmware; reject/alert on unknown firmware and decode ABS_TEMP from the flag rather than from site assumptions. Reprocess retained raw frames with the corrected decoder.
3. Repair `PUT` route integration, add end-to-end move assertions, idempotency keys and reconciliation alarms; a queue job must not become “done” after a failed ledger update.
4. Remove unversioned severity overrides. Require an authenticated actor, reason, automatic expiry, audit trail and a second approver. Alarm when a notification channel is archived while routes still target it.
5. Repair the E door-frame cable and badge reader; add an independent door-open alarm path that does not share that cable, with local audible alarming.
6. Alert on repeated trips, lockout and stale links directly from decoded event types. A communication loss coincident with DOOR_OPEN should page independently of temperature.
7. Revalidate every controller after vendor service against a calibrated probe and capture signed before/after firmware, configuration and protocol records. Investigate the inaccurate vendor report.
8. Remove HH-2 until adjusted, shorten room-D calibration intervals, and preserve NVR/host audit evidence longer than the quality-release latency.
