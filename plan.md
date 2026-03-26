# Plan: Fixing Oracle Lab

## What's wrong

Oracle Lab stripped out LLM reasoning at forecast time and replaced it with simple Python formulas. The hope was that these formulas would evolve via daily Claude Code iteration. After 11 days, the naive baseline ("predict no change") beats all 4 agents. Three root causes:

1. **Agents can't think.** They count news by category and multiply by weights. They can't reason about what news actually means. The original Kalshi agent worked because it used LLMs to analyze -- Oracle Lab removed that.
2. **Only 1 market.** 4 agents making 1 prediction each every 4 hours = 24 data points per day, all about the same question. Not enough data for the evolutionary loop to learn anything.
3. **4-hour horizon is noise.** Geopolitical markets don't move in 4 hours.

## All improvements (20 total)

Keep Oracle Lab's infrastructure (automated pipeline, cron, scoring, git tracking) but fix what's broken. Organized into 6 categories.

---

### A. Core Fixes (address the 3 root causes)

#### 1. Expand to ~30 Polymarket contracts

**Problem:** 1 market = not enough data to learn from.

**What to do:**
- Replace the hardcoded `MARKETS` dict in `constants.py` with a dynamic contract puller
- Write a script that pulls active contracts from Polymarket's Gamma API (they have hundreds)
- Use Haiku to tag each contract: domain (politics, economics, entertainment, etc.), time horizon (days/weeks/months), resolution type (official announcement, data release, etc.)
- Store contract metadata in a `contracts/` directory
- Filter to ~30 high-volume contracts across diverse domains
- Start with 30 -- enough diversity to learn patterns, not so many that costs spiral. Scale up later once we see what works.

**Files:** `constants.py`, new `contracts.py` script, `prepare.py` (fetch prices for all contracts)

#### 2. Bring LLM reasoning back at forecast time

**Problem:** Deterministic Python formulas can't reason about news content. This is the most important change.

**What to do:**
- Replace the 4 deterministic agents with an LLM-based analysis pipeline
- **Tier 1 (Haiku, all ~30 contracts):** Quick probability estimate for each contract. Compare to market price. Flag contracts where estimate diverges > X% from market.
- **Tier 2 (Sonnet, top ~10-15 divergent contracts):** Deep analysis with structured reasoning. The model reads the contract, resolution rules, relevant news, and produces a probability estimate with explicit reasoning.
- Keep the structured output format (prediction, confidence, reasoning, key evidence)
- The divergence threshold determines how many get deep dives: 10% threshold = fewer but higher-signal, 5% = more but costs more.

**Files:** Replace `agents/*/forecast.py` with new `analyze.py` pipeline, update `newswire.py` to gather news per contract domain

#### 3. Fix prediction horizon

**Problem:** 4h predictions are noise. Geopolitical markets don't move meaningfully in 4 hours.

**What to do:**
- Change to 24h (primary) and 7d (secondary) horizons
- `evaluate.py`: score predictions at 24h and 7d instead of 4h
- Keep the 4-hour data collection cycle (frequent price observations are still useful for price history)
- Scale price lookup tolerance with horizon: 2h for 24h, 8h for 7d

**Files:** `constants.py`, `evaluate.py`, `prepare.py`

---

### B. Better Data In

#### 4. Use GDELT instead of (or alongside) Perplexity

**Problem:** The current system asks Perplexity broad questions and gets back LLM-summarized news. That's a filtered, summarized version of reality -- not the raw source data.

**What to do:**
- Integrate GDELT (Global Database of Events, Language, and Tone) -- the same data source Andy's original Kalshi agent used
- GDELT continuously crawls tens of thousands of news sites, government sources, NGO sites, and blogs across 100+ languages
- Provides raw, structured event data (who did what, where, when) rather than LLM summaries
- Can run alongside Perplexity (GDELT for raw data, Perplexity for summarized context) or replace it
- Query GDELT per contract domain for relevant recent events

**Files:** New `gdelt.py` module, update `newswire.py`

#### 5. Resolution rule parsing

**Problem:** Andy's blog showed resolution rules are critical and often misunderstood. A contract about Trump and Mt. Rushmore only required an Executive Order to be *submitted*, not completed. The LLM needs to understand precisely what triggers resolution.

**What to do:**
- Explicitly parse and extract resolution rules for each contract from Polymarket
- Feed exact resolution criteria into the LLM prompt alongside the contract question
- Flag contracts with ambiguous or subjective resolution rules (these are harder to predict)

**Files:** Update `contracts.py` to extract resolution rules, include in analysis prompts

#### 6. Web search integration

**Problem:** Andy's original agent was "hamstrung by lack of relevant context" -- it would opine confidently with insufficient information.

**What to do:**
- Construct targeted search queries per contract based on domain and resolution criteria
- Use web search to gather recent, relevant information specific to each contract
- Feed search results as context to the LLM analysis pipeline
- Especially important for contracts outside politics (entertainment, sports, etc.) where the model's training data may be stale

**Files:** New `search.py` module, integrate into analysis pipeline

---

### C. Smarter Reasoning

#### 7. Council of models

