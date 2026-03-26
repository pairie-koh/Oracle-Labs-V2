# Droplet Quickstart (Fresh Setup)

SSH into your droplet, then copy-paste each section in order.

## 1. Install dependencies

```bash
apt update && apt install -y python3-venv python3-pip git tmux jq
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
```

## 2. Clone both repos

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

Verify they loaded:

```bash
echo "ANTHROPIC:    $(echo $ANTHROPIC_API_KEY | head -c 10)..."
echo "GITHUB:       $(echo $GITHUB_TOKEN | head -c 10)..."
echo "OPENROUTER:   $(echo $OPENROUTER_API_KEY | head -c 10)..."
echo "PERPLEXITY:   $(echo $PERPLEXITY_API_KEY | head -c 10)..."
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

## 6. Install Claude Code (for daily agent iteration)

```bash
npm install -g @anthropic-ai/claude-code
claude --version
```

## 7. Make scripts executable

```bash
chmod +x ~/oracle-lab/scripts/*.sh
```

## 8. Test the pipeline (in tmux so it survives disconnects)

```bash
tmux new -s oracle
```

Then inside tmux:

```bash
cd ~/oracle-lab && source venv/bin/activate && source .env && ./scripts/run_cycle.sh
```

If you get disconnected, SSH back in and run `tmux attach -t oracle` to see the output.

Takes ~5-7 minutes to complete. If it finishes without errors, move to step 9.

## 9. Set up cron

Paste this single command (avoids issues with crontab -e):

```bash
(crontab -l 2>/dev/null; echo '5 */4 * * * /root/oracle-lab/scripts/run_cycle.sh >> /root/oracle-lab/logs/cron.log 2>&1'; echo '30 2 * * * /root/oracle-lab/scripts/run_iteration.sh >> /root/oracle-lab/logs/cron.log 2>&1'; echo '45 */6 * * * /root/oracle-lab/scripts/git_push.sh'; echo '0 3 * * 0 find /root/oracle-lab/logs -name "*.log" -mtime +28 -delete') | crontab -
```

## 10. Verify cron is running

```bash
crontab -l
sudo systemctl status cron
```

Done. The droplet will now run forecasts every 4 hours and iterate agents daily.

## Troubleshooting: Check if the pipeline ran

If you're not sure whether a cycle completed (e.g. SSH dropped mid-run):

```bash
# Check latest cycle logs
ls -la ~/oracle-lab/logs/cycle_*.log | tail -3
```

```bash
# See the end of the last log
tail -30 ~/oracle-lab/logs/cycle_*.log | tail -30
```

```bash
# Check for new predictions
ls -la ~/oracle-lab/llm_predictions/ | tail -5
```

```bash
# Check if dashboard got pushed
cd ~/oracle-lab-dashboard && git log --oneline -3
```

```bash
# Re-run the cycle manually if it didn't finish
cd ~/oracle-lab && source venv/bin/activate && source .env && ./scripts/run_cycle.sh
```

Tip: use `tmux` before running long commands so they survive SSH disconnects:

```bash
tmux new -s oracle
cd ~/oracle-lab && source venv/bin/activate && source .env && ./scripts/run_cycle.sh
# Ctrl+B then D to detach. Reconnect later with: tmux attach -t oracle
```

## Recovery after disconnect (steps 1-8 already done)

If you get disconnected after the forecast ran but before cron was set up:

```bash
tmux new -s oracle
```

Then inside tmux, pull the latest code:

```bash
cd ~/oracle-lab && source .env && git pull --rebase origin main
```

Check if forecast data already exists:

```bash
ls ~/oracle-lab/briefings/latest.json ~/oracle-lab/state/current.json ~/oracle-lab/contracts/active_contracts.json
```

If those files exist, just push the dashboard (no need to re-run forecasts):

```bash
cd ~/oracle-lab && source venv/bin/activate && source .env && bash scripts/push_dashboard.sh
```

If push_dashboard.sh gives "no such file or directory", the old paths are still on the droplet. Fix with:

```bash
cd ~/oracle-lab && git config pull.rebase true && git stash && git pull origin main && git stash pop
```

Then retry:

```bash
source .env && bash scripts/push_dashboard.sh
```

If that STILL doesn't work, do it manually:

```bash
mkdir -p ~/oracle-lab-dashboard/data && cp ~/oracle-lab/contracts/active_contracts.json ~/oracle-lab-dashboard/data/active_contracts.json && cp ~/oracle-lab/briefings/latest.json ~/oracle-lab-dashboard/data/briefing.json && cp ~/oracle-lab/state/current.json ~/oracle-lab-dashboard/data/state.json && cd ~/oracle-lab-dashboard && git add data/ && git commit -m "data: manual push" && git push origin main
```

If those files DON'T exist, re-run the full cycle:

```bash
cd ~/oracle-lab && source venv/bin/activate && source .env && ./scripts/run_cycle.sh
```

Then set up cron:

```bash
(crontab -l 2>/dev/null; echo '5 */4 * * * /root/oracle-lab/scripts/run_cycle.sh >> /root/oracle-lab/logs/cron.log 2>&1'; echo '30 2 * * * /root/oracle-lab/scripts/run_iteration.sh >> /root/oracle-lab/logs/cron.log 2>&1'; echo '45 */6 * * * /root/oracle-lab/scripts/git_push.sh'; echo '0 3 * * 0 find /root/oracle-lab/logs -name "*.log" -mtime +28 -delete') | crontab -
```

Verify:

```bash
crontab -l
```

If you get disconnected again, SSH back in and run `tmux attach -t oracle`.

## Wipe old dashboard data (fresh start from today)

Clears old data from the public dashboard only:

```bash
cd ~/oracle-lab-dashboard
rm -f data/llm_predictions.json data/rolling_scores.csv data/performance_summary.json
git add -A && git commit -m "Clear old dashboard data — fresh start" && git push origin main
```

This only affects the dashboard. All oracle-lab history stays intact.
