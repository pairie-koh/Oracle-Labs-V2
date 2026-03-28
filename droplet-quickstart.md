# Droplet Setup

SSH into your droplet, then paste each block in order.

## 1. Pull latest code

```bash
cd ~/oracle-lab && git fetch origin && git reset --hard origin/main && chmod +x scripts/*.sh && mkdir -p logs reports status
```

## 2. Set up scheduled jobs and run the first cycle

Paste this entire block:

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

# Run the first forecast cycle right now
echo ""
echo "=== Starting first forecast cycle ==="
systemctl start oracle-forecast.service
echo "Cycle started. Watch logs with: tail -f ~/oracle-lab/logs/cron.log"
```

After pasting, you should see the active timers with their next run times, then the forecast cycle starts immediately.

Watch it run:

```bash
tail -f ~/oracle-lab/logs/cron.log
```

Takes ~15-25 minutes. After it finishes, check GitHub for a new `cycle:` commit.

## Verify timers are scheduled

```bash
systemctl list-timers oracle-*
```

## Check logs

```bash
tail -20 ~/oracle-lab/logs/cron.log
journalctl -u oracle-forecast.service --no-pager | tail -20
```
