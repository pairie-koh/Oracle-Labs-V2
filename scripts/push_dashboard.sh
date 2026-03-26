#!/bin/bash
# Oracle Lab — Push fresh data to the public dashboard repo
# Runs after each forecast cycle (called from run_cycle.sh or cron)
#
# Prerequisites on the droplet:
#   1. Clone the dashboard repo: git clone https://github.com/YOUR_USERNAME/oracle-lab-dashboard.git ~/oracle-lab-dashboard
#   2. Set up git push auth (same as oracle-lab: token or SSH key)

ORACLE_LAB="/home/oracle/oracle-lab"
DASHBOARD="/home/oracle/oracle-lab-dashboard"
LOGFILE="$ORACLE_LAB/logs/dashboard_push.log"

TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "=== Dashboard update: $TIMESTAMP ===" >> "$LOGFILE"

# Check dashboard repo exists
if [ ! -d "$DASHBOARD/.git" ]; then
    echo "ERROR: Dashboard repo not found at $DASHBOARD. Clone it first." >> "$LOGFILE"
    exit 1
fi

mkdir -p "$DASHBOARD/data"

# Copy data files
cp "$ORACLE_LAB/contracts/active_contracts.json"          "$DASHBOARD/data/active_contracts.json"      2>/dev/null
cp "$ORACLE_LAB/briefings/latest.json"                    "$DASHBOARD/data/briefing.json"              2>/dev/null
cp "$ORACLE_LAB/state/current.json"                       "$DASHBOARD/data/state.json"                 2>/dev/null
cp "$ORACLE_LAB/rolling_scores_history.csv"               "$DASHBOARD/data/rolling_scores.csv"         2>/dev/null

# Copy latest LLM predictions file
LATEST_PRED=$(ls -t "$ORACLE_LAB/llm_predictions/predictions_"*.json 2>/dev/null | head -1)
if [ -n "$LATEST_PRED" ]; then
    cp "$LATEST_PRED" "$DASHBOARD/data/llm_predictions.json" 2>/dev/null
fi

echo "  Copied data files" >> "$LOGFILE"

# Generate LLM performance summary (reuses generate_summary from update_data.py)
if [ -n "$OPENROUTER_API_KEY" ]; then
    echo "  Generating performance summary..." >> "$LOGFILE"
    cd "$DASHBOARD"
    python3 -c "from update_data import generate_summary; generate_summary()" >> "$LOGFILE" 2>&1
fi

# Commit and push
cd "$DASHBOARD"
git add data/ >> "$LOGFILE" 2>&1

# Only commit if there are changes
if git diff --cached --quiet; then
    echo "  No changes to push" >> "$LOGFILE"
else
    git commit -m "data: $TIMESTAMP" >> "$LOGFILE" 2>&1
    git push origin main >> "$LOGFILE" 2>&1
    if [ $? -eq 0 ]; then
        echo "  Pushed to dashboard repo" >> "$LOGFILE"
    else
        echo "  ERROR: Push failed" >> "$LOGFILE"
    fi
fi

echo "=== Dashboard update complete ===" >> "$LOGFILE"
