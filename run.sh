#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a
echo "$(date -Is) run start"

# wait up to 60s for MySQL (it can still be starting right after a VM boot)
for i in $(seq 1 30); do
  (echo > /dev/tcp/127.0.0.1/3306) 2>/dev/null && break
  sleep 2
done

.venv/bin/python -W ignore provisioning/jml.py
if [ -f provisioning/snapshot.py ]; then
  .venv/bin/python -W ignore provisioning/snapshot.py
fi
echo "$(date -Is) run done"
