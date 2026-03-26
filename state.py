"""
Oracle Lab — state.py
Rolling state tracker. Uses Haiku to update key-value state fields
based on latest facts. One call per cycle.
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

from constants import (
    MARKETS, INDICATOR_CATEGORIES, OPENROUTER_API_URL, HAIKU_MODEL_OPENROUTER,
    STATE_FILE, STATE_DIR, LATEST_FACTS,
)

# Intensity vocabulary for state fields
INTENSITY_LEVELS = ["none", "low", "moderate", "high", "critical"]


def default_state():
    """Build a default empty state structure from MARKETS and INDICATOR_CATEGORIES."""
    state = {"last_updated": None, "markets": {}}
    for key in MARKETS:
        market_state = {
            "current_status": "No data yet.",
            "last_major_event": "None recorded.",
            "last_major_event_time": None,
        }
        # Add an intensity field for each indicator category
        for cat in INDICATOR_CATEGORIES.get(key, []):
            market_state[cat] = "none"
        state["markets"][key] = market_state
    return state


def load_current_state():
    """Load state/current.json, or return default if missing."""
    if not os.path.exists(STATE_FILE):
        return default_state()
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        # Ensure all expected markets and fields exist
        state = validate_state(state)
        return state
    except (json.JSONDecodeError, IOError):
        return default_state()


def validate_state(state):
    """Ensure state has all expected keys for all markets."""
    if "markets" not in state:
        state["markets"] = {}

    for key in MARKETS:
        if key not in state["markets"]:
            state["markets"][key] = {}
        ms = state["markets"][key]

        if "current_status" not in ms:
            ms["current_status"] = "No data yet."
        if "last_major_event" not in ms:
            ms["last_major_event"] = "None recorded."
        if "last_major_event_time" not in ms:
            ms["last_major_event_time"] = None

        for cat in INDICATOR_CATEGORIES.get(key, []):
            if cat not in ms:
                ms[cat] = "none"
            elif ms[cat] not in INTENSITY_LEVELS:
                ms[cat] = "moderate"  # default if invalid

    return state


def build_update_prompt(current_state, latest_facts):
    """Build the Haiku prompt to update state based on new facts."""
    # Build the schema description
    market_fields = {}
    for key in MARKETS:
        fields = {
            "current_status": "1-2 sentence summary of the current situation",
            "last_major_event": "1 sentence describing the most significant recent event",
            "last_major_event_time": "ISO8601 timestamp of last major event",
        }
        for cat in INDICATOR_CATEGORIES.get(key, []):
            fields[cat] = f"Intensity level: one of {INTENSITY_LEVELS}"
        market_fields[key] = fields

    prompt = f"""You are updating a rolling state tracker for geopolitical forecasting markets.

Current state:
{json.dumps(current_state, indent=2)}

New facts to incorporate:
{json.dumps(latest_facts, indent=2)}

Update the state based on these new facts. For each market:
1. Update "current_status" to reflect the latest situation (1-2 sentences)
2. If any fact represents a more significant event than "last_major_event", update it
3. Update intensity fields based on the evidence. Use ONLY these values: {INTENSITY_LEVELS}

Expected output structure:
{json.dumps({"last_updated": "ISO8601", "markets": market_fields}, indent=2)}

Rules:
- Only update fields where new facts provide evidence for a change
- If no facts are relevant to a field, keep its current value
- Intensity levels should reflect cumulative evidence, not just the latest fact
- Be conservative: don't jump from "none" to "critical" without strong evidence
- "last_updated" should be the current timestamp

Return ONLY valid JSON. No markdown, no explanation."""

    return prompt


def call_haiku(prompt):
    """Call Haiku via OpenRouter. Returns parsed JSON."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/oracle-lab",
        "X-Title": "Oracle Lab",
    }
    payload = {
        "model": HAIKU_MODEL_OPENROUTER,
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt}],
    }

    resp = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    raw = data["choices"][0]["message"]["content"]

    # Strip markdown fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1])

    return json.loads(cleaned)


def save_state(state):
    """Write state to state/current.json."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    print(f"  Saved state to {STATE_FILE}")


def run_state_update():
    """Run the state update pipeline."""
    print("=== State Update ===")

    # Load current state
    current_state = load_current_state()
    print(f"  Loaded state for markets: {list(current_state.get('markets', {}).keys())}")

    # Load latest facts
    if not os.path.exists(LATEST_FACTS):
        print("  No latest facts found. Keeping current state.")
        return current_state

    with open(LATEST_FACTS, "r") as f:
        facts = json.load(f)

    if not facts:
        print("  No facts to process. Keeping current state.")
        return current_state

    print(f"  Processing {len(facts)} facts...")

    # Haiku is required for state updates — no fallback
    try:
        prompt = build_update_prompt(current_state, facts)
        print("  Calling Haiku for state update...")
        new_state = call_haiku(prompt)
        new_state = validate_state(new_state)
        save_state(new_state)
        print(f"  State updated via Haiku")
    except Exception as e:
        print(f"  WARN: State update failed ({e}). Keeping previous state unchanged.")
        return current_state

    # Summary
    for market_key, ms in new_state.get("markets", {}).items():
        print(f"\n  {market_key}:")
        print(f"    Status: {ms.get('current_status', 'N/A')}")
        for cat in INDICATOR_CATEGORIES.get(market_key, []):
            print(f"    {cat}: {ms.get(cat, 'N/A')}")

    return new_state


if __name__ == "__main__":
    run_state_update()
