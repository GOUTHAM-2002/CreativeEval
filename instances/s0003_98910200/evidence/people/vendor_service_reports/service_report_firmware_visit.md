# Service report — firmware update visit

## Summary

- Site visit conducted 2026-03-15 at Glacier Bay Storage, site JPS45, to carry out scheduled firmware update on refrigeration controllers.

## Work Performed

- Unit TK02 (room B): firmware updated from version 3.2 to 3.4, unit rebooted successfully post-update, controller came back online with no errors reported.
- Unit TK05 (room E): inspected only, no changes made
- Confirmed correct firmware version on TK02 via controller display and local diagnostic menu after reboot.
- Checked TK05 general condition and display readout during inspection; no faults present at time of visit, no update scheduled for this unit on this trip.

## Notes for Site Staff

- Advised site staff on-site that firmware 3.4 changes the air temperature reporting format to an absolute scale rather than the previous relative format used on 3.2.
- Flagged that the gateway parser feeding site monitoring/logging may need to be updated to correctly interpret the new absolute temperature format from TK02, otherwise readings could be misread downstream.
- Informed staff that firmware 3.4 also introduces a 45-entry fault snapshot buffer that is retained on lockout events, which may be useful for future diagnostics on this unit.

## Follow-up

- Recommend site confirm with monitoring/IT contact whether gateway parser update has been scheduled or applied before relying on TK02 readings for compliance logging.
- No further action taken on TK05 this visit; recommend scheduling firmware update separately if required.

Report filed by z.byrne.
