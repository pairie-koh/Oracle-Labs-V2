"""
Oracle Lab — Historian Agent
Historical base rates + mean reversion.
Deterministic forecasting — no LLM at prediction time.
"""

import csv
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

# Add project root to path to import constants
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from constants import FORECAST_HORIZONS

# ── ANSI codes for --live mode ──────────────────────────────────────────────
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RESET = "\033[0m"
LIVE_DELAY = 0.03

# ── Tunable Parameters ───────────────────────────────────────────────────────

METHODOLOGY_VERSION = "1.20.0"

# Fallback base rates if price history is unavailable
DEFAULT_BASE_RATES = {
    "regime_fall": 0.15,
}

ADAPTIVE_LOOKBACK_DAYS = 7   # days of price history for adaptive base rate
REVERSION_RATE = 0.025       # how strongly to pull toward base rate per cycle
NEWS_SENSITIVITY = 0.08      # scaling factor inside tanh
MAX_NEWS_SHIFT = 0.015        # max absolute shift from news (1.5pp)
DECAY_HALF_LIFE_HOURS = 18    # historian cares about slower signals

# Categories that indicate escalation vs de-escalation (per market)
ESCALATION_CATEGORIES = {
    "regime_fall": ["military_pressure", "economic_collapse", "internal_stability"],
}
DEESCALATION_CATEGORIES = {
    "regime_fall": ["diplomatic_signals", "international_response"],
}

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

