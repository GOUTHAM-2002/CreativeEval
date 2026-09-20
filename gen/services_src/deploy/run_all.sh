#!/usr/bin/env bash
# Start the coldchain stack on one box. Logs go to deploy/logs/.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p deploy/logs
python3 ledger/server.py &
sleep 1
python3 dispatch/server.py &
python3 gateway/server.py &
python3 alerting/server.py &
python3 billing/nightly.py &
wait
