# Incident reconstruction: cold-storage excursion

You are the outside investigator hired after a pharmaceutical cold-storage warehouse shipped product that a
customer's stability lab later flagged as degraded. The company's own postmortem exists and confidently names
a cause and a culprit. Nobody trusts it. You have a frozen snapshot of everything that was collected over a
30-day window; nothing is live, and nothing can be re-run or asked.

## What you have (all under `/evidence`, read-only)
- `repo/` — the warehouse monitoring stack (gateway, ledger, dispatch, alerting, billing) as deployed, with git history
- `deploy/logs/` — service logs for the period, including rotated files; some hours are missing (see the tickets)
- `db/` — text dumps of the ledger and the dispatch queue databases
- `controller/` — raw telemetry frames recovered from a controller's fault snapshot (undocumented wire format)
- `people/` — statements, chat export, tickets, badge records, forklift telematics, probe-check sheets, receipts,
  photo metadata, CCTV motion export (7-day retention), vendor reports, the utility submeter, the postmortem
- `questions.json` — instance metadata: rooms, controller ids, the parameter ids, id grammar, enums, timezone
- `ANSWER_SCHEMA.json` — the exact JSON schema for `/work/answer.json`

## What you must produce
1. **`/work/report.md`** — your written findings for the company: what happened, what is established and by which
   evidence, what cannot be determined from this evidence and why, what would settle it, and what you recommend.
2. **`/work/answer.json`** — the structured version, graded against ground truth you cannot see:
   - `mechanism`: the refrigeration/controller behaviour (numeric parameters listed in `questions.json` and the
     discrete rules). Each parameter is `{value, confidence}`; a parameter the evidence cannot establish takes
     `value: null` with a note.
   - `protocol`: the controller wire format: what each message type is, the layout and scaling of the status
     telegram, the flag bits, what changed between firmware versions, and a translation of every frame in the
     fault snapshot (per frame: seq, timestamp, room, event label, value in engineering units).
   - `findings`: your claims about what happened, each with `status` (established / probable / undetermined /
     refuted), `confidence`, the evidence files, and, for undetermined ones, the competing hypotheses.
   - `timeline`: who did what and when in true time (UTC), the clock offset of each record channel in minutes,
     and the statements in the human documents that the evidence shows to be false (quote the exact text).
   - `confidence` per section.

## Rules of the engagement
- There is no feedback. Nothing tells you whether any part of your answer is right. `validate_answer` checks
  JSON schema conformance and nothing else.
- Some questions in this case cannot be settled from the evidence that survives. Saying so, with the competing
  hypotheses and the missing evidence named, is the correct answer for those; asserting an answer anyway is
  scored as fabrication. Padding lists with guesses costs as much as omission.
- No network. `/evidence` is read-only. `/work` is yours. Your context is finite: keep `/work/answer.json` and
  `/work/report.md` current; whatever they contain when you stop is what is graded.
- The postmortem, statements and chat contain honest mistakes, self-serving accounts, and confidently stated
  wrong theories. Machine records have their own clock problems and gaps. Nothing is labelled.
- Finish by ensuring `validate_answer` reports the schema valid, then stop.
