#!/bin/bash
# Oracle Lab — Forecast Cycle (runs every 4 hours)
# Fetches data, runs LLM forecasts on rolling contracts, runs deterministic agents, evaluates.

source /root/oracle-lab/.env
source /root/oracle-lab/venv/bin/activate
cd /root/oracle-lab
mkdir -p logs reports status

TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
LOGFILE="logs/cycle_$(date +%Y%m%dT%H%M).log"

echo "=== Forecast cycle start: $TIMESTAMP ===" | tee -a "$LOGFILE"

# Stage 1: Gather data
echo "[1/11] Running newswire..." | tee -a "$LOGFILE"
python3 newswire.py >> "$LOGFILE" 2>&1
if [ $? -ne 0 ]; then
    echo "WARN: newswire failed, continuing with empty/stale facts" | tee -a "$LOGFILE"
fi

echo "[2/11] Updating state..." | tee -a "$LOGFILE"
python3 state.py >> "$LOGFILE" 2>&1 || echo "WARN: state update failed" >> "$LOGFILE"

echo "[3/11] Preparing briefing..." | tee -a "$LOGFILE"
python3 prepare.py >> "$LOGFILE" 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: prepare failed, aborting cycle" | tee -a "$LOGFILE"
    exit 1
fi

# Stage 2: Fetch rolling contracts + asset prices + LLM forecast
echo "[4/11] Fetching rolling contracts..." | tee -a "$LOGFILE"
python3 rolling_contracts.py >> "$LOGFILE" 2>&1
if [ $? -ne 0 ]; then
    echo "WARN: rolling contracts fetch failed, LLM forecast will skip rolling" | tee -a "$LOGFILE"
fi

echo "[5/11] Fetching Hyperliquid prices (24/7 perps)..." | tee -a "$LOGFILE"
python3 hyperliquid.py >> "$LOGFILE" 2>&1
if [ $? -ne 0 ]; then
    echo "WARN: Hyperliquid fetch failed, LLM forecast will run without asset prices" | tee -a "$LOGFILE"
fi

echo "[6/11] Fetching GDELT news context..." | tee -a "$LOGFILE"
python3 gdelt.py --timespan 2d >> "$LOGFILE" 2>&1
if [ $? -ne 0 ]; then
    echo "WARN: GDELT fetch failed, LLM forecast will run without news context" | tee -a "$LOGFILE"
fi

echo "[7/11] Running LLM forecast on all contracts..." | tee -a "$LOGFILE"
python3 llm_forecast.py >> "$LOGFILE" 2>&1
if [ $? -eq 0 ]; then
    echo "  LLM forecast: OK" | tee -a "$LOGFILE"
else
    echo "  LLM forecast: FAILED" | tee -a "$LOGFILE"
fi

# Stage 3: Deterministic agent forecasts (independent — one failure doesn't block others)
echo "[8/11] Running agent forecasts..." | tee -a "$LOGFILE"
for agent in momentum historian game_theorist quant; do
    python3 "agents/$agent/forecast.py" briefings/latest.json >> "$LOGFILE" 2>&1
    if [ $? -eq 0 ]; then
        echo "  $agent: OK" | tee -a "$LOGFILE"
    else
        echo "  $agent: FAILED" | tee -a "$LOGFILE"
    fi
done

# Stage 4: Score matured predictions (deterministic agents + rolling resolution)
echo "[9/11] Evaluating..." | tee -a "$LOGFILE"
python3 evaluate.py >> "$LOGFILE" 2>&1 || echo "WARN: evaluation failed" >> "$LOGFILE"
python3 evaluate_rolling.py >> "$LOGFILE" 2>&1 || echo "WARN: rolling evaluation failed" >> "$LOGFILE"

# Stage 5: Generate cycle report
echo "[10/11] Generating report..." | tee -a "$LOGFILE"
mkdir -p /root/oracle-lab/reports
python3 report.py >> "$LOGFILE" 2>&1 || echo "WARN: report generation failed" >> "$LOGFILE"

# Stage 6: Update status page + progress plot
echo "[11/11] Updating status page..." | tee -a "$LOGFILE"
python3 scripts/generate_status.py >> "$LOGFILE" 2>&1 || echo "WARN: status page generation failed" >> "$LOGFILE"
if [ -f scores_history.csv ]; then
    python3 scripts/plot_progress.py >> "$LOGFILE" 2>&1 && cp progress.png status/progress.png 2>/dev/null
fi

# Stage 7: Commit results
git add -A >> "$LOGFILE" 2>&1
git commit -m "cycle: $TIMESTAMP" --allow-empty >> "$LOGFILE" 2>&1

# Stage 8: Update public dashboard
echo "[post] Updating dashboard..." | tee -a "$LOGFILE"
/root/oracle-lab/scripts/push_dashboard.sh >> "$LOGFILE" 2>&1 || echo "WARN: dashboard update failed" >> "$LOGFILE"

echo "=== Forecast cycle complete: $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LOGFILE"
