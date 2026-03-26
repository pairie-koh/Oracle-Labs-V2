"""
Oracle Lab — prepare.py
Fetches Polymarket prices, seeds price history, assembles briefings.
No LLM calls — just CLOB API + local file I/O.
"""

import json
import os
import sys
import csv
import time
from datetime import datetime, timezone, timedelta

import requests

from constants import (
    MARKETS, POLYMARKET_CLOB_URL, FORECAST_HORIZON_HOURS,
    PRICE_HISTORY_DIR, PRICE_CSV, BRIEFINGS_DIR, LATEST_BRIEFING,
    LATEST_FACTS, STATE_FILE,
)


def fetch_midpoint(token_id):
    """Fetch current midpoint price for a token from Polymarket CLOB."""
    url = f"{POLYMARKET_CLOB_URL}/midpoint"
    params = {"token_id": token_id}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    # API returns {"mid": "0.245"}
    return float(data["mid"])


def fetch_price_history(token_id, interval="max", fidelity=120):
    """Fetch historical price data from CLOB. Returns [{"t": unix_ts, "p": float}, ...]."""
    url = f"{POLYMARKET_CLOB_URL}/prices-history"
    params = {
        "market": token_id,
        "interval": interval,
        "fidelity": fidelity,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # API returns {"history": [{"t": 1741478700, "p": 0.233}, ...]}
    return data.get("history", [])


def seed_history_if_needed():
    """On first run, backfill prices.csv from CLOB price history."""
    if os.path.exists(PRICE_CSV):
        # Check if it has data (more than just headers)
        with open(PRICE_CSV, "r") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if len(rows) > 1:
                return  # already seeded

    print("Seeding price history from CLOB API...")
    os.makedirs(PRICE_HISTORY_DIR, exist_ok=True)

    market_keys = list(MARKETS.keys())

    # Fetch history for each market (YES token)
    histories = {}
    for key in market_keys:
        token_id = MARKETS[key]["yes_token_id"]
        print(f"  Fetching history for {key}...")
        hist = fetch_price_history(token_id)
        # Convert to {timestamp: price} for merging
        histories[key] = {point["t"]: float(point["p"]) for point in hist}
        print(f"    Got {len(hist)} data points")

    # Collect all unique timestamps across markets
    all_timestamps = set()
    for h in histories.values():
        all_timestamps.update(h.keys())
    all_timestamps = sorted(all_timestamps)

    # Write CSV
    with open(PRICE_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp"] + market_keys)
        for ts in all_timestamps:
            row = [ts]
            for key in market_keys:
                row.append(histories[key].get(ts, ""))
            writer.writerow(row)

    print(f"  Wrote {len(all_timestamps)} rows to {PRICE_CSV}")


def append_price_row(prices):
    """Append a row to prices.csv with current prices. prices = {market_key: float}."""
    os.makedirs(PRICE_HISTORY_DIR, exist_ok=True)
    market_keys = list(MARKETS.keys())
    ts = int(time.time())

    file_exists = os.path.exists(PRICE_CSV) and os.path.getsize(PRICE_CSV) > 0

    with open(PRICE_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp"] + market_keys)
        row = [ts]
        for key in market_keys:
            row.append(prices.get(key, ""))
        writer.writerow(row)


def load_latest_facts():
    """Load latest normalized facts. Returns empty list if no facts yet."""
    if not os.path.exists(LATEST_FACTS):
        return []
    try:
        with open(LATEST_FACTS, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def load_state():
    """Load current state. Returns empty dict if no state yet."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def compute_price_changes(current_prices):
    """Compute 4h, 24h, and 7d price deltas from CSV history.
    Returns {market_key: {"change_4h": float, "change_24h": float, "change_7d": float, "history_24h": [...]}}
    """
    changes = {}
    now = time.time()
    target_4h = now - (4 * 3600)
    target_24h = now - (24 * 3600)
    target_7d = now - (7 * 24 * 3600)

    if not os.path.exists(PRICE_CSV):
        for key in MARKETS:
            changes[key] = {"change_4h": 0.0, "change_24h": 0.0, "change_7d": 0.0, "history_24h": []}
        return changes

    # Read CSV into list of rows
    with open(PRICE_CSV, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        for key in MARKETS:
            changes[key] = {"change_4h": 0.0, "change_24h": 0.0, "change_7d": 0.0, "history_24h": []}
        return changes

    for key in MARKETS:
        current = current_prices.get(key)
        if current is None:
            changes[key] = {"change_4h": 0.0, "change_24h": 0.0, "change_7d": 0.0, "history_24h": []}
            continue

        # Find nearest price to 4h ago, 24h ago, and 7d ago
        price_4h = None
        price_24h = None
        price_7d = None
        best_dist_4h = float("inf")
        best_dist_24h = float("inf")
        best_dist_7d = float("inf")
        history_24h = []

        for row in rows:
            try:
                ts = float(row["timestamp"])
                val = row.get(key, "")
                if val == "":
                    continue
                price = float(val)
            except (ValueError, KeyError):
                continue

            # Collect 24h history
            if ts >= target_24h:
                history_24h.append({"t": int(ts), "p": price})

            # Find nearest to 4h ago
            dist = abs(ts - target_4h)
            if dist < best_dist_4h:
                best_dist_4h = dist
                price_4h = price

            # Find nearest to 24h ago
            dist = abs(ts - target_24h)
            if dist < best_dist_24h:
                best_dist_24h = dist
                price_24h = price

            # Find nearest to 7d ago
            dist = abs(ts - target_7d)
            if dist < best_dist_7d:
                best_dist_7d = dist
                price_7d = price

        change_4h = round(current - price_4h, 6) if price_4h is not None else 0.0
        change_24h = round(current - price_24h, 6) if price_24h is not None else 0.0
        change_7d = round(current - price_7d, 6) if price_7d is not None else 0.0

        changes[key] = {
            "change_4h": change_4h,
            "change_24h": change_24h,
            "change_7d": change_7d,
            "history_24h": history_24h,
        }

    return changes


def assemble_briefing():
    """Orchestrate everything: fetch prices, compute changes, load facts/state, write briefing."""
    print("=== Assembling briefing ===")

    # Seed history on first run
    seed_history_if_needed()

    # Fetch current prices
    print("Fetching current prices...")
    current_prices = {}
    for key, market in MARKETS.items():
        try:
            price = fetch_midpoint(market["yes_token_id"])
            current_prices[key] = price
            print(f"  {key}: {price:.4f}")
        except Exception as e:
            print(f"  {key}: FAILED ({e})")

    if not current_prices:
        print("ERROR: No prices fetched. Cannot assemble briefing.")
        sys.exit(1)

    # Append to price history
    append_price_row(current_prices)

    # Compute changes
    price_changes = compute_price_changes(current_prices)

    # Build market_prices section
    market_prices = {}
    for key in current_prices:
        ch = price_changes[key]
        # Find previous price (current minus 4h change)
        previous = round(current_prices[key] - ch["change_4h"], 6)
        market_prices[key] = {
            "current": current_prices[key],
            "previous": previous,
            "change_4h": ch["change_4h"],
            "change_24h": ch["change_24h"],
            "change_7d": ch["change_7d"],
            "history_24h": ch["history_24h"],
        }

    # Load facts and state
    fresh_facts = load_latest_facts()
    state = load_state()

    # Assemble briefing
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    briefing = {
        "timestamp": timestamp,
        "market_prices": market_prices,
        "fresh_facts": fresh_facts,
        "state": state,
        "price_history_path": PRICE_CSV,
    }

    # Write timestamped file
    os.makedirs(BRIEFINGS_DIR, exist_ok=True)
    ts_filename = timestamp.replace(":", "").replace("-", "")
    briefing_path = os.path.join(BRIEFINGS_DIR, f"{ts_filename}.json")
    with open(briefing_path, "w") as f:
        json.dump(briefing, f, indent=2)
    print(f"Wrote briefing to {briefing_path}")

    # Write latest.json (symlink-like copy)
    with open(LATEST_BRIEFING, "w") as f:
        json.dump(briefing, f, indent=2)
    print(f"Wrote {LATEST_BRIEFING}")

    # Summary
    print(f"\nBriefing summary:")
    print(f"  Timestamp: {timestamp}")
    for key, mp in market_prices.items():
        print(f"  {key}: {mp['current']:.4f} (4h: {mp['change_4h']:+.4f}, 24h: {mp['change_24h']:+.4f}, 7d: {mp['change_7d']:+.4f})")
    print(f"  Fresh facts: {len(fresh_facts)}")
    print(f"  State keys: {list(state.keys()) if state else '(empty)'}")

    return briefing


if __name__ == "__main__":
    assemble_briefing()
