# Bench report — unit TK01 (room A)

## Summary

Bench captures were taken on unit TK01 for the customer's gateway developer. Requested by Jonas Nguyen on behalf of the integration side; ran the unit through its usual states on the bench rather than in room A itself, tapped the bus, logged raw frames. Nothing dramatic to report, mostly housekeeping so the developer has real traffic to decode against instead of guessing from the manual.

## Message types observed

- 0xeb: defrost cycle
- 0x29: door contact
- 0x11: drain-pan heater
- 0x67: defrost cycle
- 0x55: compressor hold-off
- 0xba: power-up / firmware banner

## Notes

Two distinct codes for defrost (0xeb and 0x67) came through on separate cycles — worth flagging to the developer before they assume it's a single opcode, because it isn't, and the payload lengths differ between the two. Drain-pan heater frames were sparse compared to the others; may just be bench conditions rather than a fault. Power-up banner (0xba) only fires once per cold boot, as expected, captured it on the first bench cycle and didn't chase a second.

Ingrid Schulz reviewed the capture file before handoff. No firmware changes made to TK01 during this exercise; unit returned to stock afterward.

— Z. Byrne
