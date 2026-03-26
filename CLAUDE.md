# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

Oracle Lab is an agentic geopolitical forecasting system built on top of Andy Hall's prediction market trading agent research (documented in his [Free Systems Substack](https://freesystems.substack.com/)). Four AI agents (momentum, historian, game_theorist, quant) make deterministic 4-hour-ahead predictions on Polymarket prices for geopolitical events. A headless Claude Code instance acts as "researcher" for each agent, modifying their forecast code daily based on performance. The system runs unattended on a DigitalOcean droplet.

Key design principle: **forecasts are pure deterministic Python -- no LLM at forecast time.** LLMs are used only for news gathering (Perplexity + Haiku) and daily code iteration (Claude Code).

### Current Status & Known Problems

The system is **not working well** in its current form. After 11 days of operation, the naive baseline ("predict no change") beats all 4 agents. Three root causes:

1. **Agents can't think.** They count news by category and multiply by weights. They can't reason about what the news actually means. The original Kalshi agent worked because it used LLMs to analyze -- Oracle Lab removed that capability at forecast time.
2. **Only 1 market.** 4 agents making 1 prediction each every 4 hours = 24 data points per day, all about the same question. Not enough data for the evolutionary loop to learn anything.
3. **4-hour horizon is noise.** Geopolitical markets don't move in 4 hours. The agents are optimizing on random fluctuations.

---

## Background: The Original Trading Agent

This project extends Andy Hall's earlier prediction market trading agent (built over a holiday break, documented in the Free Systems blog post "Can AI Reason About Politics?"). That system:

