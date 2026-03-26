#!/bin/bash
# Oracle Lab — Iteration Cycle (runs daily at 02:30)
# Uses Sonnet via OpenRouter to modify each agent's forecast.py.
# No ANTHROPIC_API_KEY needed — only OPENROUTER_API_KEY.

source /home/oracle/oracle-lab/.env
source /home/oracle/oracle-lab/venv/bin/activate
cd /home/oracle/oracle-lab

DATE=$(date +%Y-%m-%d)
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
LOGFILE="logs/iteration_${DATE}.log"
STATUS_FILE="status/iteration_status.json"

mkdir -p logs status

echo "=== Iteration cycle start: $(date) ===" | tee -a "$LOGFILE"

# Initialize iteration status JSON
python3 -c "
import json, os
status = {
    'date': '$DATE',
    'timestamp': '$TIMESTAMP',
    'agents': {},
    'status': 'running'
}
# Preserve history from previous runs
history = []
if os.path.exists('$STATUS_FILE'):
    try:
        old = json.load(open('$STATUS_FILE'))
        history = old.get('history', [])
    except: pass
status['history'] = history
with open('$STATUS_FILE', 'w') as f:
    json.dump(status, f, indent=2)
"

for agent in momentum historian game_theorist quant; do
    echo "--- Iterating: $agent ---" | tee -a "$LOGFILE"

    AGENT_LOG="logs/iteration_${agent}_${DATE}.log"

    # Capture methodology version before iteration
    PREV_VERSION=$(python3 -c "
import json
try:
    sc = json.load(open('agents/$agent/scorecard.json'))
    print(sc.get('methodology_version', '?'))
except: print('?')
")

    ITER_START=$(date +%s)

    # Call the Python iteration script (uses OpenRouter, no ANTHROPIC_API_KEY needed)
    timeout 300 python3 scripts/iterate_agent.py "$agent" \
        >> "$AGENT_LOG" 2>&1

    EXIT_CODE=$?
    ITER_END=$(date +%s)
    ITER_DURATION=$((ITER_END - ITER_START))

    # Capture methodology version after iteration
    NEW_VERSION=$(python3 -c "
import json
try:
    sc = json.load(open('agents/$agent/scorecard.json'))
    print(sc.get('methodology_version', '?'))
except: print('?')
" 2>/dev/null)

    # Also check forecast.py directly for version
    NEW_VERSION_CODE=$(grep -oP "METHODOLOGY_VERSION\s*=\s*['\"]([^'\"]+)['\"]" "agents/$agent/forecast.py" 2>/dev/null | grep -oP "['\"]([^'\"]+)['\"]" | tr -d "'\"" || echo "?")

    if [ $EXIT_CODE -eq 0 ]; then
        RESULT="ok"
        echo "  $agent: OK (${ITER_DURATION}s, v${PREV_VERSION} → v${NEW_VERSION_CODE})" | tee -a "$LOGFILE"
    elif [ $EXIT_CODE -eq 124 ]; then
        RESULT="timeout"
        echo "  $agent: TIMEOUT (5 min limit)" | tee -a "$LOGFILE"
    else
        RESULT="failed"
        echo "  $agent: FAILED (exit $EXIT_CODE, ${ITER_DURATION}s)" | tee -a "$LOGFILE"
    fi

    # Update iteration status
    python3 -c "
import json
with open('$STATUS_FILE') as f:
    status = json.load(f)
status['agents']['$agent'] = {
    'result': '$RESULT',
    'exit_code': $EXIT_CODE,
    'duration_seconds': $ITER_DURATION,
    'version_before': '$PREV_VERSION',
    'version_after': '$NEW_VERSION_CODE'
}
with open('$STATUS_FILE', 'w') as f:
    json.dump(status, f, indent=2)
"
done

# Determine overall status
python3 -c "
import json
with open('$STATUS_FILE') as f:
    status = json.load(f)
agents = status['agents']
if all(a['result'] == 'ok' for a in agents.values()):
    status['status'] = 'ok'
elif any(a['result'] == 'ok' for a in agents.values()):
    status['status'] = 'partial'
else:
    status['status'] = 'failed'
# Add this run to history (keep last 14 days)
entry = {'date': status['date'], 'timestamp': status['timestamp'], 'status': status['status'], 'agents': status['agents']}
status['history'] = ([entry] + status.get('history', []))[:14]
with open('$STATUS_FILE', 'w') as f:
    json.dump(status, f, indent=2)
"

# Commit all changes
git add -A
git commit -m "iteration: $DATE" || echo "WARN: git commit failed (no changes or no identity)" | tee -a "$LOGFILE"

echo "=== Iteration cycle complete: $(date) ===" | tee -a "$LOGFILE"
