# Service report — firmware update visit

## Summary

- Vendor visit performed 2026-06-08 at Borealis Coldchain site ZLH62 by F. Okafor.
- Scope: firmware update on unit VX03 (room C), inspection of unit VX05 (room E).

## Work Performed

- VX03 (room C): updated firmware from version 3.2 to 3.4, unit rebooted successfully post-update. Controller came back online and reported normal status after restart.
- Unit VX05 (room E): inspected only, no changes made
- No parts replaced during this visit; work limited to software/firmware scope as scheduled.

## Notes for Site Staff

- Advised on-site staff that firmware 3.4 changes the air temperature reporting format to an absolute value rather than the prior format used under 3.2. This may require the gateway parser configuration to be reviewed/updated on the site side to interpret the new values correctly. Recommend site IT or controls team confirm downstream logging/alarm systems are reading VX03 correctly following the change.
- Also noted that firmware 3.4 introduces a fault snapshot buffer that retains the last 45 entries at time of a lockout event. This should assist future diagnostics but staff should be aware log depth is limited to that count.

## Recommendations

- Site to verify gateway parsing of VX03 temperature data within the next few days and report any discrepancies.
- No further action required for VX05 at this time; inspection found no issues warranting service.
- Recommend scheduling firmware review for remaining units in a future visit if standardization across room controllers is desired.

End of report — F. Okafor (f.okafor)