**Problem:** A single LLM has blind spots. Andy proved that multiple models debating catches errors.

**What to do:**
- For top candidates (after Sonnet deep dive), ask Claude, GPT, and Gemini the same question
- Each gives an initial probability estimate with reasoning
- Models see each other's reasoning and update their estimates
- Final estimate is synthesized from the council
- Cost is ~3x per deep dive, so only use on the top ~5 highest-edge contracts per cycle
- Andy documented this working: Sonnet corrected a badly wrong analysis after hearing counter-arguments from GPT and Grok

**Files:** New `council.py` module

#### 8. Decomposition

**Problem:** Asking "what's the probability of X?" as a single question is how bad forecasters work. Good forecasters break it down.

**What to do:**
- Instead of one monolithic question, break each contract into sub-questions
- Example: "Will regime X fall?" becomes: "What's P(military intervention)? What's P(internal collapse)? What's P(negotiated transition)?"
- Estimate each sub-component separately, then combine
- This is how Tetlock's superforecasters work
- Basically free -- it's a prompt engineering change, no new infrastructure

**Files:** Update analysis prompts in `analyze.py`

#### 9. Adversarial second pass (red team)

**Problem:** LLMs are overconfident. Hearing counter-arguments helps (proven by Andy's council approach).

**What to do:**
- After the model produces its initial estimate, force it to construct the strongest possible argument *against* its own position
- Then ask it to update its estimate in light of the counter-argument
- Cheaper than a full council (one model arguing with itself vs. 3-4 models debating)
- Use on all Sonnet deep dives, not just top candidates

**Files:** Update `analyze.py` pipeline

#### 10. Category-specific reasoning

**Problem:** Politics, economics, entertainment, and sports all require fundamentally different analytical frameworks.

**What to do:**
- Different prompt templates for different domains:
  - Politics: institutional incentives, electoral mechanics, coalition dynamics, path dependencies
  - Economics: data releases, Fed signals, market structure, leading indicators
  - Entertainment: cultural trends, audience behavior, industry dynamics
  - Sports: statistics, injuries, matchup history
- Tag contracts by domain (improvement #1) and route to appropriate prompt template

**Files:** New `prompts/` directory with domain-specific templates

#### 11. Temporal context injection

**Problem:** Andy documented temporal confusion as a pervasive failure. His agent thought the 2024 election hadn't happened yet. It struggled with what's resolved vs. pending.

**What to do:**
- Inject explicit temporal context into every prompt: today's date, contract deadline, days until resolution
- Include what has already resolved (to avoid the "election already happened" problem)
- Describe where we are in longer political processes (e.g., "Congress is in recess until X")
- Currently a kludgy prompt fix -- needs to be systematic and automated

**Files:** Update analysis prompts, pull resolution dates from contract metadata

---

### D. Mechanical Guards

#### 12. Overconfidence shrinkage

**Problem:** Academic research confirms "systematic overconfidence across all models" and that "extended reasoning worsens rather than improves calibration."

**What to do:**
- After the model estimates a probability, mechanically shrink toward market price: `adjusted = market + (estimate - market) * 0.5`
- Subtract platform fees from expected edge
- Only flag as a trade when adjusted edge > fees (i.e., only profitable trades after costs)

**Files:** New `shrinkage.py` module, integrate into analysis pipeline

#### 13. Freshness-weighted detection

**Problem:** If the model disagrees with the market, is that genuine insight or stale information?

**What to do:**
- Score the freshness of evidence underlying each estimate
- Recent news (hours old) = higher confidence in divergence
- Old news (days/weeks old) = the market has probably already priced it in
- Weight the model's divergence from market by evidence freshness
- Automatically reduce confidence when evidence is stale

**Files:** Update `analyze.py`, integrate freshness scoring from GDELT/news timestamps

#### 14. Cross-market coherence checks

**Problem:** Logically related contracts can have incoherent prices that represent free edge.

**What to do:**
- If "X by June" is at 30% and "X by December" is at 25%, that's logically impossible -- December should be >= June
- Detect these inconsistencies automatically across the contract universe
- Flag incoherent pricing as trading opportunities
- Pure logic, no LLM needed

**Files:** New `coherence.py` module, runs after price collection

---

### E. Learning & Feedback

#### 15. Systematic prediction tracking

**Problem:** The system doesn't learn from its mistakes. No structured record of why predictions were right or wrong.

**What to do:**
- Log every prediction with full context: contract, estimate, market price, reasoning, evidence used, key factors
- After contracts resolve, compare prediction to outcome
- Store in structured format for analysis

**Files:** Update `evaluate.py`, new `prediction_log/` directory

#### 16. Per-domain performance tracking

**Problem:** The system treats all predictions equally. It doesn't know what it's good and bad at.

**What to do:**
- Track accuracy by domain: "65% accurate on politics, 40% on entertainment"
- Track accuracy by time horizon: "better at 24h than 7d"
- Track accuracy by divergence size: "we're right when we diverge by 5-10% but wrong when we diverge by 20%+"
- Use this to allocate confidence and compute to domains where the system performs well

**Files:** New `feedback.py` module, update `evaluate.py`

#### 17. Bayesian updating across cycles

**Problem:** Every cycle starts from scratch. Past reasoning is thrown away.

**What to do:**
- Maintain a running belief state per contract across cycles
- Each cycle updates the existing belief with new evidence rather than starting fresh
- If the model predicted 40% yesterday and nothing material has changed, today's estimate shouldn't jump to 60%
- This mirrors how good human forecasters actually work -- they don't start over every morning

**Files:** New `beliefs.py` module, persistent state per contract

#### 18. Feed lessons back into prompts

**Problem:** The system repeats the same mistakes because it has no memory of past errors.

**What to do:**
- After resolution, analyze what went wrong/right for each prediction
- Build a "lessons learned" database indexed by contract domain and error type
- Inject relevant past lessons into prompts: "Last time you analyzed a similar contract, you overestimated the probability because you didn't account for X"
- Iterate weekly (not daily) so there's enough data per iteration cycle

**Files:** Update `feedback.py`, new `lessons/` directory, update analysis prompts

---

### F. Extra Agent

#### 19. Smart money detector (non-LLM agent)

**Problem:** All other improvements analyze information. Nobody is watching what traders are doing.

**What to do:**
- A purely quantitative agent that watches trading patterns on Polymarket
- Track: volume spikes, bid-ask spread changes, sudden price movements, unusual order sizes
- Logic: if a contract suddenly moves 10% on high volume, informed traders are likely acting on information before news breaks
- Flag unusual activity and feed it as a signal to the LLM analysis pipeline
- This is a completely different signal source -- the LLM agents analyze news, this agent analyzes trader behavior
- No LLM needed, purely quantitative
- Complementary to everything else: can detect signals before they appear in news

**Files:** New `smart_money.py` module, integrate signals into analysis pipeline

### G. Contract Intelligence

#### 20. Structured contract metadata

**Problem:** Polymarket doesn't consistently tag contracts with useful metadata. Without knowing *what kind* of question a contract is, the system can't use domain-specific reasoning, track per-domain performance, or calibrate appropriately for different resolution types.

**What to do:**
- After pulling contracts from Polymarket (improvement #1), run each through Haiku to generate structured metadata tags:
  - **Domain:** politics, economics, entertainment, sports, science, crypto, etc.
  - **Time horizon:** days (resolves within a week), weeks (resolves within a month), months (resolves in 1-6 months)
  - **Resolution type:** official announcement (e.g., government press release), data release (e.g., jobs report), event outcome (e.g., election result), subjective judgment (e.g., journalist's call), market-based (e.g., price hitting a threshold)
  - **Geographic scope:** US, UK, EU, Middle East, global, etc.
  - **Key actors:** which people, institutions, or organizations are relevant
- Store metadata alongside contract data in `contracts/` directory as JSON
- Re-tag periodically (weekly) since context can shift
- This metadata feeds directly into:
  - **#10 Category-specific reasoning** -- domain tag routes to the right prompt template
  - **#16 Per-domain performance tracking** -- track accuracy by domain, horizon, resolution type
  - **#13 Freshness detection** -- different time horizons need different freshness thresholds
  - **#14 Cross-market coherence** -- domain and actor tags help identify logically related contracts

**Why this matters (from Andy's blog):** "Platforms could invest in more structured metadata -- tagging contracts by domain, time horizon, and resolution type -- so that AI systems can learn which kinds of questions they're good at and which they struggle with. Resolution rules matter enormously: a contract that resolves based on a specific government announcement is very different from one that resolves based on a journalist's judgment call."

**Files:** New `metadata.py` module, `contracts/` directory stores JSON per contract with metadata fields

---

## What stays the same

- Cron-based automated pipeline (still runs every 4h for data collection)
- Git auto-commits for auditability
- Price history tracking in CSV
- DigitalOcean droplet deployment
- Scoring engine structure (MSE, directional accuracy, virtual P&L)

## What changes fundamentally

- **Agents:** 4 deterministic Python agents -> LLM-based tiered analysis pipeline + smart money detector
- **Markets:** 1 contract -> ~30 contracts across multiple domains
- **Data:** Perplexity summaries -> GDELT raw data + web search + Perplexity
- **Reasoning:** Single model, single pass -> decomposition + adversarial pass + council of models
- **Horizon:** 4h -> 24h + 7d
- **Confidence:** Raw LLM estimates -> mechanically shrunk toward market + freshness-weighted
- **Learning:** Daily parameter tweak on 6 data points -> weekly iteration on hundreds of predictions with per-domain tracking

## Cost estimate

The binding constraint is inference cost, not engineering time (Andy's lesson #9).

**Per cycle (every 4 hours):**
- Haiku triage on ~30 contracts: ~$0.05
- Sonnet deep dive on ~10-15 contracts: ~$0.50-0.75
- Council of models on top ~5 contracts: ~$1.50-2.00
- Web search queries: ~$0.10
- GDELT: free (open data)
- Smart money detector: free (uses Polymarket API)

**Daily (6 cycles):** ~$12-17/day
**Monthly:** ~$360-500/month

The council is the most expensive component. Can scale it down (fewer contracts, fewer models) or up depending on budget.
