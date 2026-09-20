# Bench report — unit VX01 (room A)

## Bench report — unit VX01 (room A)

Bench captures were taken on unit VX01 for the customer's gateway developer, per request, ahead of any wider rollout on the room A line. Captures were run off the local bus tap, nothing exotic, and logged straight through to the laptop with timestamps left in site time since that is what the gateway will see in the field.

Message types observed and decoded for the developer's reference:

- message type 0xbd: condenser fan
- message type 0x4d: door contact
- message type 0x50: drain-pan heater
- message type 0x74: high-pressure cut-out
- message type 0x1d: compressor hold-off
- message type 0x62: power-up / firmware banner

All six came through clean and repeatable across multiple power cycles of VX01, no dropped frames, no mangled payloads that I could find on inspection. Ordering on power-up was consistent, banner first, hold-off shortly after as expected on a cold start.

Handed the raw capture files and this list over to the developer's side for their own parsing work. No further bench time booked against VX01 unless they come back with decode questions.

— f.okafor
