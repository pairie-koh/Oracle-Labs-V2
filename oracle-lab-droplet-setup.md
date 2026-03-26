# Oracle Lab: Droplet Setup Guide

## Step-by-step instructions to get Oracle Lab running unattended on your DigitalOcean droplet.

---

## Step 0: Find Your Droplet Details

Log into DigitalOcean (cloud.digitalocean.com). Click "Droplets" in the left sidebar. Find your droplet. You need:

- **IP address**: shown on the droplet row (something like `164.90.xxx.xxx`)
- **OS**: probably Ubuntu (check the droplet details page)

If you've forgotten your root password, click the droplet name → "Access" → "Reset Root Password." DigitalOcean will email you a new one.

---

## Step 1: SSH Into Your Droplet

From your Mac terminal:

```bash
ssh root@YOUR_DROPLET_IP
```

If it asks about host authenticity, type `yes`. Enter your password.

If you've set up SSH keys before, it will just connect. If not and you want to avoid typing passwords:

```bash
# On your Mac (not the droplet), generate a key if you don't have one:
ssh-keygen -t ed25519 -C "andy@oracle-lab"
# Press enter for default location, optional passphrase

# Copy your public key to the droplet:
ssh-copy-id root@YOUR_DROPLET_IP

# Now future connections won't need a password
```

---

## Step 2: Create a Dedicated User

Don't run everything as root. Create an `oracle` user:

```bash
# On the droplet (as root):
adduser oracle
# Set a password, press enter through the name/phone/etc prompts

# Give oracle sudo access
usermod -aG sudo oracle

# Allow oracle to use SSH
mkdir -p /home/oracle/.ssh
cp ~/.ssh/authorized_keys /home/oracle/.ssh/ 2>/dev/null
chown -R oracle:oracle /home/oracle/.ssh
chmod 700 /home/oracle/.ssh

# Switch to the oracle user for all remaining steps
su - oracle
```

From now on, SSH in as `oracle`:
```bash
ssh oracle@YOUR_DROPLET_IP
```

---

## Step 3: Install System Dependencies

```bash
# Update packages
sudo apt update && sudo apt upgrade -y

# Python 3.10+ (Ubuntu 22.04+ should have this already)
python3 --version
# If it says 3.10 or higher, you're good. If not:
sudo apt install python3.10 python3.10-venv python3-pip -y

# Git
sudo apt install git -y

# tmux
sudo apt install tmux -y

# jq (for working with JSON in bash)
sudo apt install jq -y

# Node.js (needed for Claude Code)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install nodejs -y

# Verify
node --version   # should be v20.x
npm --version    # should be 10.x
python3 --version # should be 3.10+
git --version
tmux -V
```

---

## Step 4: Install Claude Code

```bash
# Install Claude Code globally
sudo npm install -g @anthropic-ai/claude-code

# Verify
claude --version

# Authenticate (this will open a browser link you paste into your local browser)
claude auth login
# Follow the instructions — it will show a URL and a code.
# Open the URL on your Mac, paste the code, authorize.
```

If `claude auth login` doesn't work well over SSH (it needs a browser), you can authenticate on your Mac and copy the credentials:

```bash
# On your Mac, find your Claude credentials:
cat ~/.claude/credentials.json

# On the droplet, create the same file:
mkdir -p ~/.claude
nano ~/.claude/credentials.json
# Paste the contents, save (Ctrl+X, Y, Enter)
```

---

## Step 5: Set Up API Keys

Create an environment file that all scripts will source:

```bash
mkdir -p ~/oracle-lab
nano ~/oracle-lab/.env
```

Paste the following (fill in your actual keys):

```bash
# Oracle Lab API Keys
export OPENROUTER_API_KEY="sk-or-..."
export PERPLEXITY_API_KEY="pplx-..."

# Optional: if you want to push to GitHub automatically
export GITHUB_TOKEN="ghp_..."
```

Make it source automatically:

```bash
echo 'source ~/oracle-lab/.env' >> ~/.bashrc
source ~/.bashrc
```

**Where to get keys if you don't have them:**
- Anthropic API key: console.anthropic.com → API Keys
- OpenRouter API key: openrouter.ai → Keys (this is for Perplexity calls)
- Brave Search API key: api.search.brave.com → API Keys

---

## Step 6: Clone the Repo

