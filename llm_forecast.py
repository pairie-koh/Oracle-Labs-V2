"""
Oracle Lab — llm_forecast.py
Three-tier LLM forecast pipeline: Haiku triage -> Sonnet deep dive -> Opus deep dive.

Runs alongside the deterministic agents as a separate forecaster.
Predictions are logged to llm_predictions/ for scoring comparison.

Usage: python llm_forecast.py [--date YYYY-MM-DD] [--dry-run]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

# Fix Windows console encoding for international characters (e.g., Erdoğan)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from constants import OPENROUTER_API_URL, POLYMARKET_CLOB_URL
from hyperliquid import format_for_prompt as hyperliquid_price_block
from hyperliquid import format_btc_intraday as btc_intraday_block
from weather import format_for_prompt as weather_forecast_block
from gdelt import format_for_prompt as gdelt_news_block
from lessons import build_lessons_block


# ── Model Config ─────────────────────────────────────────────────────────────

MODELS = {
    "haiku": "anthropic/claude-haiku-4.5",
    "sonnet": "anthropic/claude-sonnet-4",
    "opus": "anthropic/claude-opus-4",
}

# Divergence thresholds for tiering
SONNET_THRESHOLD = 0.05   # 5% divergence triggers Sonnet
OPUS_THRESHOLD = 0.15     # 15% divergence triggers Opus
MAX_OPUS_PER_CYCLE = 5    # Cap Opus calls per cycle

# Overconfidence shrinkage: pull LLM estimates toward market price.
# 0.0 = ignore LLM entirely (use market), 1.0 = trust LLM fully (no shrinkage).
# 0.5 = split the difference. Research shows LLMs are systematically overconfident,
# but prediction markets can also be wrong. We keep 75% of LLM divergence from market.
SHRINKAGE_KEEP = 0.75


# ── Overconfidence Shrinkage ────────────────────────────────────────────────

def shrink_toward_market(llm_prob, market_price):
    """Pull an LLM probability estimate toward the market price.

    adjusted = market + SHRINKAGE_KEEP * (llm - market)

    With SHRINKAGE_KEEP=0.75: if LLM says 0.80 and market is 0.50,
    adjusted = 0.50 + 0.75*(0.80-0.50) = 0.725 instead of 0.80.
    """
    adjusted = market_price + SHRINKAGE_KEEP * (llm_prob - market_price)
    return max(0.0, min(1.0, adjusted))


def normalize_probs(probs):
    """Normalize probabilities to sum to 1.0.

    LLMs sometimes return multi-outcome probs that don't sum to 1
    (e.g. treating each outcome independently). This rescales them
    while preserving relative ordering.
    """
    total = sum(probs)
    if total <= 0:
        # Degenerate case: uniform
        return [1.0 / len(probs)] * len(probs)
    return [p / total for p in probs]


def shrink_multi_outcome(llm_probs, market_prices):
    """Apply shrinkage to each outcome, then re-normalize to sum to 1.0.

    Shrinkage pulls each outcome toward its market price independently,
    but Polymarket market prices include a vig (~3-10%) so they sum to >1.0.
    Re-normalizing ensures our final output is a valid probability distribution.
    """
    shrunk = [shrink_toward_market(p, m) for p, m in zip(llm_probs, market_prices)]
    return normalize_probs(shrunk)


# ── Temporal Context ────────────────────────────────────────────────────────

def build_temporal_context(end_date_str):
    """Build temporal context string for prompts.

    Returns text like:
      TEMPORAL CONTEXT:
        Days until resolution: 42
        Urgency: Medium — weeks remain, gradual developments likely.
    """
    if not end_date_str:
        return ""

    try:
        # Handle both date and datetime formats
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"):
            try:
                end_date = datetime.strptime(end_date_str, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        else:
            return ""

        now = datetime.now(timezone.utc)
        days_left = (end_date - now).days

        if days_left < 0:
            urgency = "EXPIRED — this contract has already passed its end date."
        elif days_left == 0:
            urgency = "Resolves TODAY — only hours remain."
        elif days_left <= 3:
            urgency = "Very high — resolves within days. Late-breaking events are critical."
        elif days_left <= 14:
            urgency = "High — resolves within 2 weeks. Current trajectory matters most."
        elif days_left <= 60:
            urgency = "Medium — weeks remain. Gradual developments likely."
        elif days_left <= 180:
            urgency = "Low — months remain. Many possible paths."
        else:
            urgency = "Very low — long time horizon. Base rates dominate."

        return f"""TEMPORAL CONTEXT:
  Days until resolution: {days_left}
  End date: {end_date_str}
  Urgency: {urgency}"""

    except Exception:
        return ""


# ── Category-Specific Reasoning ────────────────────────────────────────────

# Domain-specific "Think about" cues that replace the generic ones in prompts.
# Each category gets guidance tailored to the kind of reasoning that domain requires.
CATEGORY_CUES = {
    "geopolitics": """Think about:
- What are the key actors' incentives and constraints? Who has veto power?
- What is the current diplomatic/military status quo? What would have to change?
- Are there upcoming summits, deadlines, or elections that create pressure?
- What are the historical base rates for this type of geopolitical event?
- How does the time remaining affect likelihood? Is there a path from here to resolution?""",

    "economics": """Think about:
- What do leading economic indicators (PMI, claims, yield curve) suggest?
- What is the consensus forecast from economists/Fed dot plot?
- How do current asset prices (provided above) relate to this outcome?
- What are the key data releases or FOMC meetings before resolution?
- Are there structural factors the market might be over/underweighting?""",

    "politics": """Think about:
- What is the current legislative/procedural status? What steps remain?
- What are the key actors' public positions and political incentives?
- Are there whip counts, polling data, or committee votes to consider?
- What historical precedents exist for similar political processes?
- Is the market pricing in the correct conditional probabilities?""",

    "sports": """Think about:
- What are the current standings, records, and recent form?
- Are there injuries, suspensions, or roster changes to consider?
- What do betting odds from sportsbooks suggest?
- What is the tournament/playoff structure — how many games/rounds remain?
- Are there matchup advantages or historical patterns in this competition?""",

    "tech": """Think about:
- What are the latest benchmark results and model releases?
- What have the companies announced or leaked about upcoming releases?
- What is the current competitive landscape and trajectory?
- Are there industry events, conferences, or release cycles coming up?
- Is the market correctly weighting recent vs. expected developments?""",

    "entertainment": """Think about:
- What are the latest credible reports, leaks, or official announcements?
- What is the production/release timeline and current status?
- Are there contractual, regulatory, or logistical factors?
- What do industry insiders and trade publications indicate?
- How reliable has the source company been with previous timelines?""",

    "weather": """Think about:
