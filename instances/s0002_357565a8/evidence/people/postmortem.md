# Postmortem: thermal excursion, cold room E
Author: Ana Schulz (QA)    Published: 2026-07-01    Status: final

## Summary

This postmortem covers the thermal excursion in cold room E on the night of 2026-06-19, which was not alarmed at the time it occurred. The event was only identified after the quality lab flagged lot LN-22416 during a routine release check, several days after the excursion had already resolved on its own. This report documents the root cause, the contributing factors that prevented timely alarming, the reconstructed timeline, the affected product, and the corrective actions being taken.

## Root cause

Root cause: compressor failure on controller VX05. The failure caused the room E setpoint to drift upward over several hours without triggering an audible or dispatched alarm to any on-shift personnel.

## Contributing factors

Alert routing for room E had been moved to a legacy channel during a prior integration with Borealis Coldchain and was never migrated back onto the primary paging system, so the compressor fault notification was generated but not delivered to anyone on call. The on-call SRE deployed the severity override that muted the warnings. This override had been applied earlier that same week to silence an unrelated noisy-alarm complaint on a different room and was still active, so it also suppressed the room E compressor fault. The agency worker propped the room E door open during the night shift, which is believed to have accelerated the temperature rise once the compressor had already failed, though it was not itself the triggering fault.

## Timeline

- Night of 2026-06-19: compressor VX05 fails in room E; excursion begins, unalarmed.
- Same night: door propped open by agency worker during rounds, worsening the drift.
- Days later: quality lab flags lot LN-22416 on release testing, prompting investigation.
- 2026-07-01: this postmortem published.

## Affected product

- LN-20373
- LN-20976
- LN-21231
- LN-21956
- LN-22116
- LN-22641
- LN-23525
- LN-24714
- LN-25020
- LN-25578
- LN-26885
- LN-28611

## Actions

The quarantine list above represents every lot the ledger shows present in room E during the excursion window and has been held pending disposition, cross-referenced against the vendor recall notice on file for guidance on stability limits. Alert routing for room E is being restored to the primary channel, the severity override capability is being restricted to time-boxed use with mandatory expiry, and door-monitoring procedures for agency staff are under review with site security.
