# Oracle Lab — Complete Specification

## An Agentic Research Lab for Geopolitical Forecasting

Inspired by Karpathy's [autoresearch](https://github.com/karpathy/autoresearch): give AI agents a well-scoped research problem with a clear metric, let them iterate on their methodology, score them against reality. Instead of minimizing val_bpb on a language model, we minimize MSE on 4-hour-ahead Polymarket price predictions for live geopolitical markets.

Four competing AI agents, each with a distinct analytical identity encoded in deterministic Python code. The LLM (Claude Code) acts as the researcher that modifies the code between 24-hour iteration cycles. Every forecast is reproducible, every methodology change is a code diff.

**See also: `oracle-lab-droplet-setup.md` for detailed deployment instructions.**

---

## Target Markets

### Market 1: Will the Iranian regime fall by June 30?
~36% yes, $6M+ volume. Drivers: military pressure, internal stability, succession, diplomacy, economic collapse.

### Market 2: Will Iran close the Strait of Hormuz by June 30?
~62% yes, $8M+ volume. Drivers: naval deployments, shipping, military escalation, Iranian capability, oil, deterrence.

---

## Architecture

```
oracle-lab/
├── constants.py            # Markets, horizon (4h), API keys, categories
├── newswire.py             # Perplexity sweep + Haiku normalization
├── state.py                # Key-value state tracker updates
├── prepare.py              # Polymarket prices + briefing assembly
├── evaluate.py             # Scoring, scorecards, leaderboard
├── scripts/
│   ├── run_cycle.sh        # Forecast cycle (cron, every 4h)
│   ├── run_iteration.sh    # Iteration cycle (cron, daily at 02:30)
│   ├── git_push.sh         # Backup to GitHub (cron, every 6h)
│   └── start_monitor.sh    # tmux monitoring dashboard
├── briefings/              # Timestamped briefings (append-only)
├── state/current.json      # Rolling state (versioned in git)
├── price_history/prices.csv
├── fact_history/facts.csv
├── scoreboard/latest.json
├── logs/                   # Cycle logs, iteration logs, cron logs
└── agents/
    ├── momentum/           # forecast.py, program.md, scorecard.json, log/
    ├── historian/
    ├── game_theorist/
    └── quant/
```

---

## The Loop

### Every 4 hours — Forecast Cycle (cron, no LLM):
1. `newswire.py` → 4 Perplexity calls + 1 Haiku normalization → structured facts
2. `state.py` → update key-value state tracker
3. `prepare.py` → pull Polymarket prices, assemble briefing
4. Each agent's `forecast.py` → deterministic Python → predictions to log/
5. `evaluate.py` → score matured predictions, update scorecards + leaderboard
6. Git auto-commit

### Every 24 hours — Iteration Cycle (cron, headless Claude Code):
1. For each agent: `claude -p "[iteration prompt]" --dangerously-skip-permissions`
2. Claude Code reads scorecard + leaderboard + program.md + forecast.py
3. Proposes and implements ONE code change
4. Bumps METHODOLOGY_VERSION, logs reasoning
5. Git auto-commit

---

## Newswire: Two-Stage Pipeline

**Stage 1: Perplexity broad sweep (4 calls)**
- 2 per market: military/security + political/diplomatic/economic
- 24-hour lookback, broad scope, sourced narrative

**Stage 2: Haiku normalization (1 call)**
- Parses raw output into structured JSON facts
- Each fact tagged: claim, source, source_category, indicator_category, market, time, confidence
- Guarantees exact schema the agents' code filters on

**Source categories:** wire_service, us_prestige, uk_prestige, regional_specialist, government_official, think_tank, osint, social_media, market_commentary

**Indicator categories (regime fall):** military_pressure, internal_stability, succession_dynamics, diplomatic_signals, economic_collapse, international_response

**Indicator categories (Hormuz):** naval_deployments, shipping_disruption, military_escalation, iranian_capability, oil_market, deterrence_signals

---

## Rolling State Tracker

Key-value JSON updated each cycle by Haiku. Fields per market: current status, military pressure, internal stability, diplomatic status, economic status, last major event, timestamp. Versioned in git for diffing.

---

## Agents: All Code-First

Every forecast = deterministic Python. No LLM at forecast time. Analytical identity lives in code structure, parameters, and rules. Claude Code (the researcher) modifies the code at iteration time.

### Common interface:
```python
def make_forecasts(briefing_path) -> dict:
    # Returns: agent name, timestamp, predictions dict, 
    # methodology_version, source_weights, parameters snapshot
```

### Agent 1: Momentum
Price dynamics + news flow velocity. Tunable: MOMENTUM_WEIGHT, REVERSION_WEIGHT, NEWS_THRESHOLD, SOURCE_WEIGHTS. Starting logic: if news intensity > threshold, extrapolate momentum; else mean-revert.

