"""
Oracle Lab — Backtest
Replays historical prices through all 4 agents, scoring predictions against
actuals. Produces backtest_results.csv for the progress plot.

Usage: python3 scripts/backtest.py
"""

import csv
import json
import math
import os
import sys
from datetime import datetime, timezone

# Add project root to path
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pandas as pd

# Import agent forecast functions directly
from agents.momentum.forecast import forecast_market as momentum_forecast
from agents.historian.forecast import forecast_market as historian_forecast
from agents.game_theorist.forecast import forecast_market as gt_forecast
from agents.quant.forecast import forecast_market as quant_forecast

# Historian needs its load_adaptive_base_rate to work with varying data
from agents.historian.forecast import load_adaptive_base_rate

PRICE_CSV = os.path.join(PROJECT_ROOT, "price_history", "prices.csv")
BRIEFING_PATH = os.path.join(PROJECT_ROOT, "briefings", "latest.json")
OUTPUT_CSV = os.path.join(PROJECT_ROOT, "backtest_results.csv")

# Minimum warmup observations before we start forecasting
WARMUP = 30
# How many price steps ahead is the "actual" outcome (each step ~2h, so 2 steps ~4h)
HORIZON_STEPS = 2


def load_prices():
    """Load price history."""
    df = pd.read_csv(PRICE_CSV)
    df["timestamp"] = df["timestamp"].astype(float)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def load_facts():
    """Load the available facts from the latest briefing."""
    with open(BRIEFING_PATH, "r") as f:
        briefing = json.load(f)
    return briefing.get("fresh_facts", [])


def build_market_data(prices_so_far, market_key):
    """Construct market_data dict from price history up to current point."""
    current = prices_so_far[market_key].iloc[-1]
    prev_price = prices_so_far[market_key].iloc[-2] if len(prices_so_far) >= 2 else current

    # 4h change: ~2 steps back
    idx_4h = max(0, len(prices_so_far) - 3)
    price_4h_ago = prices_so_far[market_key].iloc[idx_4h]
    change_4h = current - price_4h_ago

    # 24h change: ~12 steps back
    idx_24h = max(0, len(prices_so_far) - 13)
    price_24h_ago = prices_so_far[market_key].iloc[idx_24h]
    change_24h = current - price_24h_ago

    return {
        "current": current,
        "previous": prev_price,
        "change_4h": change_4h,
        "change_24h": change_24h,
    }


def run_backtest():
    """Run all 4 agents across historical prices and score against actuals."""
    prices = load_prices()
    facts = load_facts()
    market_key = "regime_fall"

    n = len(prices)
    print(f"Loaded {n} price observations")
    print(f"Loaded {len(facts)} facts from latest briefing")
    print(f"Warmup: {WARMUP} obs, horizon: {HORIZON_STEPS} steps")
    print(f"Will produce {n - WARMUP - HORIZON_STEPS} backtest cycles")
    print()

    results = []
    agents = ["momentum", "historian", "game_theorist", "quant"]

    for i in range(WARMUP, n - HORIZON_STEPS):
        cycle_num = i - WARMUP
        prices_so_far = prices.iloc[:i + 1].copy()
        current_ts = prices["timestamp"].iloc[i]
        actual_price = prices[market_key].iloc[i + HORIZON_STEPS]
        current_price = prices[market_key].iloc[i]

        now_utc = datetime.fromtimestamp(current_ts, tz=timezone.utc)

        market_data = build_market_data(prices_so_far, market_key)

        # Run each agent
        for agent_name in agents:
            try:
                if agent_name == "momentum":
                    result = momentum_forecast(market_key, market_data, facts, now_utc)
                elif agent_name == "historian":
                    result = historian_forecast(market_key, market_data, facts, now_utc)
                elif agent_name == "game_theorist":
                    result = gt_forecast(market_key, market_data, facts)
                elif agent_name == "quant":
                    result = quant_forecast(market_key, market_data, facts)

                prediction = result["prediction"]
                squared_error = (prediction - actual_price) ** 2

                results.append({
                    "cycle": cycle_num,
                    "timestamp": current_ts,
                    "agent": agent_name,
                    "current_price": round(current_price, 6),
                    "prediction": round(prediction, 6),
                    "actual": round(actual_price, 6),
                    "squared_error": round(squared_error, 8),
                    "error": round(prediction - actual_price, 6),
                })
            except Exception as e:
                print(f"  WARN: {agent_name} failed at cycle {cycle_num}: {e}")

        # Progress
        if cycle_num % 50 == 0:
            print(f"  Cycle {cycle_num}/{n - WARMUP - HORIZON_STEPS}...")

    # Also compute naive baseline (predict current price = no change)
    for i in range(WARMUP, n - HORIZON_STEPS):
        cycle_num = i - WARMUP
        current_price = prices[market_key].iloc[i]
        actual_price = prices[market_key].iloc[i + HORIZON_STEPS]
        squared_error = (current_price - actual_price) ** 2

        results.append({
            "cycle": cycle_num,
            "timestamp": prices["timestamp"].iloc[i],
            "agent": "naive_baseline",
            "current_price": round(current_price, 6),
            "prediction": round(current_price, 6),
            "actual": round(actual_price, 6),
            "squared_error": round(squared_error, 8),
            "error": round(current_price - actual_price, 6),
        })

    # Save
    df = pd.DataFrame(results)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved {len(df)} rows to {OUTPUT_CSV}")

    # Summary
    print("\n=== Backtest Summary ===")
    for agent in agents + ["naive_baseline"]:
        agent_df = df[df["agent"] == agent]
        mse = agent_df["squared_error"].mean()
        rmse = math.sqrt(mse)
        mae = agent_df["error"].abs().mean()
        print(f"  {agent:20s}  MSE={mse:.6f}  RMSE={rmse:.4f}  MAE={mae:.4f}")


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    run_backtest()
