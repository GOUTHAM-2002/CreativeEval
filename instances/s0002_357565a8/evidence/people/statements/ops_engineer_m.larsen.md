# Statement — Maya Larsen (platform engineer)
Taken 2026-07-01

I'm writing this to lay out exactly what I saw and did around the VX03 and VX05 alerting after the vendor visit, because I think there's some confusion about the sequence.

After the vendor left, I noticed VX03 and VX05 decode at about -40 C on the dashboard, both units, roughly the same window. That reading looked wrong to me right away, since it's well outside anything a live cold room should show unless something upstream failed hard. I want to be clear about the decoder itself: the gateway decoder was written by Dana Whitcombe before I joined the team, so any quirks in how it parses raw sensor frames from the 3.4 boards predate my involvement entirely. I inherited that code, I didn't design it, and I've said as much before.

Given the alert noise coming out of both rooms, I routed the two rooms' low-temperature alerts to the legacy channel via a hotfix commit. My reasoning at the time was that the new alert pipeline was flooding on-call with repeated pages for what looked like a decode artifact rather than a genuine excursion, and the legacy channel gave us a slower, more filtered path while we sorted out whether the readings were real. I want to state plainly that I did not deploy any minimum-severity override on those alerts. I know that's been suggested, but that wasn't part of my commit, and I'd push back hard on anyone reading intent like that into what was a routing change, not a severity change.

The vendor confirmed by phone that the -40 readings are a known sensor fault on the 3.4 boards, which lines up with what I saw and why I treated it as a decode issue rather than an actual temperature event. I'm happy to walk through the commit line by line with anyone who wants to verify what it touched and what it didn't.