### Agent 2: Historian
Historical base rates + mean reversion. Tunable: BASE_RATES (per-market historical priors), REVERSION_RATE, NEWS_SENSITIVITY, escalation/de-escalation category lists. Starting logic: pull toward historical prior, adjust incrementally for net escalation signal.

### Agent 3: Game Theorist
Actor incentives + costly signaling. Tunable: ACTORS (profiles with escalation_bias, credibility), SIGNAL_WEIGHTS (by confidence level), ESCALATION_SENSITIVITY, SOURCE_WEIGHTS (government_official weighted high for strategic inference). Starting logic: score net escalation weighted by signal costliness and source reliability.

### Agent 4: Quant
Statistical models on price + newswire features. Tunable: feature engineering functions, model spec, blend weights, lookback windows. Starting logic: simple momentum + mean reversion blend. Seeds with historical Polymarket data via CLOB API on day one.

---

## Evaluation

### Per-prediction: squared error + directional accuracy

### Scorecard (per agent):
- Rolling MSE overall and per-market
- Naive baseline MSE for comparison
- Directional accuracy overall and per-market
- MSE trend over last 5 cycles
- Source performance: per-source_category directional accuracy
- Virtual P&L on divergence trades

### Leaderboard (visible to all agents, scores only):
Rankings by MSE and directional accuracy. Includes naive baseline. Agents see scores but NOT each other's code or reasoning.

---

## Orchestration: Unattended on DigitalOcean Droplet

### Crontab:
```cron
# Forecast cycle: every 4h at :05
5 */4 * * * /home/oracle/oracle-lab/scripts/run_cycle.sh

# Iteration cycle: daily at 02:30
30 2 * * * /home/oracle/oracle-lab/scripts/run_iteration.sh

# Git push backup: every 6h at :45
45 */6 * * * /home/oracle/oracle-lab/scripts/git_push.sh

# Log rotation: weekly
0 3 * * 0 find /home/oracle/oracle-lab/logs -name "*.log" -mtime +28 -delete
```

### run_cycle.sh (no LLM):
Sources .env and venv. Runs newswire → state → prepare → all 4 agents → evaluate → git commit. Each step has error handling; one agent failing doesn't block others.

### run_iteration.sh (headless Claude Code):
For each agent: runs `claude -p` with a structured prompt, 5-minute timeout. Reads scorecard, leaderboard, program.md, forecast.py. Makes ONE change. Commits all changes.

### Monitoring (tmux, for when you SSH in):
`start_monitor.sh` creates a 4-pane dashboard: leaderboard, latest briefing, cron log tail, methodology changes. Plus an interactive window for ad-hoc Claude Code exploration. Detach with Ctrl-b d; reattach with `tmux attach -t oracle-lab`.

### Boot recovery:
systemd service pulls latest code on boot. Cron survives reboots natively.

### Failure tolerance:
- Droplet reboot: lose at most 1 cycle, resume on next
- Failed newswire: agents forecast with stale/no facts
- Failed agent: other agents unaffected
- Failed iteration: forecast.py stays at previous version
- Extended downtime: gaps in data, resume when back

---

## Models & APIs

| Component | Model | Purpose |
|---|---|---|
| Newswire sweep | Perplexity via OpenRouter | Real-time news |
| Newswire normalize | Claude Haiku | Structured JSON extraction |
| State update | Claude Haiku | Key-value field updates |
| Agent researchers | Claude Code (headless, daily) | Read scores, modify forecast.py |
| Agent forecasts | None (pure Python) | Deterministic predictions |
| Prices | Polymarket CLOB API | Current + historical (2-min res) |

---

## Weekend Build Order

### Saturday morning: Infrastructure
1. `constants.py` — market IDs, token IDs, endpoints, categories
2. `prepare.py` — Polymarket price fetching + historical data seed
3. `newswire.py` — Perplexity + Haiku pipeline
4. `state.py` — key-value tracker

### Saturday afternoon: One agent end-to-end
5. `agents/momentum/forecast.py` + `program.md`
6. Wire up: briefing → forecast → log
7. `evaluate.py` — scoring
8. One full manual cycle

### Saturday evening: All four agents
9. All 4 agent directories with forecast.py and program.md
10. All 4 forecasting on same briefing
11. Leaderboard
12. Push to GitHub, clone to droplet

### Sunday: Deploy and iterate
13. Set up droplet (see droplet-setup.md)
14. Verify cron fires
15. Run first manual iteration
16. Watch agents modify code
17. Detach. Let it run.

---

## The Free Systems Angle

Can an open, deliberative AI system compete with an opaque market? Can it teach us which sources are predictive, which frameworks work, where markets get things wrong? Every forecast, every diff, every weight is public. AI as democratic transparency infrastructure, not private advantage.
