# Bench report — unit VX01 (room A)

## Summary

Bench captures were taken on unit VX01 for the customer's gateway developer, at their request, ahead of integration work on the Polaris Pharma Logistics site. Unit was pulled from room A stock and run on bench power, not on the live monitoring loop, so nothing here should be read against room A history.

## Method

Standard bench harness, controller left on default addressing. Captures logged raw frames off the serial tap while I cycled the unit through door open/close, forced defrost, and a manual high-pressure trip on the pressure switch. No refrigerant load connected — cabinet was empty and unpowered on the compressor side for most of the run, so timing of compressor-related frames is not representative of field behaviour.

## Message types captured

- message type 0x46: defrost cycle
- message type 0x98: door contact
- message type 0x8b: door contact
- message type 0xd7: high-pressure cut-out
- message type 0x27: compressor hold-off
- message type 0xd3: power-up / firmware banner

## Notes

Two door contact codes (0x98, 0x8b) appear to correspond to the same physical switch under differing debounce states; developer should confirm with firmware source rather than assume from this log alone. Raw dump handed off separately, not attached here.
