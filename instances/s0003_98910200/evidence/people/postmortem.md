# Postmortem: thermal excursion, cold room E
Author: Noor Larsen (QA)    Published: 2026-04-07    Status: final

## Summary

This report documents the thermal excursion in cold room E on the night of 2026-03-25, which was not alarmed at the time it occurred and only came to light after the lab flagged lot LN-26450 during routine stability testing. This postmortem is being published on 2026-04-07 following a review of controller logs, ledger records, and shift documentation.

## Root cause

Root cause: compressor failure on controller TK05. The unit lost cooling capacity overnight and room E temperature drifted outside the validated range for an extended period without triggering a response from staff on shift.

## Contributing factors

Alert routing for room E had been moved to a legacy channel during a prior systems change, and this was not caught in subsequent change control review. As a result, the compressor fault did not reach the monitoring staff who would normally have responded. The on-call SRE deployed the severity override that muted the warnings, believing the alerts to be related to a known, unrelated noise issue on an adjacent controller. This override remained active through the excursion window.

The agency worker propped the room E door open during the night shift. This is understood to have accelerated the temperature rise inside the room, though it was not the initiating event.

## Timeline

- Night of 2026-03-25: compressor failure begins on TK05; room E excursion begins; no alarm reaches staff due to legacy channel routing and active severity override.
- Following days: excursion goes undetected operationally.
- Lab testing later flags lot LN-26450 as out of specification, prompting investigation.
- 2026-04-07: this postmortem published.

## Affected product

- LN-24872
- LN-26219
- LN-26259
- LN-28595
- LN-29864

## Actions

The quarantine list above reflects every lot the ledger shows present in room E during the excursion window and has been placed on hold pending disposition. The vendor recall notice on file for the affected product line is cited as guidance for disposition decisions. Alert routing for room E is being restored to the primary monitoring channel, and a review of severity override permissions is underway to prevent unauthorized muting of active alarms. Night shift door discipline for room E is being retrained with agency staff.