- Pulled politically relevant contracts from **Kalshi** via their API
- Used Claude Haiku for contract parsing, GDELT for news, Sonnet/Opus for analysis
- Used a **tiered approach** to manage costs: Haiku for triage, Sonnet for second pass, Opus for top-25 contracts only
- Implemented a **council of models** (inspired by Karpathy's LLM Council): Claude, GPT, Gemini, and Grok debating and updating probability estimates
- Demonstrated some genuine analytical capability at scale but suffered from systematic problems

### Key Lessons From the Original Agent

These findings should guide all improvements:

1. **Better base models beat clever prompting.** Model quality matters more than prompt engineering.
2. **Quality data inputs are necessary but not sufficient.** Good news sources help, but the model still needs to reason well about them.
3. **Calibration is distinct from accuracy.** Models can be knowledgeable yet systematically overconfident. Epistemic calibration is a separate capability that current training doesn't develop well.
4. **Temporal confusion is pervasive.** The agent repeatedly struggled with what's resolved vs. pending, what information is current vs. stale, and where we are in political processes.
5. **Probability coherence is weak.** Models don't reliably update correlated beliefs together (e.g., if P(A) goes up, P(not A) should go down, but models treat each contract independently).
6. **Political nuance is shallow.** Models know facts about political systems but don't always understand how they actually operate -- informal rules, strategic calculations, path dependencies.
7. **Overconfidence is systematic.** Academic research confirms "systematic overconfidence across all models" and that "extended reasoning worsens rather than improves calibration."
8. **The council approach works.** Having multiple models debate and update estimates catches errors. In one case, Sonnet corrected a badly wrong analysis after hearing counter-arguments from GPT and Grok.
9. **The real constraint is inference cost, not engineering time.** Allocating compute efficiently across thousands of contracts is itself a research design problem.

---

## Planned Improvements (20 total)

Keep Oracle Lab's infrastructure (automated pipeline, cron, scoring, git tracking) but fix the three root causes and add smarter reasoning, better data, mechanical guards, and feedback loops. See `plan.md` for detailed implementation steps per improvement.

### A. Core Fixes
1. **Expand to ~30 Polymarket contracts** across diverse domains (politics, economics, entertainment, etc.)
2. **Bring LLM reasoning back at forecast time** -- tiered pipeline: Haiku triages all contracts, Sonnet deep-dives the most divergent ones. This is the most important change.
3. **Fix prediction horizon** -- 24h (primary) and 7d (secondary) instead of 4h

### B. Better Data In
4. **Use GDELT** (the same data source Andy's original Kalshi agent used) for raw, structured news data instead of just Perplexity summaries
5. **Resolution rule parsing** -- explicitly extract and feed resolution criteria to the LLM so it understands exactly what triggers contract resolution
6. **Web search integration** -- targeted search queries per contract to provide missing context

### C. Smarter Reasoning
7. **Council of models** -- Claude, GPT, and Gemini debate and update probability estimates on top candidates (Andy proved this works)
8. **Decomposition** -- break each contract into sub-questions and estimate components separately (how superforecasters work)
9. **Adversarial second pass** -- force the model to argue against its own position before committing
10. **Category-specific reasoning** -- different prompt templates for politics vs economics vs entertainment vs sports
11. **Temporal context injection** -- explicit date, deadline, and process-stage context to prevent temporal confusion

### D. Mechanical Guards
12. **Overconfidence shrinkage** -- mechanically shrink estimates halfway toward market price
13. **Freshness-weighted detection** -- reduce confidence when evidence is stale
14. **Cross-market coherence checks** -- catch logically incoherent prices across related contracts

### E. Learning & Feedback
15. **Systematic prediction tracking** -- log every prediction with full context and reasoning
16. **Per-domain performance tracking** -- learn what the system is good/bad at by domain, horizon, and divergence size
17. **Bayesian updating** -- maintain running belief state per contract instead of starting fresh each cycle
18. **Feed lessons back into prompts** -- inject past mistakes into future analysis to avoid repeating errors

### F. Extra Agent
19. **Smart money detector** -- non-LLM quantitative agent that watches Polymarket trading patterns (volume spikes, sudden moves) to detect informed trading before news breaks

### G. Contract Intelligence
20. **Structured contract metadata** -- use Haiku to tag each contract with domain, time horizon, resolution type, geographic scope, and key actors. This metadata powers category-specific reasoning (#10), per-domain performance tracking (#16), freshness detection (#13), and cross-market coherence (#14)

### Cost Estimate
- **Haiku triage** (~30 contracts): ~$0.05/cycle
- **Sonnet deep dives** (~10-15 contracts): ~$0.50-0.75/cycle
- **Council of models** (top ~5 contracts): ~$1.50-2.00/cycle
- **At 6 cycles/day:** ~$12-17/day, **~$360-500/month**

---

## Architecture

Two loops drive the system currently:

**Forecast cycle (every 4 hours, no LLM):**
`newswire.py` -> `state.py` -> `prepare.py` -> each agent's `forecast.py` -> `evaluate.py` -> git commit

**Iteration cycle (daily at 02:30, headless Claude Code):**
For each agent: Claude reads scorecard + leaderboard + `program.md` + `forecast.py`, makes ONE code change, bumps `METHODOLOGY_VERSION`, commits.

**Planned architecture:** The forecast cycle will use LLMs (Haiku triage + Sonnet deep analysis) instead of deterministic Python agents. See Planned Improvements above.

## Project Layout

```
oracle-lab/
├── constants.py            # Market IDs, token IDs, API endpoints, categories
├── newswire.py             # Perplexity sweep (4 calls) + Haiku normalization (1 call)
├── state.py                # Key-value state tracker (Haiku updates)
├── prepare.py              # Polymarket CLOB API prices + briefing assembly
├── evaluate.py             # Scoring engine, scorecards, leaderboard
├── report.py               # Report generation
├── init_project.py         # Project initialization
├── scripts/
│   ├── run_cycle.sh        # Forecast cycle (cron)
│   ├── run_iteration.sh    # Iteration cycle (cron)
│   ├── git_push.sh         # GitHub backup (cron)
│   └── start_monitor.sh    # tmux 4-pane dashboard
├── agents/{momentum,historian,game_theorist,quant}/
│   ├── forecast.py         # Deterministic prediction code
│   ├── program.md          # Agent's research instructions
│   ├── scorecard.json      # Performance stats
│   └── log/                # Methodology change history
├── briefings/              # Timestamped JSON briefings (append-only)
├── state/current.json      # Rolling state tracker
├── price_history/prices.csv
├── fact_history/facts.csv
├── scoreboard/latest.json  # Cross-agent leaderboard
├── scores_history.csv      # Historical scores
├── reports/                # Generated reports
├── logs/                   # Cycle logs, iteration logs, cron logs
├── status/                 # System status files
└── .env                    # API keys (not committed)
```

## Commands

```bash
# Environment setup
python3 -m venv venv
source venv/bin/activate
pip3 install requests numpy pandas scikit-learn

# Run a full forecast cycle manually
source .env && source venv/bin/activate
python3 newswire.py && python3 state.py && python3 prepare.py
python3 agents/momentum/forecast.py briefings/latest.json
python3 evaluate.py

# Run the full cycle via script
./scripts/run_cycle.sh

# Run a single agent's forecast
python3 agents/momentum/forecast.py briefings/latest.json

# Run the daily iteration cycle
./scripts/run_iteration.sh

# Monitor (tmux dashboard)
./scripts/start_monitor.sh
tmux attach -t oracle-lab
```

## Agent Interface

All agents implement the same interface:

```python
def make_forecasts(briefing_path) -> dict:
    # Returns: agent name, timestamp, predictions dict,
    # methodology_version, source_weights, parameters snapshot
```

Each agent has tunable parameters at the top of `forecast.py`. The iteration cycle modifies these. Agent identities:

- **momentum** -- price dynamics + news flow velocity
- **historian** -- historical base rates + mean reversion
- **game_theorist** -- actor incentives + costly signaling
- **quant** -- statistical models on price + newswire features

## Newswire Pipeline

Two-stage: (1) Perplexity via OpenRouter does 4 broad news sweeps (2 per market), then (2) Haiku normalizes into structured JSON facts with fields: `claim`, `source`, `source_category`, `indicator_category`, `market`, `time`, `confidence`.

Source categories: `wire_service`, `us_prestige`, `uk_prestige`, `regional_specialist`, `government_official`, `think_tank`, `osint`, `social_media`, `market_commentary`

## Evaluation

Metrics: squared error, directional accuracy, MSE trend, naive baseline comparison, source-level directional accuracy, virtual P&L on divergence trades. Scorecards live at `agents/{name}/scorecard.json`. Leaderboard at `scoreboard/latest.json`.

## API Dependencies

| Component | Service | Key env var |
|---|---|---|
| News sweep | Perplexity (direct) | `PERPLEXITY_API_KEY` |
| Fact normalization + state | Claude Haiku via OpenRouter | `OPENROUTER_API_KEY` |
| LLM forecasting (triage/deep dive) | Claude Haiku/Sonnet/Opus via OpenRouter | `OPENROUTER_API_KEY` |
| Price data | Polymarket CLOB API | (no key needed) |
| Iteration researcher | Claude Sonnet via OpenRouter | `OPENROUTER_API_KEY` |

## Deployment

Runs on a DigitalOcean droplet as user `oracle`. Cron handles scheduling. See `oracle-lab-droplet-setup.md` for full setup. Key cron jobs:
- Forecast cycle: `5 */4 * * *`
- Iteration cycle: `30 2 * * *`
- Git push: `45 */6 * * *`

Failure tolerance: one component failing doesn't block others. Agents forecast with stale facts if newswire fails. A failed iteration leaves `forecast.py` at its previous version.

---

## Workflow Requirements

These rules are non-negotiable.

1. **Never claim something works without running a test to prove it.** After writing any code, immediately run it. "It should work" is not acceptable -- show that it works.

2. **Work modularly.** Complete one module or task at a time. After each module, report what you built, show test results, and wait for confirmation before proceeding. Do not build an entire pipeline and then test it at the end.

3. **Iterate and fix errors yourself.** Run the code, observe the output, and fix problems before presenting results. If you can't fix it after genuine effort, then ask for help.

4. **Be explicit about unknowns.** If you're uncertain about something, say so. Don't guess. Don't confabulate. "I don't know" is an acceptable answer.

## Before Starting Any Task

- **Confirm you understand the goal.** Restate what you think is being asked. If there's ambiguity, ask before proceeding.
- **Check for existing work.** Look at what already exists before creating new files. Don't duplicate work.
- **Identify dependencies.** What data, files, or prior steps does this task depend on? Verify they exist.
- **Plan before coding.** For any non-trivial task, outline your approach before writing code.

## Code Standards

- **Comment the why, not the what.** Comments should explain reasoning and intent, not describe what the code obviously does.
- **One task per script.** Each script should do one coherent thing.
- **Paths should be relative.** Use relative paths from the project root, not absolute paths that only work on one machine. (Exception: cron scripts use absolute paths for `/home/oracle/oracle-lab/`.)
- **Handle errors gracefully.** Anticipate what could go wrong and handle it explicitly. Don't let scripts fail silently.
- **Print progress for long operations.** If something takes more than a few seconds, print status updates.

## Data and Results

- **Preserve raw data.** Never modify original data files. All transformations happen in code.
- **Verify completeness.** After collecting data, check counts, date ranges, and coverage. Don't assume -- verify.
- **Check for anomalies.** After loading or transforming data, run sanity checks: observation counts, missing values, unexpected values.
- **Start simple.** Run the simplest version first. Add complexity only after the simple version works.
- **Sanity check results.** Do the results make sense? Right order of magnitude? Plausible signs? Expected sample size?

## Reporting and Communication

- **Lead with the bottom line.** Start with what matters most. Details follow.
- **Show, don't just tell.** When you say something worked, show the output.
- **Flag decisions you made.** If you had to make a choice that could reasonably have gone another way, say what you chose and why.
- **Summarize at milestones.** At natural stopping points: what's done, what's working, what needs attention, what's next.

## When Things Go Wrong

- **Don't hide errors.** If something isn't working, say so immediately.
- **Debug systematically.** Isolate the problem. What's the minimal case that reproduces it?
- **After fixing a bug, re-run everything downstream.** A bug fix isn't complete until everything that depended on the buggy code has been verified.

## Checklist Before Saying "Done"

- [ ] Code runs without errors
- [ ] Output is saved to the correct location
- [ ] Results have been sanity checked
- [ ] Any judgment calls or uncertainties are documented
- [ ] Data completeness has been verified (if data collection was involved)
- [ ] Downstream dependencies have been considered
