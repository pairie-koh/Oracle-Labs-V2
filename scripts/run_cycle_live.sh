#!/bin/bash
# Oracle Lab — Live Dashboard ("Karpathy mode")
# Runs the data pipeline, then launches 4 agents in tmux panes with --live.
# Usage: ./scripts/run_cycle_live.sh

set -e

# Resolve project root relative to this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Source environment
if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
fi
if [ -f "$PROJECT_ROOT/venv/bin/activate" ]; then
    source "$PROJECT_ROOT/venv/bin/activate"
fi

SESSION="oracle-live"

echo "┌─────────────────────────────────────────────────┐"
echo "│  Oracle Lab — Live Forecast Dashboard           │"
echo "└─────────────────────────────────────────────────┘"
echo ""

# Stage 1: Run data pipeline (visible in current terminal)
echo "▸ [1/3] Running newswire..."
python3 newswire.py 2>&1 || echo "  WARN: newswire failed, continuing with stale facts"

echo "▸ [2/3] Updating state..."
python3 state.py 2>&1 || echo "  WARN: state update failed"

echo "▸ [3/3] Preparing briefing..."
python3 prepare.py 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: prepare failed, cannot proceed"
    exit 1
fi

echo ""
echo "Data pipeline complete. Launching agent dashboard..."
echo ""
sleep 1

# Kill existing session if present
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Create tmux session with first pane (momentum)
tmux new-session -d -s "$SESSION" -x 200 -y 50

# Send momentum command to first pane
tmux send-keys -t "$SESSION" "cd $PROJECT_ROOT && source .env 2>/dev/null; source venv/bin/activate 2>/dev/null; python3 agents/momentum/forecast.py briefings/latest.json --live; echo ''; echo 'Press enter to close.'; read" Enter

# Split horizontally for historian (right pane)
tmux split-window -h -t "$SESSION"
tmux send-keys -t "$SESSION" "cd $PROJECT_ROOT && source .env 2>/dev/null; source venv/bin/activate 2>/dev/null; python3 agents/historian/forecast.py briefings/latest.json --live; echo ''; echo 'Press enter to close.'; read" Enter

# Split the left pane vertically for game_theorist (bottom-left)
tmux select-pane -t "$SESSION:0.0"
tmux split-window -v -t "$SESSION"
tmux send-keys -t "$SESSION" "cd $PROJECT_ROOT && source .env 2>/dev/null; source venv/bin/activate 2>/dev/null; python3 agents/game_theorist/forecast.py briefings/latest.json --live; echo ''; echo 'Press enter to close.'; read" Enter

# Split the right pane vertically for quant (bottom-right)
tmux select-pane -t "$SESSION:0.1"
tmux split-window -v -t "$SESSION"
tmux send-keys -t "$SESSION" "cd $PROJECT_ROOT && source .env 2>/dev/null; source venv/bin/activate 2>/dev/null; python3 agents/quant/forecast.py briefings/latest.json --live; echo ''; echo 'Press enter to close.'; read" Enter

# Select top-left pane
tmux select-pane -t "$SESSION:0.0"

# Attach
tmux attach -t "$SESSION"
