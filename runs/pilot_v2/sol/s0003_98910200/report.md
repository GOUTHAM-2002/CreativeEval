# Independent incident reconstruction — room E cold-storage excursion

## Executive conclusion

The postmortem's compressor-failure theory is wrong. Room E's door opened at **2026-03-26 00:48 UTC** and remained open long enough to create a severe heat and pressure load. The known door-frame cable defect simultaneously took TK05 off the host link. TK05 still had cooling capacity: its compressor repeatedly ran, but it tripped four times on high discharge pressure and entered its designed 90-minute lockout at about **01:45**. Air had already risen above -15 °C and ultimately reached at least 5.19 °C before useful host telemetry returned. This is fully consistent with the customer's degradation signature.

The monitoring failure began earlier. On 15 March, both TK02 and TK05 were flashed from firmware 3.2 to 3.4. Firmware 3.4 changed temperature words from setpoint-relative values to absolute values. The gateway parser was not changed and continued adding the configured setpoint. Its approximately -40 °C dashboard values were therefore decoding artifacts, not failed sensors. Engineering routed B/E low-temperature warnings to a legacy channel; that channel was archived on 17 March. A gitignored override also raised the minimum alert severity to critical. During the excursion the bad decoder mapped actual warmth back into apparently cold values, while the door-induced link loss removed the most important interval altogether.

The evidence does **not** identify who left the door open. The postmortem's attribution to the agency worker is unsupported. Noor Costa's categorical statement that she had never propped a cold-room door is separately false: her earlier photo and chat establish a wedge under the E door on 16 March. That does not prove she repeated the act on 26 March. The E badge reader was offline, the controller link dropped when the door opened, and the relevant CCTV had been overwritten under the seven-day retention policy.

## What the controller evidence establishes

### Wire format and firmware change

A frame is `$unit,seq,tick,type,words*checksum`; `seq` and controller tick are hexadecimal and the checksum is the byte sum modulo 256. The actual status layout is:

| word | quantity | conversion |
|---|---|---|
| w0 | coil temperature | `(word-500)/16`; add setpoint only on 3.2 |
| w1 | air temperature | `(word-500)/16`; add setpoint only on 3.2 |
| w2 | state flags | bit field |
| w3 | discharge pressure | `word/50` |

Flags are RUN=6, RECOVERY=3, LOCKOUT=7, DOOR_OPEN=10, DEFROST=13, and ABS_TEMP=14. The last bit identifies the 3.4 absolute-temperature encoding. Observed opcodes are 56 status, 29 door, 67 trip, 55 lockout, EB defrost, 11 drain-pan heater, BA boot/firmware, and 3A queue-overflow. In particular, 3A is not a setpoint telegram: its payload equals the sequence count lost while the controller link was down.

The repository's integration note is not reliable for the deployed TK-5 protocol: it labels w0 as pressure and gives unrelated event opcodes. The partial gateway decoder correctly used w1 as air but only understood the old relative encoding and RUN bit.

### Fault snapshot

The snapshot's controller tick can be anchored to seq 3212, which the ledger received at 22:30:21. Before the event, E air cycled around its -21.7 °C setpoint. Seq 3240 is a door-open telegram at 00:48, after which the host stops receiving frames, exactly as ticket T-0410 predicts when the E door is fully open.

The controller itself retained the following decisive progression:

- 00:50: -21.13 °C air, door open, compressor running.
- 00:55: -19.38 °C, discharge 122 engineering units.
- 00:57: first high-pressure trip.
- 01:09, 01:21 and 01:33: further trips after restart attempts.
- 01:15: -14.19 °C; the validated -15 °C boundary had been crossed.
- 01:40: -8.69 °C.
- 01:45: fourth-trip lockout.

When host records resume, a queue-overflow telegram accounts for 53 skipped sequences. The 04:10 status decodes to **5.19 °C air**, while the old gateway recorded approximately -16.5 °C. The snapshot ends at lockout and therefore cannot provide the peak or exact duration above any threshold. Those would require the missing post-lockout controller buffer or an independent calibrated room logger.

## Refrigeration behaviour

Across 30 days, defrost follows approximately **8 compressor-runtime hours**, not wall clock. A normal defrost lasts 26 minutes. Simultaneously due rooms are staggered in the observed priority A, C, B, D, F, E. The controller's high-pressure policy is consistent across other rooms: a five-minute restart delay, four trips within about 60 minutes, then a 90-minute lockout. The E snapshot is a textbook execution of that protection, not evidence of lost cooling capacity.

The structured answer gives fitted thermal coefficients and their confidence. Cooling rates and hysteresis are well constrained by thousands of status cycles. Leakage and shared-wall coupling are materially less certain because they trade off statistically over the narrow controlled temperature band. Bias is independently estimable for A, B, and E after correcting HH-2's certified +1.1 °C error. C and F have no independent probe observations. D has no single valid bias: it drifted from roughly -1.5 °C to +2 °C and was recalibrated on 3 April. Reporting a fixed D, C, or F bias would be fabrication.

