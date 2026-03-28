#!/bin/bash
# Sets up systemd timers for Oracle Lab.
# Usage: bash ~/oracle-lab/scripts/setup_timers.sh

SRC=/root/oracle-lab/scripts/systemd

echo "Copying service files..."
cp "$SRC/oracle-forecast.service" /etc/systemd/system/ && echo "  oracle-forecast.service OK" || echo "  FAILED"
cp "$SRC/oracle-forecast.timer" /etc/systemd/system/ && echo "  oracle-forecast.timer OK" || echo "  FAILED"
cp "$SRC/oracle-iteration.service" /etc/systemd/system/ && echo "  oracle-iteration.service OK" || echo "  FAILED"
cp "$SRC/oracle-iteration.timer" /etc/systemd/system/ && echo "  oracle-iteration.timer OK" || echo "  FAILED"
cp "$SRC/oracle-gitpush.service" /etc/systemd/system/ && echo "  oracle-gitpush.service OK" || echo "  FAILED"
cp "$SRC/oracle-gitpush.timer" /etc/systemd/system/ && echo "  oracle-gitpush.timer OK" || echo "  FAILED"

echo ""
echo "Enabling timers..."
systemctl daemon-reload
systemctl enable --now oracle-forecast.timer && echo "  oracle-forecast.timer enabled" || echo "  FAILED"
systemctl enable --now oracle-iteration.timer && echo "  oracle-iteration.timer enabled" || echo "  FAILED"
systemctl enable --now oracle-gitpush.timer && echo "  oracle-gitpush.timer enabled" || echo "  FAILED"

echo ""
echo "=== Active timers ==="
systemctl list-timers oracle-*
