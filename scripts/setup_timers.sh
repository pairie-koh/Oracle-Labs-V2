#!/bin/bash
# Sets up systemd timers for Oracle Lab.
# Usage: bash ~/oracle-lab/scripts/setup_timers.sh

SRC=/root/oracle-lab/scripts/systemd

echo "Copying service files (stripping Windows line endings)..."
for f in oracle-forecast.service oracle-forecast.timer oracle-iteration.service oracle-iteration.timer oracle-gitpush.service oracle-gitpush.timer; do
    sed 's/\r$//' "$SRC/$f" > "/etc/systemd/system/$f" && echo "  $f OK" || echo "  $f FAILED"
done

echo ""
echo "Enabling timers..."
systemctl daemon-reload
systemctl enable --now oracle-forecast.timer && echo "  oracle-forecast.timer enabled" || echo "  FAILED"
systemctl enable --now oracle-iteration.timer && echo "  oracle-iteration.timer enabled" || echo "  FAILED"
systemctl enable --now oracle-gitpush.timer && echo "  oracle-gitpush.timer enabled" || echo "  FAILED"

echo ""
echo "=== Active timers ==="
systemctl list-timers oracle-*
