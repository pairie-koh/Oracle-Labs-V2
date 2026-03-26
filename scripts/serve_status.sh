#!/bin/bash
# Oracle Lab — Status Page HTTP Server
# Runs Python's http.server on port 8080, restarts on crash.
# Started by cron @reboot or manually.

cd /home/oracle/oracle-lab
mkdir -p logs status

# Generate initial page if missing
if [ ! -f status/index.html ]; then
    source venv/bin/activate 2>/dev/null
    python3 scripts/generate_status.py 2>/dev/null
fi

while true; do
    echo "[$(date -u)] Starting http.server on port 8080" >> logs/http.log
    venv/bin/python3 -m http.server 8080 --directory status >> logs/http.log 2>&1
    echo "[$(date -u)] http.server exited, restarting in 5s..." >> logs/http.log
    sleep 5
done
