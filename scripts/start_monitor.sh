#!/bin/bash
SESSION="oracle-lab"
PROJECT="/root/oracle-lab"

# Kill existing session
tmux kill-session -t $SESSION 2>/dev/null

# Window 0: Dashboard (4 panes)
tmux new-session -d -s $SESSION -n "dashboard" -c "$PROJECT"

# Top-left: leaderboard (auto-refreshes every 60s)
tmux send-keys -t $SESSION "watch -n 60 'echo \"=== ORACLE LAB LEADERBOARD ===\"; echo; cat scoreboard/latest.json 2>/dev/null | python3 -m json.tool 2>/dev/null || echo \"No scores yet\"; echo; echo \"=== LAST CYCLE ===\"; tail -5 logs/cron.log 2>/dev/null'" Enter

# Top-right: latest briefing facts count
tmux split-window -h -t $SESSION -c "$PROJECT"
tmux send-keys -t $SESSION "watch -n 60 'echo \"=== LATEST BRIEFING ===\"; ls -la briefings/ 2>/dev/null | tail -5; echo; LATEST=\$(ls briefings/*.json 2>/dev/null | tail -1); if [ -n \"\$LATEST\" ]; then echo \"Facts:\"; cat \$LATEST | python3 -c \"import sys,json; b=json.load(sys.stdin); print(f\\\"  Fresh facts: {len(b.get(\\\\\\\"fresh_facts\\\\\\\",[]))}\\\"); print(f\\\"  Prices: {b.get(\\\\\\\"market_prices\\\\\\\",{})}\\\")\" 2>/dev/null; fi'" Enter

# Bottom-left: cron log tail
tmux split-window -v -t $SESSION:0.0 -c "$PROJECT"
tmux send-keys -t $SESSION "tail -f logs/cron.log 2>/dev/null || echo 'No cron log yet. Waiting...'" Enter

# Bottom-right: latest methodology changes
tmux split-window -v -t $SESSION:0.1 -c "$PROJECT"
tmux send-keys -t $SESSION "watch -n 300 'echo \"=== LATEST METHODOLOGY CHANGES ===\"; for a in momentum historian game_theorist quant; do echo; echo \"--- \$a ---\"; ls agents/\$a/log/methodology_changes/*.md 2>/dev/null | tail -1 | xargs cat 2>/dev/null || echo \"  (no changes yet)\"; done'" Enter

# Window 1: Interactive (for when you want to poke around)
tmux new-window -t $SESSION -n "explore" -c "$PROJECT"
tmux send-keys -t $SESSION "source venv/bin/activate && source .env && echo 'Ready. Try: claude -C agents/historian'" Enter

# Go back to dashboard
tmux select-window -t $SESSION:0
tmux select-pane -t $SESSION:0.0

echo "Oracle Lab monitor started. Attach with: tmux attach -t oracle-lab"