## Monitoring and change-control failures

1. **Undocumented second firmware update.** The vendor report says E was only inspected, but TK05 boots with BA payload `0034` at 14:41 on 15 March; the invoice bills two units and IMG_2241 is captioned “unit TK05 after update.”
2. **Parser not made version-aware.** The vendor report itself warned that 3.4 used absolute air temperature. The unchanged parser added setpoint regardless.
3. **Warnings diverted and then made invisible.** Commit `1a83340` moved B/E low warnings to `#alerts-coldchain-old`; Jonas Nguyen archived that channel on 17 March, before the incident.
4. **Untracked severity override.** `deploy/config.override.json` is deliberately gitignored and sets `ALERT_MIN_SEVERITY=critical`. Both named engineers deny creating it. The snapshot contains no host audit record that can resolve authorship or an exact deployment time.
5. **Known physical-link defect left open.** T-0410 had reproduced the exact coupling between a fully open E door and loss of TK05 communications months earlier.
6. **Door events were not decoded or alarmed.** The gateway preserved type 29 only as an unknown token.

The on-call SRE's claim that the 26 March disk-full period meant “nothing was being logged” is too broad: service text logs have a gap, but ledger/controller records continued. The disk problem is not the cause of the 00:48–04:08 telemetry gap; that gap starts much earlier and is controller-specific.

## Product scope

The ledger `lots` table is a stale import and its `moves` table is empty. The dispatch database contains thousands of duplicated/backlogged move jobs, so neither is a defensible source of physical location on its own. The forklift scanner trail, applied as successive physical drops, puts these pallets in E when the door opened:

- **LN-24754 / PL-7664**, dropped in E at 11:58 on 25 March;
- **LN-26450 / PL-8620**, dropped in E at 16:33 and removed to F at 08:22 on 26 March;
- **LN-28604 / PL-6184**, dropped in E at 10:29 on 25 March.

The five lots listed in the postmortem had last physical drops in A, D, D, F, and D respectively, not E. Most importantly, its list omitted LN-26450, the customer lot. The temperature profile, physical residence, and lab signature make the excursion the probable cause of its degradation. Product disposition should nevertheless be based on lot-specific stability assessment; the evidence establishes exposure, while final pharmaceutical causation remains a QA/scientific determination.

## Human attribution and false accounts

Machine evidence refutes the following material claims (the exact quotations are also in `answer.json`): compressor failure; no E firmware change; a known 3.4 sensor fault; no prior cold-room propping by Costa; nobody approaching E after the night lead's observation; and archiving the old channel only after the incident. These false statements do not all imply deliberate deception—several are readily explained by the bad decoder, stale ledger, or mistaken recollection.

It would be improper to name the incident door actor. Badge clock records run 16 minutes slow, but E's reader was nonfunctional. Corrected entrance events put Elif Dubois on site at 21:49 and Noor Costa at 22:03. Both had opportunity; neither opportunity nor the prior wedge photo proves the incident act. Relevant CCTV no longer exists.

## Clock reconciliation

Offsets are defined as record-clock minus true UTC. Gateway, chat, forklift, CCTV, git, tickets, submeter are consistent with UTC (0 minutes). The badge system is **-16 minutes**, and handheld probe device time is **-8 minutes**; these offsets are strongly recovered by matching unlocks and probe checks to type-29 controller events. EXIF local time is **+60 minutes**, directly demonstrated by the rows containing both `DateTimeOriginal` and GPS UTC. Fault-snapshot tick time is anchored to a gateway-received frame rather than treated as wall time.

## Recommendations

1. Quarantine and scientifically assess LN-24754, LN-26450, and LN-28604 immediately; review any downstream splits/shipments. Reconcile and release the five incorrectly scoped lots only after physical-history review.
2. Replace/re-route the E door-frame cable and repair the badge reader. Alarm on door-open duration locally, independent of the same cable and host path.
3. Make decoder selection explicit by boot firmware (`0032` versus `0034`), decode all words/opcodes, and reject compliance use when firmware is unknown. Backfill records using the corrected decoder without overwriting raw evidence.
4. Treat stale-link plus door-open as critical. Use an independent calibrated logger and a separate communications path in every validated room.
5. Remove runtime config files from unmanaged host state. Require reviewed, attributable, expiring changes; log effective configuration and archive/unarchive actions centrally.
6. Restore primary alert routing, eliminate the critical-only override, and test end-to-end paging with synthetic high, low, stale, door, trip, and lockout events.
7. Fix dispatch idempotency and persist applied moves in the ledger. Reconcile scanner, pallet, and WMS state before using location data for quarantine.
8. Synchronize badge, probe, camera and controller clocks to monitored UTC; preserve at least the validated product-retention period of access/CCTV/event evidence.
9. Preserve controller snapshots immediately after events, including post-lockout samples, and obtain the vendor's authoritative TK-5 3.2/3.4 protocol and release notes.