Once you've built oracle-lab on your Mac with Claude Code (Saturday morning), push it to GitHub, then pull it down:

```bash
cd ~
git clone https://github.com/YOUR_USERNAME/oracle-lab.git
cd oracle-lab

# Install Python dependencies
python3 -m venv venv
source venv/bin/activate
pip install requests numpy pandas

# If the quant agent needs sklearn later:
pip install scikit-learn
```

If you haven't pushed to GitHub yet and want to just copy files:

```bash
# From your Mac:
scp -r /path/to/oracle-lab oracle@YOUR_DROPLET_IP:~/oracle-lab
```

---

## Step 7: Test the Pipeline Manually

Before setting up automation, run one full cycle by hand to make sure everything works:

```bash
cd ~/oracle-lab
source venv/bin/activate
source .env

# Test each step individually:
python3 newswire.py
echo "newswire: $?"         # should print 0

python3 state.py
echo "state: $?"

python3 prepare.py
echo "prepare: $?"

# Test one agent:
python3 agents/momentum/forecast.py briefings/latest.json
echo "momentum forecast: $?"

# Test evaluation:
python3 evaluate.py
echo "evaluate: $?"

# If all print 0, you're good.
```

---

## Step 8: Set Up the Automation Scripts

Create the scripts directory and the cycle runner:

```bash
mkdir -p ~/oracle-lab/scripts
mkdir -p ~/oracle-lab/logs
```

### scripts/run_cycle.sh
```bash
nano ~/oracle-lab/scripts/run_cycle.sh
```

Paste:
```bash
#!/bin/bash
# Oracle Lab — Forecast Cycle (runs every 4 hours)
# No LLM needed — just Python scripts and API calls.

source /home/oracle/oracle-lab/.env
source /home/oracle/oracle-lab/venv/bin/activate
cd /home/oracle/oracle-lab

TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
LOGFILE="logs/cycle_$(date +%Y%m%dT%H%M).log"

echo "=== Forecast cycle start: $TIMESTAMP ===" | tee -a "$LOGFILE"

# Stage 1: Gather data
echo "[1/5] Running newswire..." | tee -a "$LOGFILE"
python3 newswire.py >> "$LOGFILE" 2>&1
if [ $? -ne 0 ]; then
    echo "WARN: newswire failed, continuing with empty/stale facts" | tee -a "$LOGFILE"
fi

echo "[2/5] Updating state..." | tee -a "$LOGFILE"
python3 state.py >> "$LOGFILE" 2>&1 || echo "WARN: state update failed" >> "$LOGFILE"

echo "[3/5] Preparing briefing..." | tee -a "$LOGFILE"
python3 prepare.py >> "$LOGFILE" 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: prepare failed, aborting cycle" | tee -a "$LOGFILE"
    exit 1
fi

# Stage 2: All agents forecast (independent — one failure doesn't block others)
echo "[4/5] Running agent forecasts..." | tee -a "$LOGFILE"
for agent in momentum historian game_theorist quant; do
    python3 "agents/$agent/forecast.py" briefings/latest.json >> "$LOGFILE" 2>&1
    if [ $? -eq 0 ]; then
        echo "  $agent: OK" | tee -a "$LOGFILE"
    else
        echo "  $agent: FAILED" | tee -a "$LOGFILE"
    fi
done

# Stage 3: Score matured predictions
echo "[5/5] Evaluating..." | tee -a "$LOGFILE"
python3 evaluate.py >> "$LOGFILE" 2>&1 || echo "WARN: evaluation failed" >> "$LOGFILE"

# Stage 4: Commit results
git add -A >> "$LOGFILE" 2>&1
git commit -m "cycle: $TIMESTAMP" --allow-empty >> "$LOGFILE" 2>&1

echo "=== Forecast cycle complete: $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LOGFILE"
```

Make it executable:
```bash
chmod +x ~/oracle-lab/scripts/run_cycle.sh
```

### scripts/run_iteration.sh
```bash
nano ~/oracle-lab/scripts/run_iteration.sh
```

