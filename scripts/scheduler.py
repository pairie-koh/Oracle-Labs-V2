#!/usr/bin/env python3
"""Oracle Lab Scheduler — runs forecast, iteration, and git push on schedule.

Usage: nohup python3 ~/oracle-lab/scripts/scheduler.py &

Survives SSH disconnects via nohup. Logs to ~/oracle-lab/logs/scheduler.log.
"""

import os
import subprocess
import time
from datetime import datetime, timezone

os.chdir("/root/oracle-lab")

LOG = "/root/oracle-lab/logs/scheduler.log"
os.makedirs("/root/oracle-lab/logs", exist_ok=True)


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def run(name, script):
    log(f"Starting {name}...")
    try:
        subprocess.run(
            ["bash", "-c", f"source /root/oracle-lab/.env && source /root/oracle-lab/venv/bin/activate && bash {script}"],
            timeout=3600,
        )
        log(f"{name} finished.")
    except subprocess.TimeoutExpired:
        log(f"{name} TIMED OUT (1 hour limit).")
    except Exception as e:
        log(f"{name} FAILED: {e}")


already_ran = set()

log("Scheduler started. Checking every 60 seconds.")

while True:
    now = datetime.now(timezone.utc)
    hour = now.hour
    minute = now.minute
    weekday = now.weekday()  # 0=Monday
    key = f"{now.date()}-{hour}-{minute}"

    # Forecast cycle: every 4h at :05 (00:05, 04:05, 08:05, 12:05, 16:05, 20:05)
    if hour in (0, 4, 8, 12, 16, 20) and minute == 5:
        run_key = f"forecast-{now.date()}-{hour}"
        if run_key not in already_ran:
            already_ran.add(run_key)
            run("Forecast cycle", "/root/oracle-lab/scripts/run_cycle.sh")

    # Agent iteration: daily at 02:30
    if hour == 2 and minute == 30:
        run_key = f"iteration-{now.date()}"
        if run_key not in already_ran:
            already_ran.add(run_key)
            run("Agent iteration", "/root/oracle-lab/scripts/run_iteration.sh")

    # Git push: every 6h at :45 (00:45, 06:45, 12:45, 18:45)
    if hour in (0, 6, 12, 18) and minute == 45:
        run_key = f"gitpush-{now.date()}-{hour}"
        if run_key not in already_ran:
            already_ran.add(run_key)
            run("Git push", "/root/oracle-lab/scripts/git_push.sh")

    # Clean old keys (keep last 48 hours worth)
    if len(already_ran) > 100:
        already_ran.clear()

    time.sleep(60)
