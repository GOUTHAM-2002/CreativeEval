# Postmortem: thermal excursion, cold room E
Author: Victor Larsen (QA)    Published: 2026-04-11    Status: final

## Summary

This report documents the investigation into a thermal excursion in cold room E on the night of 2026-03-30 that was not detected through automated alarming. The event surfaced only after the lab flagged lot LN-29378 during routine release testing, at which point QA opened a full ledger review of room E covering the excursion window. This document is published 2026-04-11.

## Root cause

Root cause: compressor failure on controller VX05. The unit lost cooling capacity during the overnight hours and room temperature drifted outside the validated range for an extended period before recovery began.

## Contributing factors

Two additional failures compounded the mechanical fault and delayed any human response. Alert routing for room E had been moved to a legacy channel some time before the event, so the compressor fault notification was delivered to a distribution list no on-call staff were monitoring that night. Physical access controls were also bypassed. The agency worker propped the room E door open during the night shift. This allowed warm air infiltration on top of the compressor loss and accelerated the temperature rise inside the room. Separately, an unrelated stream of nuisance alerts earlier in the shift led to a suppression action being taken on the monitoring platform. The on-call SRE deployed the severity override that muted the warnings. That override remained active through the excursion window and would have blocked any residual notification even if routing had been correct.

## Timeline

- Night of 2026-03-30: excursion begins in room E; VX05 compressor fails; door propped open by agency worker; no alarm reaches on-call staff due to legacy routing and the active severity override.
- Subsequent days: lab flags lot LN-29378 during release testing, prompting QA to pull the ledger for room E.
- Following that: ledger review completed for the excursion window; quarantine list finalized.
- 2026-04-11: this postmortem published.

## Affected product

- LN-21026
- LN-24790
- LN-24829
- LN-25661
- LN-26290
- LN-26766
- LN-29303
- LN-29333
- LN-29796

## Actions

Alert routing for room E has been restored to the primary on-call channel and will be audited quarterly against all controllers, including VX05. Severity override permissions are being reviewed with SRE leadership to require dual authorization before any warning class can be muted. Door discipline for agency staff on night shift is being retrained, with signage and supervisor spot checks added. All lots on the quarantine list above are held pending disposition per the vendor recall notice on file, and no further release will occur until Quality has closed this investigation.
