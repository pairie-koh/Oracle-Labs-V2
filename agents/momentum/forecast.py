"""
Oracle Lab — Momentum Agent
Price dynamics + news flow velocity.
Deterministic forecasting — no LLM at prediction time.
"""

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
RESET = "\033[0m"
LIVE_DELAY = 0.03

# ── Tunable Parameters ───────────────────────────────────────────────────────
# The iteration cycle modifies these based on performance.

METHODOLOGY_VERSION = "1.32.0"

MOMENTUM_WEIGHT = 0.7
REVERSION_WEIGHT = 0.4
NEWS_THRESHOLD = 5       # midpoint of sigmoid blend
SIGMOID_STEEPNESS = 0.5  # how sharp the transition from reversion to momentum
LOOKBACK_HOURS = 24
DECAY_HALF_LIFE_HOURS = 12  # recent facts weighted more heavily

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

# ── Forecast Logic ───────────────────────────────────────────────────────────

def compute_news_intensity(facts, market_key, now_utc, live=False):
    """Weighted count of facts with exponential temporal decay."""
    intensity = 0.0
    decay_lambda = math.log(2) / DECAY_HALF_LIFE_HOURS
    market_facts = [f for f in facts if f.get("market") == market_key]

    if live:
        print(f"\n{BOLD}▸ Computing news intensity {DIM}(decay half-life: {DECAY_HALF_LIFE_HOURS}h){RESET}")
        time.sleep(LIVE_DELAY * 3)

    for fact in market_facts:
        source_cat = fact.get("source_category", "")
        weight = SOURCE_WEIGHTS.get(source_cat, 0.5)

        # Confidence multiplier
        conf = fact.get("confidence", "medium")
        conf_mult = {"high": 1.0, "medium": 0.6, "low": 0.3}.get(conf, 0.5)

        # Temporal decay based on fact age
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

        contribution = weight * conf_mult * decay
        intensity += contribution

        if live:
            claim = fact.get("claim", "")[:70]
            print(f"  {DIM}░{RESET} {DIM}\"{claim}...\" [{source_cat}/{conf}]{RESET}")
            print(f"    weight={CYAN}{weight:.2f}{RESET} × decay={CYAN}{decay:.2f}{RESET} "
                  f"{DIM}(age: {age_hours:.0f}h){RESET} → {YELLOW}{contribution:.3f}{RESET}")
            time.sleep(LIVE_DELAY)

    if live:
        print(f"  {BOLD}Decay-adjusted intensity: {GREEN}{intensity:.3f}{RESET}")
        time.sleep(LIVE_DELAY * 2)

    return intensity


