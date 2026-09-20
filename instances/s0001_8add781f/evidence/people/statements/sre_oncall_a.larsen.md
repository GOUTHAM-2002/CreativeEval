# Statement — Ana Larsen (on-call SRE)
Taken 2026-04-11

I was on call the night of 2026-03-22 and I got paged over and over by low-temperature warnings, back to back, enough that I lost count somewhere after the fourth or fifth page. It wasn't a one-off blip, it kept re-firing, which is usually a sign something upstream is flapping rather than an actual sustained excursion, but I still had to work each page as if it was real because that's the job.

I want to be clear on one thing since it's come up: I did not deploy any minimum-severity override on the alerting config that night or at any point during my shift. I have no record of touching that file, no shell history for it, nothing in my session logs. When I came back on in the morning the override file was just sitting there already in place. I didn't put it there and I'd like whoever did to own up to it, because it's making my on-call history look messier than it is.

Separately, and I think unrelated, the gateway host's disk filled up on 2026-03-31, roughly from 12:03 pm to about 3:11 pm. Nothing was logged in that window at all, which is annoying from a forensic standpoint because it's a dead zone in the record right when people want answers. I cleared space and rotated the logs once I caught it, so it shouldn't recur in the same way, but it does mean anyone looking at that afternoon is looking at a gap.

One more thing worth noting for context: the nightly billing rollup locks the ledger around 01:00, so anything touching shared state anywhere near that time tends to get queued or delayed, and that's just normal behavior, not an incident by itself. I mention it only because people keep asking why certain writes stalled that night and that's the reason, not anything sinister.