Paste:
```bash
#!/bin/bash
# Oracle Lab — Iteration Cycle (runs daily at 02:00)
# Uses headless Claude Code to modify each agent's forecast.py.

source /home/oracle/oracle-lab/.env
cd /home/oracle/oracle-lab

DATE=$(date +%Y-%m-%d)
LOGFILE="logs/iteration_${DATE}.log"

echo "=== Iteration cycle start: $(date) ===" | tee -a "$LOGFILE"

for agent in momentum historian game_theorist quant; do
    echo "--- Iterating: $agent ---" | tee -a "$LOGFILE"
    
    AGENT_LOG="logs/iteration_${agent}_${DATE}.log"
    
    PROMPT="You are the researcher for the $agent forecasting agent in Oracle Lab.

Read these files in order:
1. agents/$agent/scorecard.json — your detailed performance stats
2. scoreboard/latest.json — the leaderboard (other agents' scores, not their code)
3. agents/$agent/program.md — your research instructions
4. agents/$agent/forecast.py — your current forecasting code

Following the instructions in program.md:
- Review your performance honestly. Are you beating the naive baseline?
- Identify ONE specific change to make to forecast.py
- Implement the change
- Bump METHODOLOGY_VERSION to the next version number
- Write a brief explanation (3-5 sentences) of what you changed and why to:
  agents/$agent/log/methodology_changes/${DATE}.md

If your last change made things worse (current MSE > previous MSE), revert it first, then try something different.

IMPORTANT: Make only ONE change. Do not rewrite the entire file."

    timeout 300 claude -p "$PROMPT" \
        --dangerously-skip-permissions \
        -C /home/oracle/oracle-lab \
        >> "$AGENT_LOG" 2>&1
    
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 0 ]; then
        echo "  $agent: OK" | tee -a "$LOGFILE"
    elif [ $EXIT_CODE -eq 124 ]; then
        echo "  $agent: TIMEOUT (5 min limit)" | tee -a "$LOGFILE"
    else
        echo "  $agent: FAILED (exit $EXIT_CODE)" | tee -a "$LOGFILE"
    fi
done

# Commit all changes
git add -A
git commit -m "iteration: $DATE"

echo "=== Iteration cycle complete: $(date) ===" | tee -a "$LOGFILE"
```

Make it executable:
```bash
chmod +x ~/oracle-lab/scripts/run_iteration.sh
```

### scripts/git_push.sh
```bash
nano ~/oracle-lab/scripts/git_push.sh
```

Paste:
```bash
#!/bin/bash
# Push to GitHub as backup
cd /home/oracle/oracle-lab
git push origin main >> logs/git_push.log 2>&1
```

Make it executable:
```bash
chmod +x ~/oracle-lab/scripts/git_push.sh
```

---

## Step 9: Set Up Git for Auto-Commits

```bash
cd ~/oracle-lab

# Configure git identity
git config user.name "Oracle Lab Bot"
git config user.email "oracle-lab@yourdomain.com"

# If pushing to GitHub, set up authentication.
# Option A: HTTPS with token (simpler)
git remote set-url origin https://${GITHUB_TOKEN}@github.com/YOUR_USERNAME/oracle-lab.git

# Option B: SSH key (more secure)
ssh-keygen -t ed25519 -C "oracle-lab-droplet" -f ~/.ssh/oracle_lab_key -N ""
cat ~/.ssh/oracle_lab_key.pub
# Copy this output → GitHub.com → Settings → SSH Keys → Add
git remote set-url origin git@github.com:YOUR_USERNAME/oracle-lab.git
```

---

## Step 10: Set Up Cron

```bash
crontab -e
# If it asks which editor, choose nano (option 1)
```

Paste these lines at the bottom:

```cron
# ============================================
# Oracle Lab Automation
# ============================================

# Forecast cycle: every 4 hours at :05 (give the APIs a minute past the hour)
5 */4 * * * /home/oracle/oracle-lab/scripts/run_cycle.sh >> /home/oracle/oracle-lab/logs/cron.log 2>&1

# Iteration cycle: daily at 02:30 (after the 00:05 forecast cycle has been scored)
30 2 * * * /home/oracle/oracle-lab/scripts/run_iteration.sh >> /home/oracle/oracle-lab/logs/cron.log 2>&1

# Git push: every 6 hours at :45
45 */6 * * * /home/oracle/oracle-lab/scripts/git_push.sh

# Log rotation: weekly, keep last 4 weeks of logs
0 3 * * 0 find /home/oracle/oracle-lab/logs -name "*.log" -mtime +28 -delete
```

Save and exit (Ctrl+X, Y, Enter).