def forecast_market(market_key, market_data, facts, now_utc, horizon_hours=4, live=False):
    """Generate a single market forecast for a specific horizon.

    Args:
        horizon_hours: Forecast horizon in hours (24 or 168)
    """
    current = market_data["current"]
    change_4h = market_data.get("change_4h", 0.0)
    change_24h = market_data.get("change_24h", 0.0)

    # Scale coefficients by horizon_hours / 4 (linear scaling from old 4h baseline)
    horizon_scale = horizon_hours / 4.0
    scaled_momentum_weight = MOMENTUM_WEIGHT * horizon_scale
    scaled_reversion_weight = REVERSION_WEIGHT * horizon_scale

    intensity = compute_news_intensity(facts, market_key, now_utc, live=live)

    # Standard momentum signal: blend short-term and normalized long-term
    momentum_signal = 0.5 * change_4h + 0.5 * (change_24h / 6.0)

    if live:
        print(f"\n{BOLD}▸ Momentum signal{RESET}")
        print(f"  change_4h:  {CYAN}{change_4h:+.3f}{RESET}")
        print(f"  change_24h: {CYAN}{change_24h:+.3f}{RESET}")
        print(f"  signal = 0.5 × {change_4h:.3f} + 0.5 × ({change_24h:.3f}/6) = "
              f"{GREEN}{momentum_signal:+.4f}{RESET}")
        time.sleep(LIVE_DELAY * 3)

    # Sigmoid blend: smooth transition from reversion to momentum mode
    # CORRECTED: high news intensity favors momentum, low intensity favors reversion
    blend_weight = 1.0 / (1.0 + math.exp(-SIGMOID_STEEPNESS * (intensity - NEWS_THRESHOLD)))

    if live:
        print(f"\n{BOLD}▸ Sigmoid blend (CORRECTED){RESET}")
        print(f"  intensity={CYAN}{intensity:.3f}{RESET} vs threshold={CYAN}{NEWS_THRESHOLD}{RESET}")
        print(f"  blend = 1/(1+exp(-{SIGMOID_STEEPNESS}×({intensity:.3f}-{NEWS_THRESHOLD}))) = "
              f"{GREEN}{blend_weight:.4f}{RESET}")
        mode = "MOMENTUM (high news flow)" if blend_weight > 0.5 else "REVERSION (low news flow)"
        print(f"  Mode: {BOLD}{mode}{RESET}")
        time.sleep(LIVE_DELAY * 3)

    # Momentum component: extrapolate recent price dynamics (scaled by horizon)
    momentum_pred = current + momentum_signal * scaled_momentum_weight

    # Reversion component: slight pull toward 0.5 (scaled by horizon)
    reversion_pull = (0.5 - current) * scaled_reversion_weight * 0.05
    reversion_pred = current + reversion_pull

    if live:
        print(f"\n{BOLD}▸ Blending{RESET}")
        print(f"  momentum_pred:  {CYAN}{momentum_pred:.4f}{RESET}")
        print(f"  reversion_pred: {CYAN}{reversion_pred:.4f}{RESET}")
        time.sleep(LIVE_DELAY * 2)

    # Blend based on news intensity
    prediction = blend_weight * momentum_pred + (1.0 - blend_weight) * reversion_pred

    # Clamp to valid probability range
    prediction = max(0.01, min(0.99, prediction))

    mode_str = "momentum" if blend_weight > 0.5 else "reversion"

    if live:
        delta = prediction - current
        delta_pp = delta * 100
        sign = "+" if delta >= 0 else ""
        horizon_label = f"{horizon_hours}h" if horizon_hours < 168 else f"{horizon_hours // 24}d"
        print(f"\n┌─────────────────────────────────────────────────┐")
        print(f"│ {BOLD}{market_key:<48s}{RESET}│")
        print(f"│ {current:.4f} ──→ {GREEN}{prediction:.4f}{RESET}  "
              f"({sign}{delta_pp:.1f}pp) @ {horizon_label}{' ' * max(0, 19 - len(f'{sign}{delta_pp:.1f}pp) @ {horizon_label}'))}│")
        print(f"│ mode: {mode_str} | blend: {blend_weight:.2f}"
              f"{' ' * max(0, 31 - len(f'mode: {mode_str} | blend: {blend_weight:.2f}'))}│")
        print(f"└─────────────────────────────────────────────────┘")

    return {
        "prediction": round(prediction, 6),
        "current": current,
        "change_4h": change_4h,
        "change_24h": change_24h,
        "news_intensity_raw": round(intensity, 3),
        "decay_adjusted_intensity": round(intensity, 3),
        "blend_weight": round(blend_weight, 4),
        "momentum_signal": round(momentum_signal, 6),
        "mode": mode_str,
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
        print(f"┌─ {BOLD}MOMENTUM v{METHODOLOGY_VERSION}{RESET} ──────────────────────────────────┐")
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
        "agent": "momentum",
        "timestamp": timestamp,
        "predictions": predictions,
        "methodology_version": METHODOLOGY_VERSION,
        "source_weights": SOURCE_WEIGHTS,
        "parameters": {
            "momentum_weight": MOMENTUM_WEIGHT,
            "reversion_weight": REVERSION_WEIGHT,
            "news_threshold": NEWS_THRESHOLD,
            "sigmoid_steepness": SIGMOID_STEEPNESS,
            "lookbook_hours": LOOKBACK_HOURS,
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

    # Print summary (only in normal mode; live mode already printed everything)
    if not live:
        print(f"[momentum v{METHODOLOGY_VERSION}] {timestamp}")
        for mk, horizons in predictions.items():
            for hz_label, pred in horizons.items():
                print(f"  {mk} @ {hz_label}: {pred['current']:.4f} -> {pred['prediction']:.4f} "
                      f"({pred['mode']}, intensity={pred['decay_adjusted_intensity']:.1f}, "
                      f"blend={pred['blend_weight']:.2f}, momentum_sig={pred['momentum_signal']:.4f})")

    return forecast


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 agents/momentum/forecast.py <briefing_path> [--live]")
        sys.exit(1)
    live_mode = "--live" in sys.argv
    briefing_arg = [a for a in sys.argv[1:] if a != "--live"][0]
    make_forecasts(briefing_arg, live=live_mode)
