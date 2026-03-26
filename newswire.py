"""
Oracle Lab — newswire.py
Two-stage news pipeline:
  1. Perplexity via OpenRouter: 2 broad news sweeps per market
  2. Haiku normalization: raw text → structured JSON facts
"""

import json
import os
import csv
import sys
import time
from datetime import datetime, timezone

import requests

from constants import (
    MARKETS, OPENROUTER_API_URL, PERPLEXITY_API_URL,
    PERPLEXITY_MODEL, HAIKU_MODEL_OPENROUTER,
    SOURCE_CATEGORIES, INDICATOR_CATEGORIES,
    QUERY_TEMPLATES, FACT_HISTORY_DIR, FACTS_CSV, LATEST_FACTS,
)


# ── Stage 1: Perplexity Sweep ────────────────────────────────────────────────

def call_perplexity(prompt):
    """Call Perplexity API directly. Returns raw text response."""
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        raise RuntimeError("PERPLEXITY_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": PERPLEXITY_MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }

    resp = requests.post(PERPLEXITY_API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def gather_raw_news():
    """Run all Perplexity queries (2 per market). Returns list of (market_key, focus, raw_text)."""
    results = []
    total_calls = sum(len(QUERY_TEMPLATES[k]) for k in MARKETS if k in QUERY_TEMPLATES)
    call_num = 0

    for market_key in MARKETS:
        if market_key not in QUERY_TEMPLATES:
            print(f"  WARN: No query templates for {market_key}, skipping")
            continue

        for focus, prompt in QUERY_TEMPLATES[market_key]:
            call_num += 1
            print(f"  [{call_num}/{total_calls}] {market_key} / {focus}...")
            try:
                raw = call_perplexity(prompt)
                results.append((market_key, focus, raw))
                print(f"    Got {len(raw)} chars")
            except Exception as e:
                print(f"    FAILED: {e}")
                results.append((market_key, focus, f"[Error fetching news: {e}]"))

    return results


# ── Stage 2: Haiku Normalization ─────────────────────────────────────────────

def normalize_facts(raw_results):
    """Send raw news to Haiku for structured extraction. Returns list of fact dicts."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    # Build the raw text block
    raw_block = ""
    for market_key, focus, text in raw_results:
        raw_block += f"\n=== Market: {market_key} | Focus: {focus} ===\n{text}\n"

    # Build allowed categories per market
    market_categories = ""
    for key in MARKETS:
        cats = INDICATOR_CATEGORIES.get(key, [])
        market_categories += f"  Market '{key}': {json.dumps(cats)}\n"

    prompt = f"""Extract structured news facts from the following raw news reports.

For each distinct factual claim, create a JSON object with these exact fields:
- "claim": A single, clear factual statement (1-2 sentences)
- "source": The news source or outlet that reported it
- "source_category": MUST be exactly one of: {json.dumps(SOURCE_CATEGORIES)}
- "indicator_category": MUST be one of the allowed values for its market:
{market_categories}
- "market": The market key this fact is relevant to (one of: {json.dumps(list(MARKETS.keys()))})
- "time": ISO8601 timestamp of when the event occurred (best estimate, use today's date if unclear)
- "confidence": "high", "medium", or "low" based on source reliability and specificity

Rules:
- Extract 10-30 facts total across all markets
- Each claim should be a single, verifiable factual statement
- Do NOT include analysis, speculation, or predictions — only facts
- If a source isn't clearly one of the categories, use your best judgment
- Deduplicate: if the same fact appears in multiple reports, include it once with the most reliable source
- If no real news is found, return an empty array

Return ONLY a JSON array of fact objects. No markdown, no explanation, just the JSON array.

Raw news reports:
{raw_block}"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/oracle-lab",
        "X-Title": "Oracle Lab",
    }
    payload = {
        "model": HAIKU_MODEL_OPENROUTER,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }

    print("  Calling Haiku for normalization...")
    resp = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    raw_response = data["choices"][0]["message"]["content"]

    # Strip markdown code fences if present
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        # Remove first line (```json) and last line (```)
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1])

    try:
        facts = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"    WARN: Failed to parse Haiku response as JSON: {e}")
        print(f"    Raw response (first 500 chars): {raw_response[:500]}")
        return []

    if not isinstance(facts, list):
        print(f"    WARN: Haiku returned non-list: {type(facts)}")
        return []

    # Validate and filter
    valid_facts = []
    valid_markets = set(MARKETS.keys())
    valid_sources = set(SOURCE_CATEGORIES)
    valid_indicators = {}
    for key in MARKETS:
        valid_indicators[key] = set(INDICATOR_CATEGORIES.get(key, []))

    for fact in facts:
        if not isinstance(fact, dict):
            continue

        # Check required fields
        missing = [f for f in ["claim", "source", "source_category", "indicator_category", "market", "time", "confidence"]
                   if f not in fact]
        if missing:
            print(f"    Dropping fact missing fields {missing}: {fact.get('claim', '?')[:50]}")
            continue

        # Validate enum values
        if fact["source_category"] not in valid_sources:
            print(f"    Dropping fact with invalid source_category '{fact['source_category']}': {fact['claim'][:50]}")
            continue

        if fact["market"] not in valid_markets:
            print(f"    Dropping fact with invalid market '{fact['market']}': {fact['claim'][:50]}")
            continue

        market_indicators = valid_indicators.get(fact["market"], set())
        if fact["indicator_category"] not in market_indicators:
            print(f"    Dropping fact with invalid indicator_category '{fact['indicator_category']}' for market '{fact['market']}': {fact['claim'][:50]}")
            continue

        if fact["confidence"] not in ("high", "medium", "low"):
            fact["confidence"] = "medium"  # default rather than drop

        valid_facts.append(fact)

    print(f"  Normalized: {len(valid_facts)} valid facts (dropped {len(facts) - len(valid_facts)})")
    return valid_facts