- What does the NWS forecast say for today's high temperature? This is your most reliable signal.
- Same-day weather forecasts are highly accurate — trust the NWS forecast high.
- Look at the hourly temperature progression — when does the peak occur?
- Which temperature bucket does the forecast high fall into? Put 60-70% probability there.
- Put 15-20% in each adjacent bucket to account for minor forecast errors.
- Put minimal probability (1-5%) in non-adjacent buckets unless there's extreme uncertainty.
- Could rain, cloud cover, or wind cause the actual high to be 1-2 degrees off the forecast?
- Be aggressive: if forecast says 67°F and the bucket is 65-69°F, that bucket should get most of your probability mass.""",
}

# Fallback for unknown categories
DEFAULT_CUES = """Think about:
- What is the base rate for events like this?
- What recent information shifts the probability?
- Is the market price reasonable, too high, or too low?
- How does the time remaining affect likelihood?"""


def get_category_cues(contract):
    """Get category-specific thinking cues for a contract.

    Checks category field first, then domain as fallback.
    Returns the appropriate Think about block.
    """
    category = contract.get("category", "")
    domain = contract.get("domain", "")

    # Try category first, then domain
    if category in CATEGORY_CUES:
        return CATEGORY_CUES[category]
    if domain in CATEGORY_CUES:
        return CATEGORY_CUES[domain]

    return DEFAULT_CUES


# ── LLM API (via OpenRouter) ─────────────────────────────────────────────────

def call_anthropic(prompt, model_key, max_tokens=1024):
    """Call Claude via OpenRouter. Returns raw text response."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    model = MODELS[model_key]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/oracle-lab",
        "X-Title": "Oracle Lab",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }

    resp = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ── Market Price Fetch ───────────────────────────────────────────────────────

def get_clob_midpoint(token_id):
    """Fetch midpoint price from Polymarket CLOB API."""
    try:
        resp = requests.get(
            f"{POLYMARKET_CLOB_URL}/midpoint",
            params={"token_id": token_id},
            timeout=10,
        )
        resp.raise_for_status()
        return float(resp.json().get("mid", 0))
    except Exception:
        return None


# ── Prompt Building ──────────────────────────────────────────────────────────

def build_binary_prompt(contract, market_price, tier):
    """Build prompt for a binary contract."""
    depth = {
        "haiku": "Give a brief assessment (2-3 sentences).",
        "sonnet": "Give a thorough assessment (1-2 paragraphs). Consider key factors, recent developments, and potential surprises.",
        "opus": "Give a deep, nuanced assessment (2-3 paragraphs). Consider base rates, key actors, incentive structures, temporal dynamics, and what the market might be missing.",
    }

    # Inject context blocks if available
    hl_block = hyperliquid_price_block()
    slug = contract.get("slug", contract.get("_key", ""))
    gdelt_block = gdelt_news_block(contract_slug=slug)
    temporal_block = build_temporal_context(contract.get("end_date", ""))
    context_section = ""
    if temporal_block:
        context_section += f"\n{temporal_block}\n"
    if hl_block:
        context_section += f"\n{hl_block}\n"
    if gdelt_block:
        context_section += f"\n{gdelt_block}\n"

    # Inject past performance lessons
    contract_key = contract.get("_key", contract.get("slug", ""))
    domain = contract.get("category", contract.get("domain", ""))
    lessons_block = build_lessons_block(contract_key, domain=domain)
    if lessons_block:
        context_section += f"\n{lessons_block}\n"

    # Inject targeted context for specific rolling contracts
    if contract_key == "bitcoin_daily":
        btc_block = btc_intraday_block()
        if btc_block:
            context_section += f"\n{btc_block}\n"

    # Get resolution rules and category cues
    resolution_text = contract.get('resolution_rules', '') or contract.get('resolution_source', 'Standard Polymarket resolution')
    category_cues = get_category_cues(contract)

    # Build metadata context line
    meta_parts = []
    geo = contract.get("geo_scope", "")
    actors = contract.get("key_actors", "")
    res_type = contract.get("resolution_type", "")
    if geo:
        meta_parts.append(f"GEOGRAPHIC SCOPE: {geo}")
    if actors:
        meta_parts.append(f"KEY ACTORS: {actors}")
    if res_type:
        meta_parts.append(f"RESOLUTION TYPE: {res_type}")
    metadata_block = "\n".join(meta_parts)

    prompt = f"""You are a calibrated forecaster on a prediction market. Your job is to estimate the true probability of an outcome.

CONTRACT: {contract['question']}
DESCRIPTION: {contract.get('description', 'N/A')}
RESOLUTION: {resolution_text}
{metadata_block}
END DATE: {contract.get('end_date', 'N/A')}
CURRENT MARKET PRICE (YES): {market_price:.3f} ({market_price*100:.1f}%)

Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
{context_section}
{depth[tier]}

{category_cues}

IMPORTANT: You must end your response with exactly this format on its own line:
PROBABILITY: 0.XX

Where 0.XX is your estimated probability (0.00 to 1.00) that this contract resolves YES.

NOTE: Don't hedge or play it safe - make confident predictions when the evidence supports them. Markets reward accuracy, not appearing reasonable. If you think an outcome is likely, don't be afraid to assign high probability."""

    return prompt


