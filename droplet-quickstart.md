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

## 8. Test cron (verify it actually fires)

First, schedule two test jobs a few minutes from now:

```bash
NOW_MIN=$(date -u +%M)
NOW_HOUR=$(date -u +%H)
TEST1=$(( (NOW_MIN + 3) % 60 ))
TEST2=$(( (NOW_MIN + 8) % 60 ))
HOUR1=$NOW_HOUR
HOUR2=$NOW_HOUR
if [ $TEST1 -lt $NOW_MIN ]; then HOUR1=$(( (NOW_HOUR + 1) % 24 )); fi
if [ $TEST2 -lt $NOW_MIN ]; then HOUR2=$(( (NOW_HOUR + 1) % 24 )); fi

crontab -r 2>/dev/null
cat > /tmp/oracle_cron << EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
$TEST1 $HOUR1 * * * echo "TEST 1 fired at \$(date -u)" >> /root/oracle-lab/logs/cron_test.log
$TEST2 $HOUR2 * * * echo "TEST 2 fired at \$(date -u)" >> /root/oracle-lab/logs/cron_test.log
EOF
crontab /tmp/oracle_cron
rm /tmp/oracle_cron
mkdir -p /root/oracle-lab/logs

echo ""
echo "Test jobs scheduled:"
crontab -l
echo ""
echo "Check in a few minutes with: cat ~/oracle-lab/logs/cron_test.log"
```

Wait ~10 minutes, then check:

```bash
cat ~/oracle-lab/logs/cron_test.log
```

You should see two lines like:

```
TEST 1 fired at Sat Mar 28 12:03:00 UTC 2026
TEST 2 fired at Sat Mar 28 12:08:00 UTC 2026
```

If you see both lines, cron works. Move to step 9.

If the file is empty or missing, cron is broken. Run:

```bash
sudo systemctl status cron | head -5
sudo systemctl start cron
sudo systemctl enable cron
```

Then redo step 8.

## 9. Set up real cron jobs

Once the test in step 8 passes, install the real schedule:

```bash
crontab -r 2>/dev/null
cat > /tmp/oracle_cron << 'EOF'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
5 */4 * * * /root/oracle-lab/scripts/run_cycle.sh >> /root/oracle-lab/logs/cron.log 2>&1
30 2 * * * /root/oracle-lab/scripts/run_iteration.sh >> /root/oracle-lab/logs/cron.log 2>&1
45 */6 * * * /root/oracle-lab/scripts/git_push.sh >> /root/oracle-lab/logs/cron.log 2>&1
0 3 * * 0 find /root/oracle-lab/logs -name "*.log" -mtime +28 -delete
EOF
crontab /tmp/oracle_cron
rm /tmp/oracle_cron
echo "Done:"
crontab -l
```

You should see exactly 6 lines (2 config + 4 jobs). The `SHELL` and `PATH` lines at the top are critical — without them, cron can't find `python3` or `git`.

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
