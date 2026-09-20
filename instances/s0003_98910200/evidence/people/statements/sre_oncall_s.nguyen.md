# Statement — Sofia Nguyen (on-call SRE)
Taken 2026-04-07

I got paged repeatedly through the night of 2026-03-17 for low-temperature warnings, one after another, and honestly by about the fourth or fifth page I was already annoyed because the pattern didn't look like a real excursion, it looked like flapping. I acknowledged each one as it came in, checked the dashboards, and nothing on the sensor side gave me a clean story, so I kept escalating internally rather than just silencing anything.

On the override question — I want to be direct about this because I know it's come up: I did not deploy the minimum-severity override. I don't run overrides like that off-hours without a ticket, and there was no ticket for it that night. When I came in the next morning the file was just sitting there, already present, and I remember being confused because I hadn't touched it and nobody had told me it had been pushed. I flagged it and moved on, but I want that on record.

Separately, on 2026-03-26 I dealt with the gateway host's disk filling up. That ran from about Thu 26 Mar, 12:05 pm through about Thu 26 Mar, 3:17 pm, and for that whole stretch nothing was being logged, which is obviously not great from an audit standpoint. I freed up space on the volume and rotated the logs once I had room, but I can't reconstruct what happened operationally in that gap because there's simply nothing written down for it. That's a known blind spot and I'd flag it as a real gap, not just paperwork.

Last thing, more of a standing constraint than an incident: the nightly billing rollup locks the ledger around 01:00, so anything touching that process or adjacent systems has to be timed around that lock or you get contention. I mention it because it's relevant context for anyone trying to line up what could or couldn't have been changed overnight.
