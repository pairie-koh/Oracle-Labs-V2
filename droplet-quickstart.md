# Droplet Setup

SSH into your droplet, then run these commands.

## 0. If the terminal is stuck

Press `Ctrl+C` to get your terminal back.

## 1. Pull latest code

```bash
cd ~/oracle-lab && git fetch origin && git reset --hard origin/main && chmod +x scripts/*.sh && mkdir -p logs reports status
```

## 2. Start the scheduler

```bash
nohup python3 ~/oracle-lab/scripts/scheduler.py > /dev/null 2>&1 &
echo "Scheduler running in background (PID: $!)"
```

That's it. The scheduler runs in the background, survives SSH disconnects, and handles all jobs:
- Forecast cycle every 4h at :05
- Agent iteration daily at 02:30
- Git push every 6h at :45

You can close SSH. It keeps running.

## Check if it's working

```bash
tail -20 ~/oracle-lab/logs/scheduler.log
```

## Check if the scheduler is running

```bash
ps aux | grep scheduler.py | grep -v grep
```

If it's not running, start it again with step 2.

## Stop the scheduler

```bash
pkill -f scheduler.py
```

## Check forecast logs

```bash
tail -20 ~/oracle-lab/logs/cron.log
```