def build_multi_outcome_prompt(contract, markets_with_prices, tier):
    """Build prompt for a multi-outcome contract (multiple binary markets under one event)."""
    depth = {
        "haiku": "Give a brief assessment (2-3 sentences per outcome).",
        "sonnet": "Give a thorough assessment. Consider key factors for each outcome.",
        "opus": "Give a deep, nuanced assessment. Consider base rates, correlations between outcomes, and what the market might be missing.",
    }

    outcomes_block = ""
    for m in markets_with_prices:
        outcomes_block += f"  - {m['question']}: market={m['market_price']:.3f} ({m['market_price']*100:.1f}%)\n"

    # Inject context blocks if available
    hl_block = hyperliquid_price_block()
    slug = contract.get("slug", contract.get("_key", ""))
    gdelt_block = gdelt_news_block(contract_slug=slug)
    temporal_block = build_temporal_context(contract.get("end_date", ""))
    context_section = ""
    if temporal_block:
        context_section += f"\n{temporal_block}\n"
    if hl_block:
        context_section += f"\n{hl_block}\n"
    if gdelt_block:
        context_section += f"\n{gdelt_block}\n"

    # Inject past performance lessons
    contract_key = contract.get("_key", contract.get("slug", ""))
    domain = contract.get("category", contract.get("domain", ""))
    lessons_block = build_lessons_block(contract_key, domain=domain)
    if lessons_block:
        context_section += f"\n{lessons_block}\n"

    # Inject targeted context for specific rolling contracts
    if contract_key == "nyc_temp":
        weather_block = weather_forecast_block(city="nyc")
        if weather_block:
            context_section += f"\n{weather_block}\n"
    elif contract_key == "miami_temp":
        weather_block = weather_forecast_block(city="miami")
        if weather_block:
            context_section += f"\n{weather_block}\n"

    # Get resolution rules and category cues
    resolution_text = contract.get('resolution_rules', '') or contract.get('resolution_source', '')
    category_cues = get_category_cues(contract)

    resolution_line = f"\nRESOLUTION: {resolution_text}" if resolution_text else ""

    # Build metadata context
    meta_parts = []
    geo = contract.get("geo_scope", "")
    actors = contract.get("key_actors", "")
    res_type = contract.get("resolution_type", "")
    if geo:
        meta_parts.append(f"GEOGRAPHIC SCOPE: {geo}")
    if actors:
        meta_parts.append(f"KEY ACTORS: {actors}")
    if res_type:
        meta_parts.append(f"RESOLUTION TYPE: {res_type}")
    metadata_block = "\n".join(meta_parts)

    prompt = f"""You are a calibrated forecaster on a prediction market. Your job is to estimate the true probability of each outcome.

EVENT: {contract['name']}
OUTCOMES AND CURRENT MARKET PRICES:
{outcomes_block}{resolution_line}
{metadata_block}
Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
{context_section}
{depth[tier]}

{category_cues}

Additionally:
- Do the market probabilities make sense relative to each other?
- Probabilities across all outcomes should roughly sum to 1.0.

IMPORTANT: You must end your response with probabilities for each outcome, one per line, in this exact format:
PROBABILITY [outcome question or short label]: 0.XX

List them in the same order as above.

NOTE: Don't spread probability evenly to hedge - if you think one outcome is most likely, concentrate probability there. Markets reward accuracy, not appearing reasonable."""

    return prompt


# ── Adversarial Second Pass ──────────────────────────────────────────────────

def build_adversarial_binary_prompt(contract, market_price, initial_reasoning, initial_prob):
    """Build adversarial prompt that forces the model to argue against its own position.

    Only used on Sonnet/Opus deep dives. The model sees its initial reasoning and
    must identify weaknesses, then commit to a revised probability.
    """
    direction = "higher" if initial_prob > market_price else "lower"

    return f"""You are a calibrated forecaster performing a self-critique. Below is your initial analysis of a prediction market contract. Your job is to find weaknesses in your own reasoning and arrive at a revised probability.

CONTRACT: {contract.get('question', contract.get('name', ''))}
RESOLUTION: {contract.get('resolution_rules', '') or contract.get('resolution_source', 'Standard Polymarket resolution')}
END DATE: {contract.get('end_date', 'N/A')}
CURRENT MARKET PRICE: {market_price:.3f} ({market_price*100:.1f}%)

YOUR INITIAL ANALYSIS:
{initial_reasoning}

YOUR INITIAL PROBABILITY: {initial_prob:.3f} ({initial_prob*100:.1f}%) — this is {direction} than the market.

Now argue AGAINST your initial position. Consider:
1. What evidence did you overlook or underweight?
2. What assumptions are you making that could be wrong?
3. Why might the market price actually be correct?
4. Are you being overconfident in your divergence from the market?
5. What would have to be true for your initial estimate to be badly wrong?

After your critique, provide a REVISED probability that accounts for these concerns. It's fine to stick close to your initial estimate if your critique doesn't find major issues, but be honest about weaknesses.

IMPORTANT: End with exactly this format:
REVISED PROBABILITY: 0.XX"""


def build_adversarial_multi_prompt(contract, markets_with_prices, initial_reasoning, initial_probs):
    """Build adversarial prompt for multi-outcome contracts."""
    outcomes_block = ""
    for m, p in zip(markets_with_prices, initial_probs):
        outcomes_block += f"  - {m['question']}: market={m['market_price']:.3f}, your_initial={p:.3f}\n"

    return f"""You are a calibrated forecaster performing a self-critique. Below is your initial analysis of a multi-outcome prediction market. Your job is to find weaknesses in your own reasoning and arrive at revised probabilities.

EVENT: {contract.get('name', contract.get('question', ''))}
RESOLUTION: {contract.get('resolution_rules', '') or contract.get('resolution_source', '')}

OUTCOMES — MARKET PRICES vs YOUR INITIAL ESTIMATES:
{outcomes_block}
YOUR INITIAL ANALYSIS:
{initial_reasoning}

Now argue AGAINST your initial position. Consider:
1. Which outcomes did you over- or under-estimate and why?
2. Do your probabilities maintain coherence (roughly sum to 1.0)?
3. Are you anchoring too much on one outcome at the expense of others?
4. Why might the market distribution actually be more accurate than yours?
5. What scenarios would make your estimates badly wrong?

After your critique, provide REVISED probabilities. It's fine to stick close to your initial estimates if your critique doesn't find major issues.

IMPORTANT: End with revised probabilities, one per line:
REVISED PROBABILITY [outcome question or short label]: 0.XX

List them in the same order as above."""


def parse_adversarial_binary(response_text):
    """Extract revised probability from adversarial response."""
    for line in reversed(response_text.strip().split("\n")):
        cleaned = _clean_line(line)
        if cleaned.upper().startswith("REVISED PROBABILITY"):
            val = _extract_probability_value(cleaned)
            if val is not None:
                return val
    return None


def parse_adversarial_multi(response_text):
    """Extract revised probabilities from adversarial multi-outcome response."""
    probs = []
    for line in response_text.strip().split("\n"):
        cleaned = _clean_line(line)
        if cleaned.upper().startswith("REVISED PROBABILITY"):
            val = _extract_probability_value(cleaned)
            if val is not None:
                probs.append(val)
    return probs


# ── Response Parsing ─────────────────────────────────────────────────────────

def _clean_line(line):
    """Strip markdown formatting and list prefixes from a line.

    Handles: **bold**, - bullets, 1. numbered lists, * bullets
    """
    line = line.strip()
    # Strip bold markdown
    line = line.replace("**", "")
    # Strip leading bullet/number prefixes
    if line.startswith("- "):
        line = line[2:]
    elif line.startswith("* "):
        line = line[2:]
    else:
        # Strip numbered list prefix like "1. ", "12. "
        import re
        line = re.sub(r"^\d+\.\s+", "", line)
    return line.strip()


def _extract_probability_value(line):
    """Extract a float probability from a line that contains a colon-separated value.

    Handles formats like:
      PROBABILITY: 0.30
      PROBABILITY [label]: 0.30
      PROBABILITY label with ?: 0.30
    """
    # Find the LAST colon followed by a number — this handles labels containing colons or '?:'
    import re
    match = re.search(r":\s*([\d.]+)\s*$", line)
    if match:
        try:
            val = float(match.group(1))
            return max(0.0, min(1.0, val))
        except ValueError:
            pass
    return None