Verify cron is installed:
```bash
crontab -l
# Should show your entries

# Make sure cron service is running
sudo systemctl status cron
# If it says "inactive", start it:
sudo systemctl enable cron
sudo systemctl start cron
```

---

## Step 11: Set Up the Monitoring tmux Session

This is for when you SSH in to watch. It doesn't need to be running for automation to work.

```bash
nano ~/oracle-lab/scripts/start_monitor.sh
```

Paste:
```bash
#!/bin/bash
SESSION="oracle-lab"
PROJECT="/home/oracle/oracle-lab"

# Kill existing session
tmux kill-session -t $SESSION 2>/dev/null

# Window 0: Dashboard (4 panes)
tmux new-session -d -s $SESSION -n "dashboard" -c "$PROJECT"

# Top-left: leaderboard (auto-refreshes every 60s)
tmux send-keys -t $SESSION "watch -n 60 'echo \"=== ORACLE LAB LEADERBOARD ===\"; echo; cat scoreboard/latest.json 2>/dev/null | python3 -m json.tool 2>/dev/null || echo \"No scores yet\"; echo; echo \"=== LAST CYCLE ===\"; tail -5 logs/cron.log 2>/dev/null'" Enter

# Top-right: latest briefing facts count
tmux split-window -h -t $SESSION -c "$PROJECT"
tmux send-keys -t $SESSION "watch -n 60 'echo \"=== LATEST BRIEFING ===\"; ls -la briefings/ 2>/dev/null | tail -5; echo; LATEST=\$(ls briefings/*.json 2>/dev/null | tail -1); if [ -n \"\$LATEST\" ]; then echo \"Facts:\"; cat \$LATEST | python3 -c \"import sys,json; b=json.load(sys.stdin); print(f\\\"  Fresh facts: {len(b.get(\\\\\\\"fresh_facts\\\\\\\",[]))}\\\"); print(f\\\"  Prices: {b.get(\\\\\\\"market_prices\\\\\\\",{})}\\\")\" 2>/dev/null; fi'" Enter

# Bottom-left: cron log tail
tmux split-window -v -t $SESSION:0.0 -c "$PROJECT"
tmux send-keys -t $SESSION "tail -f logs/cron.log 2>/dev/null || echo 'No cron log yet. Waiting...'" Enter

# Bottom-right: latest methodology changes
tmux split-window -v -t $SESSION:0.1 -c "$PROJECT"
tmux send-keys -t $SESSION "watch -n 300 'echo \"=== LATEST METHODOLOGY CHANGES ===\"; for a in momentum historian game_theorist quant; do echo; echo \"--- \$a ---\"; ls agents/\$a/log/methodology_changes/*.md 2>/dev/null | tail -1 | xargs cat 2>/dev/null || echo \"  (no changes yet)\"; done'" Enter

# Window 1: Interactive (for when you want to poke around)
tmux new-window -t $SESSION -n "explore" -c "$PROJECT"
tmux send-keys -t $SESSION "source venv/bin/activate && source .env && echo 'Ready. Try: claude -C agents/historian'" Enter

# Go back to dashboard
tmux select-window -t $SESSION:0
tmux select-pane -t $SESSION:0.0

echo "Oracle Lab monitor started. Attach with: tmux attach -t oracle-lab"
```

Make it executable:
```bash
chmod +x ~/oracle-lab/scripts/start_monitor.sh
```

To use:
```bash
# Start the monitor
~/oracle-lab/scripts/start_monitor.sh

# Or if it's already running:
tmux attach -t oracle-lab

# Navigate:
# Ctrl-b arrow keys = move between panes
# Ctrl-b n = next window (dashboard → explore)
# Ctrl-b d = detach (everything keeps running)
```

---

## Step 12: Boot Recovery

Make sure everything survives a droplet reboot:

```bash
sudo nano /etc/systemd/system/oracle-lab-boot.service
```

Paste:
```ini
[Unit]
Description=Oracle Lab boot recovery
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=oracle
ExecStart=/bin/bash -c 'cd /home/oracle/oracle-lab && git pull origin main 2>/dev/null; echo "Oracle Lab ready at $(date)" >> /home/oracle/oracle-lab/logs/boot.log'

[Install]
WantedBy=multi-user.target
```

Enable it:
```bash
sudo systemctl enable oracle-lab-boot
```

Cron itself survives reboots automatically on Ubuntu. The systemd service just pulls the latest code on boot in case you pushed changes from your Mac.

