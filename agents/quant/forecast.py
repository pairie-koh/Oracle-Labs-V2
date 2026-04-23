"""
Oracle Lab — Quant Agent
Statistical models on price + newswire features.
Deterministic forecasting — no LLM at prediction time.
Uses pandas/numpy for price series operations.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# ── ANSI codes for --live mode ──────────────────────────────────────────────
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"
LIVE_DELAY = 0.03

# Add project root to path so we can import constants
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from constants import MARKETS, PRICE_CSV, FORECAST_HORIZONS

# ── Tunable Parameters ───────────────────────────────────────────────────────

METHODOLOGY_VERSION = "1.31.0"

MOMENTUM_LOOKBACK = 6       # number of recent price points for momentum (linear slope)
REVERSION_LOOKBACK = 24     # number of recent price points for long-term mean
BASE_MOMENTUM_BLEND = 0.2   # reduced from 0.5: favor mean reversion in falling regime
NEWS_FEATURE_WEIGHT = 0.0   # zeroed: news was anti-predictive (escalation bias in stable market)

SOURCE_WEIGHTS = {
    "wire_service": 1.0,
    "us_prestige": 0.9,
    "uk_prestige": 0.85,
    "regional_specialist": 0.8,
    "government_official": 1.0,
    "think_tank": 0.7,
    "osint": 0.6,
    "social_media": 0.3,
    "market_commentary": 0.4,
}

CONFIDENCE_WEIGHTS = {"high": 1.0, "medium": 0.6, "low": 0.3}

# ── Forecast Logic ───────────────────────────────────────────────────────────

def load_price_series(market_key):
    """Load price history as a pandas Series."""
    if not os.path.exists(PRICE_CSV):
        return pd.Series(dtype=float)

    df = pd.read_csv(PRICE_CSV)
    if market_key not in df.columns:
        return pd.Series(dtype=float)

    series = df[["timestamp", market_key]].dropna()
    series = series.set_index("timestamp")[market_key].astype(float)
    series = series.sort_index()
    return series


def compute_momentum(series, lookback):
    """Compute linear slope of recent prices — more stable than EWMA."""
    if len(series) < 2:
        return series.iloc[-1] if len(series) > 0 else 0.5
    
    recent = series.tail(lookback)
    if len(recent) < 2:
        return recent.iloc[-1]
    
    x = np.arange(len(recent))
    y = recent.values
    slope, intercept = np.polyfit(x, y, 1)
    # Project to next point
    next_x = len(recent)
    return slope * next_x + intercept


def compute_volatility(series, lookback):
    """Compute rolling volatility (std of returns) and median historical vol."""
    if len(series) < 3:
        return 0.01, 0.01  # defaults when insufficient data

    returns = series.pct_change().dropna()
    if len(returns) < 2:
        return 0.01, 0.01

    # Recent volatility
    recent_returns = returns.tail(lookback)
    vol = recent_returns.std() if len(recent_returns) > 1 else 0.01

    # Median volatility from full history
    # Rolling std with same window, then take median
    if len(returns) >= lookback:
        rolling_vol = returns.rolling(lookback).std().dropna()
        median_vol = rolling_vol.median() if len(rolling_vol) > 0 else vol
    else:
        median_vol = vol

    # Floor at small positive value to avoid division issues
    vol = max(vol, 0.001)
    median_vol = max(median_vol, 0.001)

    return vol, median_vol


def compute_long_term_mean(series, lookback):
    """Compute mean of last N price points."""
    if len(series) == 0:
        return 0.5
    recent = series.tail(lookback)
    return recent.mean()


def compute_news_feature(facts, market_key, live=False):
    """Simple news feature: weighted sum of facts, positive = escalation."""
    escalation_cats = {"military_pressure", "economic_collapse", "internal_stability"}
    deescalation_cats = {"diplomatic_signals", "international_response"}

    score = 0.0
    market_facts = [f for f in facts if f.get("market") == market_key]

    if live:
        print(f"\n{BOLD}▸ Computing news feature vector{RESET}")
        time.sleep(LIVE_DELAY * 2)

    for fact in market_facts:
        cat = fact.get("indicator_category", "")
        src = fact.get("source_category", "")
        conf = fact.get("confidence", "medium")

        weight = SOURCE_WEIGHTS.get(src, 0.5) * CONFIDENCE_WEIGHTS.get(conf, 0.5)

        if cat in escalation_cats:
            score += weight
            direction = "+ESC"
            color = YELLOW
        elif cat in deescalation_cats:
            score -= weight
            direction = "-ESC"
            color = CYAN
        else:
            direction = "skip"
            color = DIM

        if live:
            claim = fact.get("claim", "")[:55]
            if direction != "skip":
                print(f"  {DIM}░{RESET} {DIM}\"{claim}...\"{RESET}")
                print(f"    [{color}{direction}{RESET}] {src}/{conf} → w={CYAN}{weight:.2f}{RESET}")
            time.sleep(LIVE_DELAY)

    if live:
        print(f"  {BOLD}News feature score: {GREEN}{score:+.3f}{RESET}")
        time.sleep(LIVE_DELAY * 2)

    return score


def forecast_market(market_key, market_data, facts, horizon_hours=4, live=False):
    """Generate a single market forecast using statistical methods for a specific horizon.

    Args:
        horizon_hours: Forecast horizon in hours (24 or 168)
    """
    current = market_data["current"]

    # Scale coefficients by horizon_hours / 4 (linear scaling from old 4h baseline)
    horizon_scale = horizon_hours / 4.0

    # Load price series
    series = load_price_series(market_key)

    if live:
        print(f"\n{BOLD}▸ Loading price series{RESET}")
        print(f"  Observations: {CYAN}{len(series)}{RESET}")
        if len(series) > 0:
            print(f"  Range: {CYAN}{series.iloc[0]:.4f}{RESET} → {CYAN}{series.iloc[-1]:.4f}{RESET}")
        time.sleep(LIVE_DELAY * 3)

    # Linear regression momentum (more stable than EWMA)
    momentum_projection = compute_momentum(series, MOMENTUM_LOOKBACK)

    if live:
        print(f"\n{BOLD}▸ Linear momentum {DIM}(lookback={MOMENTUM_LOOKBACK}){RESET}")
        print(f"  Projected:  {GREEN}{momentum_projection:.6f}{RESET}")
        print(f"  Current:    {CYAN}{current:.6f}{RESET}")
        diff = momentum_projection - current
        print(f"  Momentum:   {YELLOW}{diff:+.6f}{RESET}")
        time.sleep(LIVE_DELAY * 3)

    # Long-term mean for reversion target
    long_mean = compute_long_term_mean(series, REVERSION_LOOKBACK)

    if live:
        print(f"\n{BOLD}▸ Long-term mean {DIM}(lookback={REVERSION_LOOKBACK}){RESET}")
        print(f"  Mean: {GREEN}{long_mean:.6f}{RESET}")
        time.sleep(LIVE_DELAY * 2)

    # Rolling volatility (for info only now)
    vol, median_vol = compute_volatility(series, REVERSION_LOOKBACK)

    if live:
        print(f"\n{BOLD}▸ Volatility metrics{RESET}")
        print(f"  Recent vol:  {CYAN}{vol:.6f}{RESET}")
        print(f"  Median vol:  {CYAN}{median_vol:.6f}{RESET}")
        ratio = vol / median_vol if median_vol > 0 else 0
        regime = "HIGH" if ratio > 1.5 else "LOW" if ratio < 0.7 else "NORMAL"
        color = RED if ratio > 1.5 else GREEN if ratio < 0.7 else YELLOW
        print(f"  Vol ratio:   {color}{ratio:.2f}× ({regime}){RESET}")
        time.sleep(LIVE_DELAY * 3)

    # Fixed blend (no longer adaptive)
    fixed_blend = BASE_MOMENTUM_BLEND

    # Momentum forecast: use projected momentum value with scaled coefficient (increased from 0.0002 to 0.001)
    momentum_coefficient = 0.001 * horizon_scale  # increased for bolder directional predictions
    momentum_forecast = current + (momentum_projection - current) * momentum_coefficient

    # Reversion forecast: pull toward long-term mean (scaled by horizon)
    reversion_coefficient = 0.000015 * horizon_scale
    reversion_forecast = current + (long_mean - current) * reversion_coefficient

    if live:
        print(f"\n{BOLD}▸ Fixed blend{RESET}")
        print(f"  Blend weight:       {GREEN}{fixed_blend:.4f}{RESET} "
              f"{DIM}(1.0=momentum, 0.0=reversion){RESET}")
        print(f"  Momentum forecast:  {CYAN}{momentum_forecast:.6f}{RESET}")
        print(f"  Reversion forecast: {CYAN}{reversion_forecast:.6f}{RESET}")
        time.sleep(LIVE_DELAY * 3)

    # Blend
    blended = fixed_blend * momentum_forecast + (1.0 - fixed_blend) * reversion_forecast

    # News adjustment scaled by inverse volatility
    news_score = compute_news_feature(facts, market_key, live=live)
    effective_news_weight = NEWS_FEATURE_WEIGHT / max(vol / median_vol, 0.5)
    news_adj = news_score * effective_news_weight

    if live:
        print(f"\n{BOLD}▸ News feature adjustment{RESET}")
        print(f"  Raw news score:  {CYAN}{news_score:+.3f}{RESET}")
        print(f"  Effective weight: {CYAN}{effective_news_weight:.4f}{RESET}")
        print(f"  News adjustment:  {YELLOW}{news_adj:+.6f}{RESET}")
        time.sleep(LIVE_DELAY * 3)

    prediction = blended + news_adj

    # Clamp
    prediction = max(0.01, min(0.99, prediction))

    if live:
        delta = prediction - current
        delta_pp = delta * 100
        sign = "+" if delta >= 0 else ""
        horizon_label = f"{horizon_hours}h" if horizon_hours < 168 else f"{horizon_hours // 24}d"
        print(f"\n┌─────────────────────────────────────────────────┐")
        print(f"│ {BOLD}{market_key:<48s}{RESET}│")
        print(f"│ {current:.4f} ──→ {GREEN}{prediction:.4f}{RESET}  "
              f"({sign}{delta_pp:.1f}pp) @ {horizon_label}{' ' * max(0, 19 - len(f'{sign}{delta_pp:.1f}pp) @ {horizon_label}'))}│")
        print(f"│ blend: {fixed_blend:.2f} | vol: {vol:.4f} | n={len(series)}"
              f"{' ' * max(0, 24 - len(f'blend: {fixed_blend:.2f} | vol: {vol:.4f} | n={len(series)}'))}│")
        print(f"└─────────────────────────────────────────────────┘")

    return {
        "prediction": round(prediction, 6),
        "current": current,
        "momentum_projection": round(momentum_projection, 6),
        "long_term_mean": round(long_term_mean, 6),
        "momentum_forecast": round(momentum_forecast, 6),
        "reversion_forecast": round(reversion_forecast, 6),
        "blended": round(blended, 6),
        "volatility": round(vol, 6),
        "median_vol": round(median_vol, 6),
        "fixed_blend": round(fixed_blend, 4),
        "news_adjustment": round(news_adj, 6),
        "series_length": len(series),
    }


def make_forecasts(briefing_path, live=False):
    """Standard agent interface. Returns forecast dict with dual horizon predictions."""
    with open(briefing_path, "r") as f:
        briefing = json.load(f)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    facts = briefing.get("fresh_facts", [])
    market_prices = briefing.get("market_prices", {})

    if live:
        n_facts = len(facts)
        n_markets = len(market_prices)
        print(f"┌─ {BOLD}QUANT v{METHODOLOGY_VERSION}{RESET} ──────────────────────────────────────┐")
        print(f"\n{BOLD}▸ Loading briefing...{RESET} {CYAN}{n_facts}{RESET} facts, "
              f"{CYAN}{n_markets}{RESET} market{'s' if n_markets != 1 else ''}")
        time.sleep(LIVE_DELAY * 5)

    predictions = {}
    for market_key, market_data in market_prices.items():
        # Generate predictions for both horizons
        predictions[market_key] = {}
        for horizon_label, horizon_hours in FORECAST_HORIZONS.items():
            result = forecast_market(market_key, market_data, facts, horizon_hours=horizon_hours, live=live)
            predictions[market_key][horizon_label] = result

    forecast = {
        "agent": "quant",
        "timestamp": timestamp,
        "predictions": predictions,
        "methodology_version": METHODOLOGY_VERSION,
        "source_weights": SOURCE_WEIGHTS,
        "parameters": {
            "momentum_lookback": MOMENTUM_LOOKBACK,
            "reversion_lookback": REVERSION_LOOKBACK,
            "base_momentum_blend": BASE_MOMENTUM_BLEND,
            "news_feature_weight": NEWS_FEATURE_WEIGHT,
        },
    }

    # Save to log
    log_dir = os.path.join(os.path.dirname(__file__), "log")
    os.makedirs(log_dir, exist_ok=True)
    log_ts = timestamp.replace(":", "").replace("-", "")
    log_path = os.path.join(log_dir, f"{log_ts}.json")
    with open(log_path, "w") as f:
        json.dump(forecast, f, indent=2)

    if not live:
        print(f"[quant v{METHODOLOGY_VERSION}] {timestamp}")
        for mk, horizons in predictions.items():
            for hz_label, pred in horizons.items():
                print(f"  {mk} @ {hz_label}: {pred['current']:.4f} -> {pred['prediction']:.4f} "
                      f"(momentum={pred['momentum_projection']:.4f}, vol={pred['volatility']:.4f}, "
                      f"med_vol={pred['median_vol']:.4f}, blend={pred['fixed_blend']:.2f}, "
                      f"n={pred['series_length']})")

    return forecast


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 agents/quant/forecast.py <briefing_path> [--live]")
        sys.exit(1)
    live_mode = "--live" in sys.argv
    briefing_arg = [a for a in sys.argv[1:] if a != "--live"][0]
    make_forecasts(briefing_arg, live=live_mode)
