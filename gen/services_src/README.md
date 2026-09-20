# coldchain-stack

Monitoring and inventory stack for the {{COMPANY}} cold store ({{SITE}}).

| service | what it does |
|---|---|
| `gateway/` | TCP listener for the {{VENDOR}} controller telegram links; decodes what we know (`rh7_decode.py`), stores readings in the ledger, notifies dispatch on activity; `/api/move` for the handheld scanners |
| `ledger/` | SQLite system of record (lots, moves, readings, probe checks, events, alerts, audit) behind a small HTTP API |
| `dispatch/` | pallet reconciliation queue with a worker pool |
| `alerting/` | threshold rules per zone → chat channels (`alerting/routes.json`) |
| `billing/` | nightly zone-hours rollup for invoicing |

Config: `deploy/config.json`, overridden by `deploy/config.override.json` (never commit that one) and `CC_*` env vars.
Start everything with `deploy/run_all.sh`. Logs: `deploy/logs/<service>.log`.

Controller docs: `docs/rh7_integration_note_v2.txt` (vendor note, old firmware), `docs/floor_plan.md`, `docs/runbook.md`.
