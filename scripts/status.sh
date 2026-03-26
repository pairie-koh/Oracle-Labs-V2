#!/bin/bash
# Oracle Lab — Quick Status Check
# Usage: ./scripts/status.sh

cd /home/oracle/oracle-lab

echo "=== Oracle Lab Status ==="
echo "Time: $(date -u '+%Y-%m-%d %H:%M UTC')"
echo ""

# Last cycle report
if [ -f reports/latest.txt ]; then
    cat reports/latest.txt
else
    echo "(No cycle report yet)"
fi

echo ""
echo "── System ──"
echo "  Cron jobs: $(crontab -l 2>/dev/null | grep -c oracle-lab) active"

# HTTP status page
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/ 2>/dev/null)
if [ "$HTTP_CODE" = "200" ]; then
    echo "  Status page: UP (port 8080)"
else
    echo "  Status page: DOWN"
fi

echo "  Log files: $(ls logs/*.log 2>/dev/null | wc -l)"
echo "  Forecast logs: $(ls agents/*/log/*.json 2>/dev/null | wc -l) total across agents"
echo "  Briefings: $(ls briefings/*.json 2>/dev/null | wc -l)"
echo "  Last git push: $(git log --oneline -1 --format='%ar')"
echo "  Disk: $(df -h / | tail -1 | awk '{print $5 " used"}')"
echo ""

# Errors in last cycle log
LAST_LOG=$(ls -t logs/cycle_*.log 2>/dev/null | head -1)
if [ -n "$LAST_LOG" ]; then
    ERRORS=$(grep -ci 'error\|failed\|traceback' "$LAST_LOG" 2>/dev/null)
    if [ "$ERRORS" -gt 0 ]; then
        echo "  WARNING: $ERRORS error(s) in last cycle log ($LAST_LOG)"
        grep -i 'error\|failed\|traceback' "$LAST_LOG" | tail -3
    else
        echo "  Last cycle: clean (no errors)"
    fi
fi
