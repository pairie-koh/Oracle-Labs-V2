#!/bin/bash
# Sets up systemd timers for Oracle Lab scheduled jobs.
# Run once: bash ~/oracle-lab/scripts/setup_timers.sh

set -e

echo "Creating systemd service and timer files..."

# --- Forecast cycle: every 4 hours at :05 ---
cat > /etc/systemd/system/oracle-forecast.service << 'ENDOFFILE'
[Unit]
Description=Oracle Lab Forecast Cycle

[Service]
Type=oneshot
WorkingDirectory=/root/oracle-lab
ExecStart=/bin/bash -c 'source /root/oracle-lab/.env && source /root/oracle-lab/venv/bin/activate && bash /root/oracle-lab/scripts/run_cycle.sh >> /root/oracle-lab/logs/cron.log 2>&1'
ENDOFFILE

cat > /etc/systemd/system/oracle-forecast.timer << 'ENDOFFILE'
[Unit]
Description=Run Oracle Lab forecast every 4 hours

[Timer]
OnCalendar=*-*-* 00,04,08,12,16,20:05:00
Persistent=true

[Install]
WantedBy=timers.target
ENDOFFILE

# --- Agent iteration: daily at 02:30 ---
cat > /etc/systemd/system/oracle-iteration.service << 'ENDOFFILE'
[Unit]
Description=Oracle Lab Agent Iteration

[Service]
Type=oneshot
WorkingDirectory=/root/oracle-lab
ExecStart=/bin/bash -c 'source /root/oracle-lab/.env && source /root/oracle-lab/venv/bin/activate && bash /root/oracle-lab/scripts/run_iteration.sh >> /root/oracle-lab/logs/cron.log 2>&1'
ENDOFFILE

cat > /etc/systemd/system/oracle-iteration.timer << 'ENDOFFILE'
[Unit]
Description=Run Oracle Lab agent iteration daily

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true

[Install]
WantedBy=timers.target
ENDOFFILE

# --- Git push: every 6 hours at :45 ---
cat > /etc/systemd/system/oracle-gitpush.service << 'ENDOFFILE'
[Unit]
Description=Oracle Lab Git Push

[Service]
Type=oneshot
WorkingDirectory=/root/oracle-lab
ExecStart=/bin/bash -c 'source /root/oracle-lab/.env && bash /root/oracle-lab/scripts/git_push.sh >> /root/oracle-lab/logs/cron.log 2>&1'
ENDOFFILE

cat > /etc/systemd/system/oracle-gitpush.timer << 'ENDOFFILE'
[Unit]
Description=Push Oracle Lab to GitHub every 6 hours

[Timer]
OnCalendar=*-*-* 00,06,12,18:45:00
Persistent=true

[Install]
WantedBy=timers.target
ENDOFFILE

# Enable and start all timers
systemctl daemon-reload
systemctl enable --now oracle-forecast.timer
systemctl enable --now oracle-iteration.timer
systemctl enable --now oracle-gitpush.timer

echo ""
echo "=== Done. Active timers ==="
systemctl list-timers oracle-*