---

## Step 13: Verify Everything Works

### Test the forecast cycle manually:
```bash
cd ~/oracle-lab
source venv/bin/activate && source .env
./scripts/run_cycle.sh
# Watch the output. Should complete in ~2 minutes.
cat logs/cycle_*.log | tail -20
```

### Test the iteration cycle manually:
```bash
./scripts/run_iteration.sh
# This takes longer (up to 5 min per agent = 20 min total)
# Watch with: tail -f logs/iteration_*.log
```

### Verify cron will fire:
```bash
# Check next scheduled run times
sudo apt install -y at 2>/dev/null  # for atq if needed
crontab -l

# Wait for the next :05 past a 4-hour mark (00:05, 04:05, 08:05, etc.)
# Check the cron log after:
tail -f ~/oracle-lab/logs/cron.log
```

### Test a reboot:
```bash
sudo reboot
# Wait 1-2 minutes, SSH back in
ssh oracle@YOUR_DROPLET_IP
crontab -l  # should still show your jobs
```

---

## Daily Operations

### Checking in (takes 30 seconds):
```bash
ssh oracle@YOUR_DROPLET_IP
tmux attach -t oracle-lab 2>/dev/null || ~/oracle-lab/scripts/start_monitor.sh
# Glance at leaderboard, check cron log for errors
# Ctrl-b d to detach
```

### Manually triggering a cycle:
```bash
ssh oracle@YOUR_DROPLET_IP
cd ~/oracle-lab && source venv/bin/activate && source .env
./scripts/run_cycle.sh
```

### Manually triggering an iteration:
```bash
./scripts/run_iteration.sh
```

### Interactively exploring an agent:
```bash
cd ~/oracle-lab/agents/historian
claude
# "Show me your last 3 methodology changes and whether they helped"
```

### Pulling changes you made on your Mac:
```bash
cd ~/oracle-lab && git pull origin main
```

### Pushing droplet changes to your Mac:
```bash
cd ~/oracle-lab && git push origin main
```

---

## Dealing With Droplet Unreliability

Your droplet has been flaky before. Here's how this setup handles it:

**If the droplet reboots:** Cron restarts automatically. The boot service pulls latest code. The next scheduled cycle runs as normal. You lose at most one cycle's predictions (4 hours of data). The monitor tmux session will be gone—restart it with `start_monitor.sh` when you SSH back in.

**If a cycle fails mid-run:** Each script has error handling. A failed newswire doesn't stop the agents from forecasting (they just have stale/no fresh facts). A failed agent doesn't stop other agents. The next cycle runs clean.

**If the iteration fails:** Claude Code has a 5-minute timeout per agent. If it hangs, it times out and the next agent runs. The forecast code stays at whatever version it was before—no corruption.

**If the droplet is completely down for hours:** You lose cycles, which means gaps in your prediction data. When it comes back, everything resumes. The 24h lookback on the newswire means you'll catch up on news you missed.

**Nuclear option — if you want to move off the droplet later:** Everything is in git. Clone the repo to a new server, set up the same cron jobs, and you're running in 15 minutes.

---

## Troubleshooting

### "Permission denied" on scripts
```bash
chmod +x ~/oracle-lab/scripts/*.sh
```

### Claude Code not found in cron
Cron has a minimal PATH. Add this to the top of your crontab:
```cron
PATH=/usr/local/bin:/usr/bin:/bin:/home/oracle/.npm-global/bin
```
Or find Claude's path with `which claude` and use the full path in `run_iteration.sh`.

### API key not available in cron
Cron doesn't source `.bashrc`. The scripts explicitly source `.env` at the top. If keys are missing, check that `.env` has the right values:
```bash
source ~/oracle-lab/.env
echo $OPENROUTER_API_KEY  # should print your key
```

### Python packages not found in cron
The scripts activate the venv. If you get import errors, make sure packages are installed in the venv:
```bash
source ~/oracle-lab/venv/bin/activate
pip install requests numpy pandas scikit-learn
```

### Git push failing
```bash
cd ~/oracle-lab
git remote -v  # check the remote URL is correct
git push origin main  # try manually, see the error message
```

### Checking if cron ran
```bash
# System cron log:
grep CRON /var/log/syslog | tail -20

# Oracle Lab cron log:
tail -50 ~/oracle-lab/logs/cron.log
```