# ── Save ─────────────────────────────────────────────────────────────────────

def save_facts(facts):
    """Append facts to facts.csv and write latest.json."""
    os.makedirs(FACT_HISTORY_DIR, exist_ok=True)
    cycle_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Append to CSV
    file_exists = os.path.exists(FACTS_CSV) and os.path.getsize(FACTS_CSV) > 0
    with open(FACTS_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["cycle_timestamp", "claim", "source", "source_category",
                             "indicator_category", "market", "time", "confidence"])
        for fact in facts:
            writer.writerow([
                cycle_ts,
                fact.get("claim", ""),
                fact.get("source", ""),
                fact.get("source_category", ""),
                fact.get("indicator_category", ""),
                fact.get("market", ""),
                fact.get("time", ""),
                fact.get("confidence", ""),
            ])

    # Write latest.json
    with open(LATEST_FACTS, "w") as f:
        json.dump(facts, f, indent=2)

    print(f"  Saved {len(facts)} facts to {FACTS_CSV} and {LATEST_FACTS}")


# ── Main ─────────────────────────────────────────────────────────────────────

def run_newswire():
    """Run the full newswire pipeline."""
    print("=== Newswire Pipeline ===")

    print("[1/3] Gathering raw news from Perplexity...")
    raw_results = gather_raw_news()

    # Check if we got anything useful
    useful = [r for r in raw_results if not r[2].startswith("[Error")]
    if not useful:
        print("ERROR: All Perplexity calls failed. No news gathered.")
        # Save empty facts so downstream doesn't crash
        save_facts([])
        return []

    print(f"\n[2/3] Normalizing {len(useful)} raw reports with Haiku...")
    facts = normalize_facts(raw_results)

    print(f"\n[3/3] Saving facts...")
    save_facts(facts)

    print(f"\n=== Newswire complete: {len(facts)} facts ===")
    return facts


if __name__ == "__main__":
    run_newswire()
