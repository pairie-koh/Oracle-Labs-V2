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

Paste this entire block at once:

```bash
cat > /tmp/setup_cron.sh << 'SCRIPT'
#!/bin/bash
crontab -l 2>/dev/null > /tmp/oracle_cron
echo '5 */4 * * * /root/oracle-lab/scripts/run_cycle.sh >> /root/oracle-lab/logs/cron.log 2>&1' >> /tmp/oracle_cron
echo '30 2 * * * /root/oracle-lab/scripts/run_iteration.sh >> /root/oracle-lab/logs/cron.log 2>&1' >> /tmp/oracle_cron
echo '45 */6 * * * /root/oracle-lab/scripts/git_push.sh' >> /tmp/oracle_cron
echo '0 3 * * 0 find /root/oracle-lab/logs -name "*.log" -mtime +28 -delete' >> /tmp/oracle_cron
crontab /tmp/oracle_cron
rm /tmp/oracle_cron
echo "Done. Current crontab:"
crontab -l
SCRIPT
bash /tmp/setup_cron.sh
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

## Recovery after disconnect

SSH back in, then:

```bash
tmux attach -t oracle 2>/dev/null || tmux new -s oracle
```

If there's a merge conflict or "uncommitted changes" error on git pull:

```bash
cd ~/oracle-lab && git fetch origin && git reset --hard origin/main
```

If cron isn't set up yet, paste the cron setup block from step 9 above.

Check if cron is already running:

```bash
crontab -l
```

If it shows the 4 oracle-lab entries, you're good — the droplet will keep running on its own even if you disconnect.

## Wipe old dashboard data (fresh start from today)

Clears old data from the public dashboard only:

```bash
cd ~/oracle-lab-dashboard
rm -f data/llm_predictions.json data/rolling_scores.csv data/performance_summary.json
git add -A && git commit -m "Clear old dashboard data — fresh start" && git push origin main
```

This only affects the dashboard. All oracle-lab history stays intact.

## Fix: Stuck at `>` prompt

If you pasted something wrong and the terminal shows `>` waiting for input, press `Ctrl+C` to break out. Then retry the command.

## Cron setup (standalone copy-paste block)

If step 9 didn't work or you need to redo it, paste this entire block:

```bash
cat > /tmp/setup_cron.sh << 'SCRIPT'
#!/bin/bash
crontab -l 2>/dev/null > /tmp/oracle_cron
echo '5 */4 * * * /root/oracle-lab/scripts/run_cycle.sh >> /root/oracle-lab/logs/cron.log 2>&1' >> /tmp/oracle_cron
echo '30 2 * * * /root/oracle-lab/scripts/run_iteration.sh >> /root/oracle-lab/logs/cron.log 2>&1' >> /tmp/oracle_cron
echo '45 */6 * * * /root/oracle-lab/scripts/git_push.sh' >> /tmp/oracle_cron
echo '0 3 * * 0 find /root/oracle-lab/logs -name "*.log" -mtime +28 -delete' >> /tmp/oracle_cron
crontab /tmp/oracle_cron
rm /tmp/oracle_cron
echo "Done. Current crontab:"
crontab -l
SCRIPT
bash /tmp/setup_cron.sh
```

You should see output like:

```
Done. Current crontab:
5 */4 * * * /root/oracle-lab/scripts/run_cycle.sh >> /root/oracle-lab/logs/cron.log 2>&1
30 2 * * * /root/oracle-lab/scripts/run_iteration.sh >> /root/oracle-lab/logs/cron.log 2>&1
45 */6 * * * /root/oracle-lab/scripts/git_push.sh
0 3 * * 0 find /root/oracle-lab/logs -name "*.log" -mtime +28 -delete
```

## Debug: Cron not running

Paste this to check what's wrong:

```bash
echo "=== 1. Cron service ==="
systemctl status cron | head -5

echo ""
echo "=== 2. Scripts executable? ==="
ls -la ~/oracle-lab/scripts/run_cycle.sh ~/oracle-lab/scripts/run_iteration.sh ~/oracle-lab/scripts/git_push.sh

echo ""
echo "=== 3. Logs directory ==="
ls ~/oracle-lab/logs/ 2>/dev/null || echo "logs/ directory missing — creating it"
mkdir -p ~/oracle-lab/logs

echo ""
echo "=== 4. .env file exists and has keys? ==="
cat ~/oracle-lab/.env

echo ""
echo "=== 5. Python venv works? ==="
source ~/oracle-lab/venv/bin/activate && python3 --version

echo ""
echo "=== 6. Crontab entries ==="
crontab -l
```

If `.env` is empty or missing, re-create it:

```bash
cat > ~/oracle-lab/.env << 'EOF'
export ANTHROPIC_API_KEY="YOUR_KEY_HERE"
export GITHUB_TOKEN="YOUR_KEY_HERE"
export OPENROUTER_API_KEY="YOUR_KEY_HERE"
export PERPLEXITY_API_KEY="YOUR_KEY_HERE"
EOF
```

If scripts aren't executable:

```bash
chmod +x ~/oracle-lab/scripts/*.sh
```

Test the cycle manually to see errors:

```bash
cd ~/oracle-lab && source venv/bin/activate && source .env && bash scripts/run_cycle.sh 2>&1 | head -30
```

## Fix everything and start (paste this whole block)

This fixes all common issues and kicks off the first cycle. Paste the entire thing at once:

```bash
tmux new -s oracle || tmux attach -t oracle
```

Then paste this inside tmux:

```bash
cd ~/oracle-lab

# Create logs dir
mkdir -p logs reports status

# Make scripts executable
chmod +x scripts/*.sh

# Create .env if it doesn't exist
if [ ! -f .env ]; then
  cat > .env << 'EOF'
export ANTHROPIC_API_KEY="PASTE_YOUR_ANTHROPIC_KEY"
export GITHUB_TOKEN="PASTE_YOUR_GITHUB_TOKEN"
export OPENROUTER_API_KEY="PASTE_YOUR_OPENROUTER_KEY"
export PERPLEXITY_API_KEY="PASTE_YOUR_PERPLEXITY_KEY"
EOF
  echo "Created .env — EDIT IT NOW with your real keys:"
  echo "  nano ~/oracle-lab/.env"
  echo "Then re-run this block."
else
  echo ".env exists:"
  cat .env
fi
```

After confirming .env has your real keys, paste this to set up cron and run the first cycle:

```bash
cd ~/oracle-lab
source venv/bin/activate
source .env

# Set up cron
crontab -l 2>/dev/null > /tmp/oracle_cron
echo '5 */4 * * * /root/oracle-lab/scripts/run_cycle.sh >> /root/oracle-lab/logs/cron.log 2>&1' >> /tmp/oracle_cron
echo '30 2 * * * /root/oracle-lab/scripts/run_iteration.sh >> /root/oracle-lab/logs/cron.log 2>&1' >> /tmp/oracle_cron
echo '45 */6 * * * /root/oracle-lab/scripts/git_push.sh' >> /tmp/oracle_cron
echo '0 3 * * 0 find /root/oracle-lab/logs -name "*.log" -mtime +28 -delete' >> /tmp/oracle_cron
crontab /tmp/oracle_cron
rm /tmp/oracle_cron
echo "Cron set:"
crontab -l

# Run the first cycle now
echo ""
echo "=== Starting first forecast cycle ==="
./scripts/run_cycle.sh
```