def parse_binary_probability(response_text):
    """Extract probability from LLM response.

    Robust to markdown formatting (**bold**), whitespace, etc.
    Falls back to searching for '0.XX' patterns in the last few lines.
    """
    import re

    # Primary: look for explicit PROBABILITY: line
    for line in reversed(response_text.strip().split("\n")):
        cleaned = _clean_line(line)
        if cleaned.upper().startswith("PROBABILITY:") or cleaned.upper().startswith("PROBABILITY :"):
            val = _extract_probability_value(cleaned)
            if val is not None:
                return val

    # Fallback: look for "probability" followed by a number anywhere in last 5 lines
    last_lines = "\n".join(response_text.strip().split("\n")[-5:])
    match = re.search(r"probability[:\s]+\*?\*?(0\.\d+)", last_lines, re.IGNORECASE)
    if match:
        try:
            val = float(match.group(1))
            return max(0.0, min(1.0, val))
        except ValueError:
            pass

    return None


def parse_multi_outcome_probabilities(response_text):
    """Extract probabilities for multi-outcome from LLM response.

    Robust to markdown formatting (**bold**), bullet prefixes (- , * , 1. ),
    and labels containing special characters (?, colons, etc.).
    """
    probs = []
    for line in response_text.strip().split("\n"):
        cleaned = _clean_line(line)
        if cleaned.upper().startswith("PROBABILITY"):
            val = _extract_probability_value(cleaned)
            if val is not None:
                probs.append(val)
    return probs


# ── Tier Logic ───────────────────────────────────────────────────────────────

def run_triage(contracts, dry_run=False):
    """
    Tier 1: Run Haiku on all contracts.
    Returns list of predictions with divergence scores.
    """
    print(f"\n=== TIER 1: Haiku Triage ({len(contracts)} contracts) ===\n")
    predictions = []

    for i, contract in enumerate(contracts, 1):
        name = contract.get("question", contract.get("name", "?"))
        print(f"  [{i}/{len(contracts)}] {name[:70]}")

        if contract["_type"] == "binary":
            market_price = contract["_market_price"]
            if dry_run:
                print(f"    [DRY RUN] market={market_price:.3f}")
                predictions.append({
                    **contract,
                    "_tier": "haiku",
                    "_prediction": market_price,
                    "_divergence": 0.0,
                    "_reasoning": "[dry run]",
                })
                continue

            prompt = build_binary_prompt(contract, market_price, "haiku")
            try:
                response = call_anthropic(prompt, "haiku", max_tokens=768)
                raw_prob = parse_binary_probability(response)
                if raw_prob is None:
                    print(f"    WARNING: Could not parse probability, using market price")
                    raw_prob = market_price
                    response += "\n[PARSE FAILED]"

                shrunk_prob = shrink_toward_market(raw_prob, market_price)
                divergence = abs(raw_prob - market_price)
                print(f"    haiku={raw_prob:.3f} market={market_price:.3f} div={divergence:.3f} (shrunk={shrunk_prob:.3f})")

                predictions.append({
                    **contract,
                    "_tier": "haiku",
                    "_prediction": raw_prob,
                    "_shrunk_prediction": shrunk_prob,
                    "_market_price": market_price,
                    "_divergence": divergence,
                    "_reasoning": response,
                })
            except Exception as e:
                print(f"    ERROR: {e}")
                predictions.append({
                    **contract,
                    "_tier": "haiku",
                    "_prediction": market_price,
                    "_divergence": 0.0,
                    "_reasoning": f"[ERROR: {e}]",
                })

            time.sleep(0.3)  # Rate limit

        elif contract["_type"] == "multi-outcome":
            markets = contract["_markets"]
            if dry_run:
                print(f"    [DRY RUN] {len(markets)} outcomes")
                predictions.append({
                    **contract,
                    "_tier": "haiku",
                    "_outcome_predictions": [m["market_price"] for m in markets],
                    "_divergence": 0.0,
                    "_reasoning": "[dry run]",
                })
                continue

            prompt = build_multi_outcome_prompt(contract, markets, "haiku")
            try:
                # Scale tokens with outcome count: 2048 base + 128 per outcome beyond 8
                multi_tokens = 2048 + max(0, len(markets) - 8) * 128
                response = call_anthropic(prompt, "haiku", max_tokens=multi_tokens)
                raw_probs = parse_multi_outcome_probabilities(response)

                if len(raw_probs) > len(markets):
                    # LLM output extra lines — truncate to expected count
                    print(f"    NOTE: Got {len(raw_probs)} probs for {len(markets)} outcomes, truncating")
                    raw_probs = raw_probs[:len(markets)]
                elif len(raw_probs) < len(markets):
                    # Too few — fall back to market prices
                    print(f"    WARNING: Got {len(raw_probs)} probs for {len(markets)} outcomes, using market prices")
                    raw_probs = [m["market_price"] for m in markets]
                    response += "\n[PARSE MISMATCH]"

                # Normalize so outcomes sum to 1.0
                raw_probs = normalize_probs(raw_probs)

                market_prices = [m["market_price"] for m in markets]
                shrunk_probs = shrink_multi_outcome(raw_probs, market_prices)

                # Divergence = max divergence across outcomes (raw)
                divs = [abs(p - m) for p, m in zip(raw_probs, market_prices)]
                max_div = max(divs) if divs else 0.0
                print(f"    {len(raw_probs)} outcomes, max_div={max_div:.3f}")

                predictions.append({
                    **contract,
                    "_tier": "haiku",
                    "_outcome_predictions": raw_probs,
                    "_shrunk_outcome_predictions": shrunk_probs,
                    "_divergence": max_div,
                    "_reasoning": response,
                })
            except Exception as e:
                print(f"    ERROR: {e}")
                predictions.append({
                    **contract,
                    "_tier": "haiku",
                    "_outcome_predictions": [m["market_price"] for m in markets],
                    "_divergence": 0.0,
                    "_reasoning": f"[ERROR: {e}]",
                })

            time.sleep(0.3)

    return predictions


