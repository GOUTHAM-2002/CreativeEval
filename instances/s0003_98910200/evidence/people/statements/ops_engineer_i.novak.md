# Statement — Ivan Novak (platform engineer)
Taken 2026-04-07

I'm writing this to put on record exactly what I did and didn't do around the TK02 and TK05 alerting after the vendor visit, because I've seen a couple of versions of events floating around and I want to be precise.

After the vendor visit I saw TK02 and TK05 decode at about -40 C, which anyone looking at the feed that day would have seen too. That's not a normal operating value for either controller and I flagged it as soon as I noticed it. The vendor confirmed by phone that the -40 readings are a known sensor fault on the 3.4 boards, which lined up with what I was seeing on the decoded output — a hardware/firmware quirk rather than an actual thermal event in either room.

Separately, and this is the part I want to be very clear about, I did route the two rooms' low-temperature alerts to the legacy channel via a hotfix commit. That was a deliberate, logged change on my part, done so the on-call team wasn't getting paged repeatedly for a fault condition we already knew was spurious. It was not intended to suppress a genuine excursion, and it did not change any severity thresholds.

I want to state plainly that I did not deploy any minimum-severity override. That is not something I wrote, committed, or approved, and I don't believe it should be attributed to my hotfix. If there is a minimum-severity override in the system, it did not come from my change, and I'd ask that whoever is reviewing the commit history check the authorship carefully rather than assuming it's mine because it touched the same alerting path.

For context on the decoder itself: the gateway decoder was written by Dana Whitcombe before they joined the team I'm currently on, and I inherited it as-is. I didn't rewrite its core parsing logic, only the alert routing for TK02 and TK05, and I'm happy to walk through the diff line by line if that helps the investigation.
