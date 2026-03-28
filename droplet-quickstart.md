# Droplet Setup

SSH into your droplet, then paste each section in order.

## 1. Install dependencies

```bash
apt update && apt install -y python3-venv python3-pip git tmux jq
```

## 2. Clone repos

```bash
cd ~
git clone https://github.com/pairie-koh/Oracle-Labs-V2.git oracle-lab
git clone https://github.com/pairie-koh/Trading-Agents-on-Polymarket.git oracle-lab-dashboard
```

## 3. Set up Python

```bash
cd ~/oracle-lab
python3 -m venv venv
source venv/bin/activate
pip install requests numpy pandas scikit-learn
```

## 4. Write API keys

```bash
cat > ~/oracle-lab/.env << 'EOF'
export ANTHROPIC_API_KEY="YOUR_KEY_HERE"
export GITHUB_TOKEN="YOUR_KEY_HERE"
export OPENROUTER_API_KEY="YOUR_KEY_HERE"
export PERPLEXITY_API_KEY="YOUR_KEY_HERE"
EOF
echo 'source ~/oracle-lab/.env' >> ~/.bashrc
source ~/oracle-lab/.env
```

## 5. Set up git

```bash
cd ~/oracle-lab
git config user.name "Oracle Lab Bot"
git config user.email "hello.pairie@gmail.com"
git remote set-url origin https://$GITHUB_TOKEN@github.com/pairie-koh/Oracle-Labs-V2.git

cd ~/oracle-lab-dashboard
git config user.name "Oracle Lab Bot"
git config user.email "hello.pairie@gmail.com"
git remote set-url origin https://$GITHUB_TOKEN@github.com/pairie-koh/Trading-Agents-on-Polymarket.git
```

## 6. Prepare scripts

```bash
cd ~/oracle-lab
chmod +x scripts/*.sh
mkdir -p logs reports status
```

## 7. Test the pipeline

```bash
tmux new -s oracle
cd ~/oracle-lab && source venv/bin/activate && source .env && ./scripts/run_cycle.sh
```

If you get disconnected: `tmux attach -t oracle`

Takes ~15-25 minutes. If it finishes without errors, move to step 8.

## 8. Set up scheduled jobs (systemd timers)

Paste this entire block. It creates three systemd services and timers that replace cron:

```bash
# --- Forecast cycle: every 4 hours at :05 ---
cat > /etc/systemd/system/oracle-forecast.service << 'EOF'
[Unit]
Description=Oracle Lab Forecast Cycle

[Service]
Type=oneshot
WorkingDirectory=/root/oracle-lab
ExecStart=/bin/bash -c 'source /root/oracle-lab/.env && source /root/oracle-lab/venv/bin/activate && bash /root/oracle-lab/scripts/run_cycle.sh >> /root/oracle-lab/logs/cron.log 2>&1'
EOF

cat > /etc/systemd/system/oracle-forecast.timer << 'EOF'
[Unit]
Description=Run Oracle Lab forecast every 4 hours

[Timer]
OnCalendar=*-*-* 00,04,08,12,16,20:05:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# --- Agent iteration: daily at 02:30 ---
cat > /etc/systemd/system/oracle-iteration.service << 'EOF'
[Unit]
Description=Oracle Lab Agent Iteration

[Service]
Type=oneshot
WorkingDirectory=/root/oracle-lab
ExecStart=/bin/bash -c 'source /root/oracle-lab/.env && source /root/oracle-lab/venv/bin/activate && bash /root/oracle-lab/scripts/run_iteration.sh >> /root/oracle-lab/logs/cron.log 2>&1'
EOF

cat > /etc/systemd/system/oracle-iteration.timer << 'EOF'
[Unit]
Description=Run Oracle Lab agent iteration daily

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# --- Git push: every 6 hours at :45 ---
cat > /etc/systemd/system/oracle-gitpush.service << 'EOF'
[Unit]
Description=Oracle Lab Git Push

[Service]
Type=oneshot
WorkingDirectory=/root/oracle-lab
ExecStart=/bin/bash -c 'source /root/oracle-lab/.env && bash /root/oracle-lab/scripts/git_push.sh >> /root/oracle-lab/logs/cron.log 2>&1'
EOF

cat > /etc/systemd/system/oracle-gitpush.timer << 'EOF'
[Unit]
Description=Push Oracle Lab to GitHub every 6 hours

[Timer]
OnCalendar=*-*-* 00,06,12,18:45:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Enable and start all timers
systemctl daemon-reload
systemctl enable --now oracle-forecast.timer
systemctl enable --now oracle-iteration.timer
systemctl enable --now oracle-gitpush.timer

echo ""
echo "=== Active timers ==="
systemctl list-timers oracle-*
```

You should see output showing the next run time for each timer.

## 9. Test it — run the forecast cycle now

```bash
systemctl start oracle-forecast.service
```

This runs the forecast cycle immediately. Watch the logs:

```bash
journalctl -u oracle-forecast.service -f
```

Or check the oracle-lab log:

```bash
tail -f ~/oracle-lab/logs/cron.log
```

Takes ~15-25 minutes. After it finishes, check GitHub for a new `cycle:` commit.

## 10. Verify timers are scheduled

```bash
systemctl list-timers oracle-*
```

This shows exactly when each job will next fire. If a timer is missing, re-run the setup block from step 8.

## Schedule

| Job | Schedule (UTC) | What it does |
|---|---|---|
| Forecast cycle | Every 4h at :05 | Fetches news, runs LLM forecasts, evaluates, pushes dashboard |
| Agent iteration | Daily at 02:30 | Sonnet rewrites agent forecast code based on performance |
| Git push | Every 6h at :45 | Backs up everything to GitHub |
| Log cleanup | Sundays at 03:00 | Deletes logs older than 28 days |

## Check if it's working

```bash
tail -20 ~/oracle-lab/logs/cron.log
```

## Pull latest code

If the repo was updated from another machine:

```bash
cd ~/oracle-lab && git fetch origin && git reset --hard origin/main && chmod +x scripts/*.sh
```

## Fix: Dashboard not updating

```bash
cd ~/oracle-lab-dashboard
source ~/oracle-lab/.env
git remote set-url origin https://$GITHUB_TOKEN@github.com/pairie-koh/Trading-Agents-on-Polymarket.git
git fetch origin
git reset --hard origin/main
cd ~/oracle-lab && source .env && bash scripts/push_dashboard.sh
```

## Recovery after disconnect

```bash
tmux attach -t oracle 2>/dev/null || tmux new -s oracle
```

If there's a merge conflict:

```bash
cd ~/oracle-lab && git fetch origin && git reset --hard origin/main
```

## Fix: Stuck at `>` prompt

Press `Ctrl+C` to break out. Then retry the command.