def run_deep_dive(predictions, dry_run=False):
    """
    Tier 2 & 3: Run Sonnet/Opus on contracts with significant divergence.
    Mutates predictions in-place with upgraded tier results.
    """
    # Sort by divergence to prioritize
    divergent = [(i, p) for i, p in enumerate(predictions) if p["_divergence"] >= SONNET_THRESHOLD]
    divergent.sort(key=lambda x: x[1]["_divergence"], reverse=True)

    if not divergent:
        print("\n=== No contracts above divergence threshold — skipping deep dives ===")
        return predictions

    # Split into Opus (>15%) and Sonnet (5-15%)
    opus_candidates = [(i, p) for i, p in divergent if p["_divergence"] >= OPUS_THRESHOLD]
    sonnet_candidates = [(i, p) for i, p in divergent if p["_divergence"] < OPUS_THRESHOLD]

    # Cap Opus calls
    opus_to_run = opus_candidates[:MAX_OPUS_PER_CYCLE]
    # Remaining Opus candidates get Sonnet instead
    sonnet_to_run = sonnet_candidates + opus_candidates[MAX_OPUS_PER_CYCLE:]

    print(f"\n=== TIER 2: Sonnet Deep Dive ({len(sonnet_to_run)} contracts) ===\n")
    for idx, pred in sonnet_to_run:
        _run_upgrade(predictions, idx, "sonnet", dry_run)
        time.sleep(0.5)

    print(f"\n=== TIER 3: Opus Deep Dive ({len(opus_to_run)} contracts) ===\n")
    for idx, pred in opus_to_run:
        _run_upgrade(predictions, idx, "opus", dry_run)
        time.sleep(0.5)

    return predictions


def _run_upgrade(predictions, idx, tier, dry_run):
    """Upgrade a single prediction with a deeper model + adversarial second pass.

    After the initial deep dive, runs an adversarial self-critique where the model
    argues against its own position, then commits to a revised probability.
    Logs both pre-adversarial and post-adversarial predictions.
    """
    pred = predictions[idx]
    name = pred.get("question", pred.get("name", "?"))
    print(f"  {name[:70]} (div={pred['_divergence']:.3f})")

    if dry_run:
        print(f"    [DRY RUN] would call {tier} + adversarial")
        return

    try:
        if pred["_type"] == "binary":
            # Step 1: Initial deep dive
            prompt = build_binary_prompt(pred, pred["_market_price"], tier)
            response = call_anthropic(prompt, tier, max_tokens=2048)
            initial_prob = parse_binary_probability(response)
            if initial_prob is None:
                print(f"    WARNING: Could not parse {tier} probability")
                return

            initial_div = abs(initial_prob - pred["_market_price"])
            print(f"    {tier} initial={initial_prob:.3f} market={pred['_market_price']:.3f} div={initial_div:.3f}")

            # Step 2: Adversarial self-critique
            adv_prompt = build_adversarial_binary_prompt(
                pred, pred["_market_price"], response, initial_prob
            )
            time.sleep(0.3)
            adv_response = call_anthropic(adv_prompt, tier, max_tokens=1536)
            revised_prob = parse_adversarial_binary(adv_response)

            if revised_prob is not None:
                final_prob = revised_prob
                print(f"    adversarial revised={revised_prob:.3f} (was {initial_prob:.3f}, delta={revised_prob - initial_prob:+.3f})")
            else:
                # Adversarial parse failed — use initial
                final_prob = initial_prob
                print(f"    adversarial parse failed, keeping initial={initial_prob:.3f}")
                adv_response += "\n[ADVERSARIAL PARSE FAILED]"

            shrunk_prob = shrink_toward_market(final_prob, pred["_market_price"])
            new_div = abs(final_prob - pred["_market_price"])

            pred["_tier"] = tier
            pred["_prediction"] = final_prob
            pred["_pre_adversarial_prediction"] = initial_prob
            pred["_shrunk_prediction"] = shrunk_prob
            pred["_divergence"] = new_div
            pred["_reasoning"] = response
            pred["_adversarial_reasoning"] = adv_response

        elif pred["_type"] == "multi-outcome":
            markets = pred["_markets"]

            # Step 1: Initial deep dive
            prompt = build_multi_outcome_prompt(pred, markets, tier)
            multi_tokens = 2048 + max(0, len(markets) - 8) * 128
            response = call_anthropic(prompt, tier, max_tokens=multi_tokens)
            initial_probs = parse_multi_outcome_probabilities(response)

            if len(initial_probs) > len(markets):
                print(f"    NOTE: Got {len(initial_probs)} probs for {len(markets)} outcomes, truncating")
                initial_probs = initial_probs[:len(markets)]
            elif len(initial_probs) < len(markets):
                print(f"    WARNING: Got {len(initial_probs)} probs for {len(markets)} outcomes")
                return

            initial_probs = normalize_probs(initial_probs)

            market_prices = [m["market_price"] for m in markets]
            initial_divs = [abs(p - m) for p, m in zip(initial_probs, market_prices)]
            initial_max_div = max(initial_divs) if initial_divs else 0.0
            print(f"    {tier} initial: {len(initial_probs)} outcomes, max_div={initial_max_div:.3f}")

            # Step 2: Adversarial self-critique
            adv_prompt = build_adversarial_multi_prompt(
                pred, markets, response, initial_probs
            )
            time.sleep(0.3)
            adv_response = call_anthropic(adv_prompt, tier, max_tokens=multi_tokens)
            revised_probs = parse_adversarial_multi(adv_response)

            # Truncate if LLM output extra lines
            if len(revised_probs) > len(markets):
                revised_probs = revised_probs[:len(markets)]

            if len(revised_probs) == len(markets):
                revised_probs = normalize_probs(revised_probs)
                final_probs = revised_probs
                # Show largest revision
                max_revision = max(abs(r - i) for r, i in zip(revised_probs, initial_probs))
                print(f"    adversarial revised: max_revision={max_revision:.3f}")
            else:
                # Adversarial parse failed — use initial
                final_probs = initial_probs
                print(f"    adversarial parse failed ({len(revised_probs)} probs), keeping initial")
                adv_response += "\n[ADVERSARIAL PARSE FAILED]"

            shrunk_probs = shrink_multi_outcome(final_probs, market_prices)
            divs = [abs(p - m) for p, m in zip(final_probs, market_prices)]
            max_div = max(divs) if divs else 0.0
            print(f"    final: max_div={max_div:.3f}")

            pred["_tier"] = tier
            pred["_outcome_predictions"] = final_probs
            pred["_pre_adversarial_predictions"] = initial_probs
            pred["_shrunk_outcome_predictions"] = shrunk_probs
            pred["_divergence"] = max_div
            pred["_reasoning"] = response
            pred["_adversarial_reasoning"] = adv_response

    except Exception as e:
        print(f"    ERROR calling {tier}: {e}")


# ── Contract Loading ─────────────────────────────────────────────────────────

