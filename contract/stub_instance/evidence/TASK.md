# Incident reconstruction: cold-storage excursion

You are the outside investigator hired after a pharmaceutical cold-storage warehouse shipped product that a
customer's stability lab later flagged as degraded. The company's own postmortem exists and confidently names
a cause. Nobody trusts it. You have a frozen snapshot of everything that was collected; nothing is live.

## What you have (all under `/evidence`, read-only)
- `repo/` — the warehouse monitoring stack (gateway, ledger, dispatch, alerting, billing) as deployed, with git history
- `deploy/logs/` — the service logs covering the whole period
- `db/ledger.sql` — a text dump of the ledger database
- `controller/` — raw controller frames recovered from a device ring buffer that never reached the gateway
- `people/` — shift statements, chat export, tickets, badge records, forklift telematics, probe-check sheets,
  receipts, photo metadata, CCTV motion counts, vendor service reports, the utility submeter, the postmortem
- `questions.json` — instance metadata: zones, controller ids, the parameter ids you must estimate, the id
  grammar and enums used in the answer, the held-out frame file
- `ANSWER_SCHEMA.json` — the exact JSON schema your answer must satisfy

## What you must produce: `/work/answer.json`
Four sections, all graded against ground truth you cannot see:
1. **mechanism** — the refrigeration/controller behaviour of this site: the numeric parameters listed in
   `questions.json` (per-zone cooling and leak rates, hysteresis bands, sensor biases, door effect, inter-zone
   coupling, defrost and lockout rules) and the discrete rules (defrost trigger type, defrost stagger order,
   which zones are physically adjacent).
2. **notation** — the controller telegram format: a label for every root the shipped decoder does not know,
   the role of each affix, what changed between firmware versions, and a translation of every frame in the
   held-out ring buffer (per frame: seq, timestamp, zone, main event label, value in engineering units).
3. **causal_chain** — the causes of the missed excursion and the wrong quarantine, as a directed graph over
   typed ids (see `questions.json` id grammar): nodes, edges, root causes, the candidate causes you examined
   and rejected, the lots actually affected, and the excursion window.
4. **timeline** — what people actually did and when (true time, not the clock of whichever record you read it
   from), the clock offset of each record channel in minutes, and the claims in the human documents that are
   false (quote the exact text).
Plus a `confidence` value in [0,1] per section, which is scored for calibration.

## Rules of the engagement
- There is no feedback. Nothing tells you whether any part of your answer is right. The only tool that touches
  your answer is `validate_answer`, which checks JSON schema conformance and nothing else.
- Nothing can be re-run: the services are not running and cannot be started; the controllers are gone.
  Cross-checking the evidence against itself is the only verification available, and it is expected.
- No network. `/evidence` is read-only. `/work` is yours; keep drafts and scratch there.
- Your context is finite. Keep `/work/answer.json` updated as you go; whatever it contains when you stop or
  run out is what is graded. Partial credit is given per field. An empty or missing section scores zero.
- List-valued answers (causal nodes and edges, timeline events, affected lots, false claims) are scored on both
  precision and recall: every wrong or padded entry costs as much as a missed one. Numeric parameters are scored
  against a tolerance, so give your best point estimate for every one.
- The postmortem, statements and chat contain honest mistakes, self-serving accounts, and at least one
  confidently stated wrong theory. Machine records have their own clock problems. Nothing is labelled.
- Finish by ensuring `validate_answer` reports the schema valid, then stop.