def load_adaptive_base_rate(market_key, live=False):
    """Compute adaptive base rate from median of last N days of price history."""
    price_csv = os.path.join("price_history", "prices.csv")
    if not os.path.exists(price_csv):
        if live:
            print(f"  {DIM}No price history found, using default base rate{RESET}")
        return DEFAULT_BASE_RATES.get(market_key, 0.5)

    prices = []
    try:
        with open(price_csv, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if market_key in row and row[market_key]:
                    try:
                        ts = float(row["timestamp"])
                        price = float(row[market_key])
                        prices.append((ts, price))
                    except (ValueError, KeyError):
                        continue
    except Exception:
        return DEFAULT_BASE_RATES.get(market_key, 0.5)

    if not prices:
        return DEFAULT_BASE_RATES.get(market_key, 0.5)

    # Sort by timestamp, take last N days
    prices.sort(key=lambda x: x[0])
    latest_ts = prices[-1][0]
    cutoff = latest_ts - (ADAPTIVE_LOOKBACK_DAYS * 86400)
    recent = [p for ts, p in prices if ts >= cutoff]

    if not recent:
        return DEFAULT_BASE_RATES.get(market_key, 0.5)

    # Median
    recent.sort()
    n = len(recent)
    if n % 2 == 0:
        base = (recent[n // 2 - 1] + recent[n // 2]) / 2.0
    else:
        base = recent[n // 2]

    if live:
        print(f"  {DIM}Price history:{RESET} {CYAN}{len(prices)}{RESET} total observations")
        print(f"  {DIM}Lookback window:{RESET} {CYAN}{ADAPTIVE_LOOKBACK_DAYS}{RESET} days → "
              f"{CYAN}{n}{RESET} recent prices")
        print(f"  {BOLD}Adaptive base rate (median): {GREEN}{base:.4f}{RESET}")
        time.sleep(LIVE_DELAY * 3)

    return base


def compute_net_escalation(facts, market_key, now_utc, live=False):
    """Compute net escalation signal with temporal decay."""
    escalation_cats = set(ESCALATION_CATEGORIES.get(market_key, []))
    deescalation_cats = set(DEESCALATION_CATEGORIES.get(market_key, []))
    decay_lambda = math.log(2) / DECAY_HALF_LIFE_HOURS

    escalation_score = 0.0
    deescalation_score = 0.0

    market_facts = [f for f in facts if f.get("market") == market_key]

    if live:
        print(f"\n{BOLD}▸ Scanning historical pattern indicators {DIM}(decay: {DECAY_HALF_LIFE_HOURS}h half-life){RESET}")
        time.sleep(LIVE_DELAY * 3)

    for fact in market_facts:
        cat = fact.get("indicator_category", "")
        src = fact.get("source_category", "")
        conf = fact.get("confidence", "medium")

        weight = SOURCE_WEIGHTS.get(src, 0.5) * CONFIDENCE_WEIGHTS.get(conf, 0.5)

        # Temporal decay
        decay = 1.0
        age_hours = 0.0
        time_str = fact.get("time", "")
        if time_str:
            try:
                fact_time = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                age_hours = max(0, (now_utc - fact_time).total_seconds() / 3600)
                decay = math.exp(-decay_lambda * age_hours)
            except (ValueError, TypeError):
                pass

        weighted = weight * decay

        if cat in escalation_cats:
            escalation_score += weighted
            direction = "ESC"
            color = YELLOW
        elif cat in deescalation_cats:
            deescalation_score += weighted
            direction = "DE-ESC"
            color = CYAN
        else:
            direction = "NEUTRAL"
            color = DIM

        if live:
            claim = fact.get("claim", "")[:65]
            print(f"  {DIM}░{RESET} {DIM}\"{claim}...\"{RESET}")
            print(f"    [{color}{direction}{RESET}] {cat} | "
                  f"w={CYAN}{weight:.2f}{RESET} × d={CYAN}{decay:.2f}{RESET} "
                  f"{DIM}({age_hours:.0f}h ago){RESET} → {YELLOW}{weighted:.3f}{RESET}")
            time.sleep(LIVE_DELAY)

    net = escalation_score - deescalation_score

    if live:
        print(f"  {BOLD}Escalation: {YELLOW}{escalation_score:.3f}{RESET}  "
              f"{BOLD}De-escalation: {CYAN}{deescalation_score:.3f}{RESET}")
        print(f"  {BOLD}Net signal: {GREEN}{net:+.3f}{RESET}")
        time.sleep(LIVE_DELAY * 2)

    return net


def forecast_market(market_key, market_data, facts, now_utc, horizon_hours=4, live=False):
    """Generate a single market forecast using historical base rates for a specific horizon.

    Args:
        horizon_hours: Forecast horizon in hours (24 or 168)
    """
    current = market_data["current"]

    # Scale coefficients by horizon_hours / 4 (linear scaling from old 4h baseline)
    horizon_scale = horizon_hours / 4.0
    scaled_reversion_rate = REVERSION_RATE * horizon_scale
    scaled_max_news_shift = MAX_NEWS_SHIFT * horizon_scale

    if live:
        print(f"\n{BOLD}▸ Loading historical base rate{RESET}")
        time.sleep(LIVE_DELAY * 2)

    # Adaptive base rate from price history
    base_rate = load_adaptive_base_rate(market_key, live=live)

    # Mean reversion toward adaptive base rate (scaled by horizon)
    reversion_pull = (base_rate - current) * scaled_reversion_rate

    if live:
        print(f"\n{BOLD}▸ Mean reversion calculation{RESET}")
        print(f"  Current price: {CYAN}{current:.4f}{RESET}")
        print(f"  Base rate:     {CYAN}{base_rate:.4f}{RESET}")
        print(f"  Reversion = ({base_rate:.4f} - {current:.4f}) × {scaled_reversion_rate} = "
              f"{GREEN}{reversion_pull:+.6f}{RESET}")
        time.sleep(LIVE_DELAY * 3)

    # News-driven shift with tanh cap (scaled by horizon)
    raw_signal = compute_net_escalation(facts, market_key, now_utc, live=live)
    capped_shift = scaled_max_news_shift * math.tanh(raw_signal * NEWS_SENSITIVITY)

    if live:
        print(f"\n{BOLD}▸ News-driven shift (tanh cap: ±{scaled_max_news_shift:.0%}){RESET}")
        print(f"  raw_signal = {CYAN}{raw_signal:+.3f}{RESET}")
        print(f"  tanh({raw_signal:.3f} × {NEWS_SENSITIVITY}) = {CYAN}{math.tanh(raw_signal * NEWS_SENSITIVITY):.4f}{RESET}")
        print(f"  capped_shift = {GREEN}{capped_shift:+.6f}{RESET}")
        time.sleep(LIVE_DELAY * 3)

    prediction = current + reversion_pull + capped_shift

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
        print(f"│ base: {base_rate:.3f} | reversion: {reversion_pull:+.4f}"
              f"{' ' * max(0, 22 - len(f'base: {base_rate:.3f} | reversion: {reversion_pull:+.4f}'))}│")
        print(f"└─────────────────────────────────────────────────┘")

    return {
        "prediction": round(prediction, 6),
        "current": current,
        "adaptive_base_rate": round(base_rate, 4),
        "reversion_pull": round(reversion_pull, 6),
        "raw_signal": round(raw_signal, 3),
        "capped_shift": round(capped_shift, 6),
    }


def make_forecasts(briefing_path, live=False):
    """Standard agent interface. Returns forecast dict with dual horizon predictions."""
    with open(briefing_path, "r") as f:
        briefing = json.load(f)

    now_utc = datetime.now(timezone.utc)
    timestamp = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    facts = briefing.get("fresh_facts", [])
    market_prices = briefing.get("market_prices", {})

    if live:
        n_facts = len(facts)
        n_markets = len(market_prices)
        print(f"┌─ {BOLD}HISTORIAN v{METHODOLOGY_VERSION}{RESET} ──────────────────────────────────┐")
        print(f"\n{BOLD}▸ Loading briefing...{RESET} {CYAN}{n_facts}{RESET} facts, "
              f"{CYAN}{n_markets}{RESET} market{'s' if n_markets != 1 else ''}")
        time.sleep(LIVE_DELAY * 5)

    predictions = {}
    for market_key, market_data in market_prices.items():
        # Generate predictions for both horizons
        predictions[market_key] = {}
        for horizon_label, horizon_hours in FORECAST_HORIZONS.items():
            result = forecast_market(market_key, market_data, facts, now_utc, horizon_hours=horizon_hours, live=live)
            predictions[market_key][horizon_label] = result

    forecast = {
        "agent": "historian",
        "timestamp": timestamp,
        "predictions": predictions,
        "methodology_version": METHODOLOGY_VERSION,
        "source_weights": SOURCE_WEIGHTS,
        "parameters": {
            "default_base_rates": DEFAULT_BASE_RATES,
            "adaptive_lookback_days": ADAPTIVE_LOOKBACK_DAYS,
            "reversion_rate": REVERSION_RATE,
            "news_sensitivity": NEWS_SENSITIVITY,
            "max_news_shift": MAX_NEWS_SHIFT,
            "decay_half_life_hours": DECAY_HALF_LIFE_HOURS,
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
        print(f"[historian v{METHODOLOGY_VERSION}] {timestamp}")
        for mk, horizons in predictions.items():
            for hz_label, pred in horizons.items():
                print(f"  {mk} @ {hz_label}: {pred['current']:.4f} -> {pred['prediction']:.4f} "
                      f"(base={pred['adaptive_base_rate']:.3f}, reversion={pred['reversion_pull']:+.6f}, "
                      f"raw_signal={pred['raw_signal']:.2f}, capped_shift={pred['capped_shift']:+.6f})")

    return forecast


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 agents/historian/forecast.py <briefing_path> [--live]")
        sys.exit(1)
    live_mode = "--live" in sys.argv
    briefing_arg = [a for a in sys.argv[1:] if a != "--live"][0]
    make_forecasts(briefing_arg, live=live_mode)