def load_rolling_contracts():
    """Load today's rolling contracts with market prices."""
    path = os.path.join("contracts", "rolling_today.json")
    if not os.path.exists(path):
        print(f"  WARNING: {path} not found. Run rolling_contracts.py first.")
        return []

    with open(path) as f:
        data = json.load(f)

    contracts = []
    for key, contract in data.get("contracts", {}).items():
        if contract.get("status") != "active":
            continue

        markets = contract.get("markets", [])
        if not markets:
            continue

        if contract["type"] == "binary" and len(markets) == 1:
            m = markets[0]
            # Binary: Up/Down or Yes/No
            yes_price = m["prices"][0] if m["prices"] else 0.5
            contracts.append({
                "question": m["question"],
                "description": "",
                "end_date": m.get("end_date", ""),
                "slug": m.get("slug", ""),
                "condition_id": m.get("condition_id", ""),
                "token_ids": m.get("token_ids", []),
                "category": contract.get("category", ""),
                "_type": "binary",
                "_market_price": yes_price,
                "_source": "rolling",
                "_key": key,
            })

        elif contract["type"] == "multi-outcome":
            # Multi-outcome: multiple binary markets under one event
            markets_with_prices = []
            for m in markets:
                yes_price = m["prices"][0] if m["prices"] else 0.0
                markets_with_prices.append({
                    "question": m["question"],
                    "market_price": yes_price,
                    "slug": m.get("slug", ""),
                    "condition_id": m.get("condition_id", ""),
                    "token_ids": m.get("token_ids", []),
                })

            contracts.append({
                "name": contract["name"],
                "question": contract["name"],
                "description": "",
                "end_date": markets[0].get("end_date", "") if markets else "",
                "category": contract.get("category", ""),
                "_type": "multi-outcome",
                "_markets": markets_with_prices,
                "_market_price": 0,  # Not meaningful for multi-outcome
                "_source": "rolling",
                "_key": key,
            })

    return contracts


def should_run_now(frequency):
    """Check if a contract with the given frequency should be forecast this cycle.

    The cron runs every 4h at minute 5: hours 0, 4, 8, 12, 16, 20 UTC.
    We use 4h windows to determine which cron slot we're in.

    Frequencies:
      every_12h  -> run at cron slots 0 and 12 UTC
      every_24h  -> run at cron slot 0 UTC only
      once_daily -> run at cron slot 12 UTC only (morning US Eastern)
      once_weekly -> run on Mondays at cron slot 0 UTC
    """
    now = datetime.now(timezone.utc)
    # Round to nearest 4h cron slot (0,4,8,12,16,20)
    slot = (now.hour // 4) * 4
    weekday = now.weekday()  # 0 = Monday

    if frequency == "every_12h":
        return slot in (0, 12)
    elif frequency == "every_24h":
        return slot == 0
    elif frequency == "once_daily":
        return slot == 12
    elif frequency == "once_weekly":
        return weekday == 0 and slot == 0
    else:
        # Unknown frequency — run every cycle as fallback
        return True


def load_static_contracts(frequency_filter=True):
    """Load static contracts from active_contracts.json with fresh CLOB prices.

    The new format supports both binary and multi-outcome contracts,
    each with a prediction_frequency field.
    """
    path = os.path.join("contracts", "active_contracts.json")
    if not os.path.exists(path):
        print(f"  WARNING: {path} not found. Run build_active_contracts.py first.")
        return []

    with open(path) as f:
        data = json.load(f)

    contracts = []
    skipped = 0
    expired = 0
    now = datetime.now(timezone.utc)
    for c in data.get("contracts", []):
        # Skip expired contracts
        end_date_str = c.get("end_date", "")
        if end_date_str:
            try:
                for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"):
                    try:
                        end_dt = datetime.strptime(end_date_str, fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
                else:
                    end_dt = None
                if end_dt and end_dt < now:
                    expired += 1
                    continue
            except Exception:
                pass

        # Check frequency gate
        freq = c.get("prediction_frequency", "every_12h")
        if frequency_filter and not should_run_now(freq):
            skipped += 1
            continue

        contract_type = c.get("contract_type", "binary")

        if contract_type == "binary":
            # Binary contract — fetch fresh price from CLOB
            yes_token = c.get("yes_token_id", "")
            fresh_price = None
            if yes_token:
                fresh_price = get_clob_midpoint(yes_token)
            if fresh_price is not None:
                yes_price = fresh_price
            else:
                yes_price = c.get("current_prices", {}).get("yes", 0.5)

            contracts.append({
                "question": c.get("question", c.get("contract_name", "")),
                "description": c.get("description", ""),
                "end_date": c.get("end_date", ""),
                "slug": c.get("slug", ""),
                "condition_id": c.get("condition_id", ""),
                "resolution_source": c.get("resolution_source", ""),
                "resolution_rules": c.get("resolution_rules", ""),
                "yes_token_id": yes_token,
                "no_token_id": c.get("no_token_id", ""),
                "category": c.get("category", ""),
                "domain": c.get("domain", ""),
                "geo_scope": c.get("geo_scope", ""),
                "key_actors": c.get("key_actors", ""),
                "resolution_type": c.get("resolution_type", ""),
                "_type": "binary",
                "_market_price": yes_price,
                "_source": "static",
                "_key": c.get("slug", ""),
            })
            time.sleep(0.1)

        elif contract_type == "multi-outcome":
            # Multi-outcome contract — fetch fresh prices per outcome
            outcomes = c.get("outcomes", [])
            if not outcomes:
                continue

            # For large events (>15 outcomes), only track top outcomes by stored price
            # to keep CLOB calls and LLM tokens manageable
            MAX_OUTCOMES = 15
            if len(outcomes) > MAX_OUTCOMES:
                outcomes = sorted(outcomes, key=lambda o: o.get("yes_price", 0), reverse=True)[:MAX_OUTCOMES]

            markets_with_prices = []
            for outcome in outcomes:
                yes_token = outcome.get("yes_token_id", "")
                fresh_price = None
                if yes_token:
                    fresh_price = get_clob_midpoint(yes_token)
                if fresh_price is not None:
                    mkt_price = fresh_price
                else:
                    mkt_price = outcome.get("yes_price", 0.5)

                markets_with_prices.append({
                    "question": outcome.get("question", ""),
                    "market_price": mkt_price,
                    "slug": outcome.get("market_slug", ""),
                    "condition_id": outcome.get("condition_id", ""),
                    "token_ids": [outcome.get("yes_token_id", "")],
                })
                time.sleep(0.1)

            contracts.append({
                "name": c.get("contract_name", c.get("question", "")),
                "question": c.get("question", c.get("contract_name", "")),
                "description": c.get("description", ""),
                "end_date": c.get("end_date", ""),
                "slug": c.get("slug", ""),
                "resolution_source": c.get("resolution_source", ""),
                "resolution_rules": c.get("resolution_rules", ""),
                "category": c.get("category", ""),
                "domain": c.get("domain", ""),
                "geo_scope": c.get("geo_scope", ""),
                "key_actors": c.get("key_actors", ""),
                "resolution_type": c.get("resolution_type", ""),
                "_type": "multi-outcome",
                "_markets": markets_with_prices,
                "_market_price": 0,
                "_source": "static",
                "_key": c.get("slug", ""),
            })

    if expired:
        print(f"  Skipped {expired} expired contracts")
    if skipped:
        print(f"  Skipped {skipped} contracts (not due this cycle per frequency)")

    return contracts


# ── Cross-Market Coherence Checks ────────────────────────────────────────────

# Coherence rules define logical constraints between related predictions.
# "temporal_subset": P(shorter deadline) must be <= P(longer deadline)
# "inverse_soft": two contracts where both being high is contradictory (warning only)
COHERENCE_RULES = [
    # Iran deal: April 30 deadline is a subset of the 2027 deadline
    {
        "type": "temporal_subset",
        "name": "Iran deal: P(by April 30) <= P(before 2027)",
        "short_key": "us-iran-nuclear-deal-by-april-30",
        "long_key": "us-iran-nuclear-deal-before-2027",
    },
    # Hormuz: "normalizes" and "Iran closes" are contradictory signals
    {
        "type": "inverse_soft",
        "name": "Hormuz: normalize vs close are inversely related",
        "key_a": "strait-of-hormuz-traffic-returns-to-normal-by-april-30",
        "key_b": "will-iran-close-the-strait-of-hormuz-by-2027",
        "threshold": 0.6,  # Warn if both P(a) > 0.6 and max P(b outcomes) > 0.6
    },
]


def check_coherence(predictions):
    """Check and enforce logical coherence across related predictions.

    Applies hard constraints (temporal subset) and logs soft warnings (inverse).
    Mutates predictions in-place. Returns list of adjustments made.
    """
    # Build lookup by _key for fast access
    pred_by_key = {}
    for i, p in enumerate(predictions):
        key = p.get("_key", "")
        if key:
            pred_by_key[key] = (i, p)

    adjustments = []

    print("\n=== Coherence Checks ===\n")

    for rule in COHERENCE_RULES:
        if rule["type"] == "temporal_subset":
            short_key = rule["short_key"]
            long_key = rule["long_key"]

            if short_key not in pred_by_key or long_key not in pred_by_key:
                continue

            _, short_pred = pred_by_key[short_key]
            _, long_pred = pred_by_key[long_key]

            # Both must be binary for this rule
            if short_pred["_type"] != "binary" or long_pred["_type"] != "binary":
                continue

            p_short = short_pred["_prediction"]
            p_long = long_pred["_prediction"]

            if p_short > p_long:
                # Violation: shorter deadline has higher probability than longer
                # Fix: raise P(long) to match P(short)
                old_long = p_long
                long_pred["_prediction"] = p_short
                long_pred["_divergence"] = abs(p_short - long_pred["_market_price"])
                long_pred["_shrunk_prediction"] = shrink_toward_market(p_short, long_pred["_market_price"])

                adj = {
                    "rule": rule["name"],
                    "action": "adjusted",
                    "detail": f"P({short_key})={p_short:.3f} > P({long_key})={old_long:.3f} -> raised P({long_key}) to {p_short:.3f}",
                }
                adjustments.append(adj)
                print(f"  ADJUSTED: {adj['detail']}")
            else:
                gap = p_long - p_short
                print(f"  OK: {rule['name']} (P_short={p_short:.3f} <= P_long={p_long:.3f}, gap={gap:.3f})")

        elif rule["type"] == "inverse_soft":
            key_a = rule["key_a"]
            key_b = rule["key_b"]
            threshold = rule.get("threshold", 0.6)

            if key_a not in pred_by_key or key_b not in pred_by_key:
                continue

            _, pred_a = pred_by_key[key_a]
            _, pred_b = pred_by_key[key_b]

            # Get P(a) — binary
            if pred_a["_type"] == "binary":
                p_a = pred_a["_prediction"]
            else:
                continue

            # Get max P(b) — could be multi-outcome
            if pred_b["_type"] == "binary":
                p_b = pred_b["_prediction"]
            elif pred_b["_type"] == "multi-outcome":
                p_b = max(pred_b.get("_outcome_predictions", [0]))
            else:
                continue

            if p_a > threshold and p_b > threshold:
                adj = {
                    "rule": rule["name"],
                    "action": "warning",
                    "detail": f"POTENTIAL CONTRADICTION: P({key_a})={p_a:.3f} and max P({key_b})={p_b:.3f} both > {threshold}",
                }
                adjustments.append(adj)
                print(f"  WARNING: {adj['detail']}")
            else:
                print(f"  OK: {rule['name']} (P_a={p_a:.3f}, max_P_b={p_b:.3f})")

    # Check internal coherence for multi-outcome contracts:
    # outcomes with temporal ordering (e.g., "by Jan 31" <= "by March 31" <= "by June 30")
    for key, (idx, pred) in pred_by_key.items():
        if pred["_type"] != "multi-outcome":
            continue

        markets = pred.get("_markets", [])
        probs = pred.get("_outcome_predictions", [])
        if len(markets) != len(probs):
            continue

        # Detect temporal ordering in outcome questions
        # Look for patterns like "by [month] [day]" or "before [year]"
        # Only applies when outcomes represent DIFFERENT dates for the same event
        # (e.g., "by Jan 31" vs "by March 31"), NOT different entities at the same date
        # (e.g., "Will Macron be out before 2027" vs "Will Putin be out before 2027")
        temporal_outcomes = _extract_temporal_ordering(markets, probs)
        if len(temporal_outcomes) < 2:
            continue

        # If all temporal outcomes share the same date_key, these are different
        # entities with the same deadline, NOT a temporal ordering — skip
        unique_dates = set(t["date_key"] for t in temporal_outcomes)
        if len(unique_dates) < 2:
            continue

        # Check monotonicity: earlier deadline <= later deadline
        violations = []
        for i in range(len(temporal_outcomes) - 1):
            earlier = temporal_outcomes[i]
            later = temporal_outcomes[i + 1]
            if earlier["prob"] > later["prob"] + 0.001:  # Small tolerance
                violations.append((earlier, later))

        if violations:
            for earlier, later in violations:
                # Fix: raise later to match earlier
                later_idx = later["idx"]
                old_val = probs[later_idx]
                probs[later_idx] = earlier["prob"]

                adj = {
                    "rule": f"temporal ordering in {key}",
                    "action": "adjusted",
                    "detail": f"P({earlier['label'][:30]})={earlier['prob']:.3f} > P({later['label'][:30]})={old_val:.3f} -> raised to {earlier['prob']:.3f}",
                }
                adjustments.append(adj)
                print(f"  ADJUSTED: {adj['detail']}")

            # Update the prediction with fixed probs
            pred["_outcome_predictions"] = probs
            market_prices = [m["market_price"] for m in markets]
            pred["_shrunk_outcome_predictions"] = shrink_multi_outcome(probs, market_prices)
            divs = [abs(p - m) for p, m in zip(probs, market_prices)]
            pred["_divergence"] = max(divs) if divs else 0.0

    if not adjustments:
        print("  All checks passed — no adjustments needed.")

    return adjustments


def _extract_temporal_ordering(markets, probs):
    """Extract outcomes that have temporal deadlines and return them sorted by date.

    Looks for patterns like:
    - "by January 31" / "by March 31" / "by June 30"
    - "before 2027"
    - "by April 30, 2026" / "by December 31, 2026"

    Returns list of dicts: [{"label": ..., "prob": ..., "idx": ..., "date_key": ...}]
    sorted by date_key.
    """
    import re

    MONTH_ORDER = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }

    temporal = []
    for i, (m, p) in enumerate(zip(markets, probs)):
        q = m.get("question", "").lower()

        # Pattern: "by [month] [day]" or "by [month] [day], [year]"
        match = re.search(r"by (\w+)\s+(\d+)", q)
        if match:
            month_name = match.group(1)
            day = int(match.group(2))
            month_num = MONTH_ORDER.get(month_name)
            if month_num:
                # Extract year if present, default to 2026
                year_match = re.search(r",?\s*(20\d{2})", q[match.end():])
                year = int(year_match.group(1)) if year_match else 2026
                date_key = year * 10000 + month_num * 100 + day
                temporal.append({"label": m["question"], "prob": p, "idx": i, "date_key": date_key})
                continue

        # Pattern: "before [year]"
        match = re.search(r"before (\d{4})", q)
        if match:
            year = int(match.group(1))
            date_key = year * 10000  # Jan 1 of that year
            temporal.append({"label": m["question"], "prob": p, "idx": i, "date_key": date_key})

    # Sort by date
    temporal.sort(key=lambda x: x["date_key"])
    return temporal


# ── Prediction Saving ────────────────────────────────────────────────────────

def save_predictions(predictions, timestamp):
    """Save predictions to llm_predictions/ directory."""
    output_dir = "llm_predictions"
    os.makedirs(output_dir, exist_ok=True)

    # Strip long reasoning for the summary file
    summary = []
    for p in predictions:
        entry = {
            "question": p.get("question", p.get("name", "")),
            "source": p.get("_source", ""),
            "key": p.get("_key", ""),
            "type": p.get("_type", ""),
            "tier": p.get("_tier", ""),
            "market_price": p.get("_market_price", 0),
            "divergence": p.get("_divergence", 0),
            "timestamp": timestamp,
        }

        if p["_type"] == "binary":
            entry["prediction"] = p.get("_prediction", 0)
            entry["shrunk_prediction"] = p.get("_shrunk_prediction", p.get("_prediction", 0))
            if "_pre_adversarial_prediction" in p:
                entry["pre_adversarial_prediction"] = p["_pre_adversarial_prediction"]
        elif p["_type"] == "multi-outcome":
            entry["outcome_predictions"] = p.get("_outcome_predictions", [])
            entry["shrunk_outcome_predictions"] = p.get("_shrunk_outcome_predictions", p.get("_outcome_predictions", []))
            entry["outcome_questions"] = [m["question"] for m in p.get("_markets", [])]
            entry["outcome_market_prices"] = [m["market_price"] for m in p.get("_markets", [])]
            if "_pre_adversarial_predictions" in p:
                entry["pre_adversarial_predictions"] = p["_pre_adversarial_predictions"]

        # Save truncated reasoning for iteration feedback loop
        reasoning = p.get("_reasoning", "")
        if reasoning and reasoning not in ("[dry run]",):
            entry["reasoning_excerpt"] = reasoning[:500]

        summary.append(entry)

    # Save summary (compact, for scoring)
    summary_file = os.path.join(output_dir, f"predictions_{timestamp.replace(':', '-')}.json")
    with open(summary_file, "w") as f:
        json.dump({"timestamp": timestamp, "predictions": summary}, f, indent=2)

    # Save latest (for quick access)
    latest_file = os.path.join(output_dir, "latest.json")
    with open(latest_file, "w") as f:
        json.dump({"timestamp": timestamp, "predictions": summary}, f, indent=2)

    print(f"\nSaved {len(summary)} predictions to {summary_file}")
    return summary_file


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LLM forecast pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Skip API calls, use market prices")
    parser.add_argument("--rolling-only", action="store_true", help="Only forecast rolling contracts")
    parser.add_argument("--static-only", action="store_true", help="Only forecast static contracts")
    parser.add_argument("--haiku-only", action="store_true", help="Skip Sonnet/Opus deep dives")
    parser.add_argument("--no-frequency-filter", action="store_true", help="Ignore prediction frequency gates, run all contracts")
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"=== LLM Forecast Pipeline — {timestamp} ===\n")

    freq_filter = not args.no_frequency_filter

    # Load contracts
    contracts = []

    if not args.static_only:
        print("Loading rolling contracts...")
        rolling = load_rolling_contracts()
        print(f"  {len(rolling)} rolling contracts loaded")
        contracts.extend(rolling)

    if not args.rolling_only:
        print("Loading static contracts...")
        static = load_static_contracts(frequency_filter=freq_filter)
        print(f"  {len(static)} static contracts loaded")
        contracts.extend(static)

    if not contracts:
        print("ERROR: No contracts to forecast. Run rolling_contracts.py and/or contracts.py first.")
        sys.exit(1)

    print(f"\nTotal contracts: {len(contracts)}")

    # Tier 1: Haiku triage on all contracts
    predictions = run_triage(contracts, dry_run=args.dry_run)

    # Tier 2 & 3: Deep dives on divergent contracts
    if not args.haiku_only:
        predictions = run_deep_dive(predictions, dry_run=args.dry_run)

    # Cross-market coherence checks
    coherence_adjustments = check_coherence(predictions)

    # Summary
    tiers = {}
    for p in predictions:
        tier = p.get("_tier", "unknown")
        tiers[tier] = tiers.get(tier, 0) + 1

    print(f"\n=== Summary ===")
    print(f"Total predictions: {len(predictions)}")
    for tier, count in sorted(tiers.items()):
        print(f"  {tier}: {count}")

    avg_div = sum(p["_divergence"] for p in predictions) / len(predictions) if predictions else 0
    print(f"Average divergence: {avg_div:.3f}")
    if coherence_adjustments:
        n_adj = sum(1 for a in coherence_adjustments if a["action"] == "adjusted")
        n_warn = sum(1 for a in coherence_adjustments if a["action"] == "warning")
        print(f"Coherence: {n_adj} adjustments, {n_warn} warnings")

    # Save
    output_file = save_predictions(predictions, timestamp)

    print("\nDone!")


if __name__ == "__main__":
    main()
