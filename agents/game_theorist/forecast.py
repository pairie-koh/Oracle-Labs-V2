"""
Oracle Lab — Game Theorist Agent
Actor incentives + costly signaling.
Deterministic forecasting — no LLM at prediction time.
"""

import json
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
RED = "\033[31m"
MAGENTA = "\033[35m"
RESET = "\033[0m"
LIVE_DELAY = 0.03

# ── Tunable Parameters ───────────────────────────────────────────────────────

METHODOLOGY_VERSION = "1.28.0"

# Actor profiles: each source category has an escalation bias and credibility score
ACTORS = {
    "wire_service": {"escalation_bias": 0.0, "credibility": 0.9},
    "us_prestige": {"escalation_bias": 0.1, "credibility": 0.85},
    "uk_prestige": {"escalation_bias": 0.05, "credibility": 0.8},
    "regional_specialist": {"escalation_bias": -0.1, "credibility": 0.75},
    "government_official": {"escalation_bias": 0.15, "credibility": 1.0},
    "think_tank": {"escalation_bias": 0.0, "credibility": 0.7},
    "osint": {"escalation_bias": 0.2, "credibility": 0.6},
    "social_media": {"escalation_bias": 0.3, "credibility": 0.3},
    "market_commentary": {"escalation_bias": 0.0, "credibility": 0.4},
}

# Signal weights by confidence level
SIGNAL_WEIGHTS = {"high": 1.0, "medium": 0.5, "low": 0.2}

ESCALATION_SENSITIVITY = 0.002       # how much each unit of net signal moves the forecast
COSTLY_SIGNAL_BONUS = 1.2       # multiplier for signals against speaker's bias
CONSENSUS_HIGH_THRESHOLD = 0.8  # above this, scale sensitivity up
CONSENSUS_LOW_THRESHOLD = 0.6   # below this, scale sensitivity down
CONSENSUS_HIGH_SCALE = 1.5
CONSENSUS_LOW_SCALE = 0.7

# Escalatory vs de-escalatory indicator categories (per market)
ESCALATORY_CATEGORIES = {
    "regime_fall": ["military_pressure", "economic_collapse", "internal_stability"],
}
DEESCALATORY_CATEGORIES = {
    "regime_fall": ["diplomatic_signals", "international_response"],
}
# Neutral categories — direction determined by actor bias
NEUTRAL_CATEGORIES = {
    "regime_fall": ["succession_dynamics"],
}

SOURCE_WEIGHTS = {
    "wire_service": 0.9,
    "us_prestige": 0.85,
    "uk_prestige": 0.8,
    "regional_specialist": 0.75,
    "government_official": 1.0,
    "think_tank": 0.7,
    "osint": 0.6,
    "social_media": 0.3,
    "market_commentary": 0.4,
}

# ── Forecast Logic ───────────────────────────────────────────────────────────

def compute_signal_score(facts, market_key, live=False):
    """Score facts through the game theory lens: costly signals matter more."""
    escalatory = set(ESCALATORY_CATEGORIES.get(market_key, []))
    deescalatory = set(DEESCALATORY_CATEGORIES.get(market_key, []))
    neutral = set(NEUTRAL_CATEGORIES.get(market_key, []))

    net_signal = 0.0
    fact_count = 0
    escalatory_count = 0
    deescalatory_count = 0
    costly_signal_count = 0

    market_facts = [f for f in facts if f.get("market") == market_key]

    if live:
        print(f"\n{BOLD}▸ Evaluating actor signals{RESET}")
        time.sleep(LIVE_DELAY * 3)

    for fact in market_facts:
        cat = fact.get("indicator_category", "")
        src = fact.get("source_category", "")
        conf = fact.get("confidence", "medium")

        actor = ACTORS.get(src, {"escalation_bias": 0.0, "credibility": 0.5})
        signal_weight = SIGNAL_WEIGHTS.get(conf, 0.5)

        # Base signal score from confidence and credibility
        score = signal_weight * actor["credibility"]

        # Determine direction from category
        if cat in escalatory:
            direction = 1.0
            escalatory_count += 1
        elif cat in deescalatory:
            direction = -1.0
            deescalatory_count += 1
        elif cat in neutral:
            bias = actor["escalation_bias"]
            if bias > 0:
                direction = 1.0
                escalatory_count += 1
            elif bias < 0:
                direction = -1.0
                deescalatory_count += 1
            else:
                direction = 0.0
        else:
            direction = 0.0

        # Costly signal bonus: if direction opposes actor's bias, weight more
        is_costly = False
        if direction != 0.0:
            actor_bias_sign = 1.0 if actor["escalation_bias"] > 0 else (-1.0 if actor["escalation_bias"] < 0 else 0.0)
            if actor_bias_sign != 0.0 and direction != actor_bias_sign:
                score *= COSTLY_SIGNAL_BONUS
                costly_signal_count += 1
                is_costly = True

        # Bias is already captured in the costly-signal mechanism (a de-escalatory
        # signal from an escalation-biased source gets a credibility bonus). Adding
        # a separate bias_adjustment on top caused systematic upward drift and 0%
        # directional accuracy — removed.
        contribution = score * direction
        net_signal += contribution
        fact_count += 1

        if live:
            claim = fact.get("claim", "")[:60]
            dir_label = {1.0: "ESC", -1.0: "DE-ESC", 0.0: "—"}[direction]
            dir_color = {1.0: YELLOW, -1.0: CYAN, 0.0: DIM}[direction]
            costly_tag = f" {RED}★ COSTLY SIGNAL{RESET}" if is_costly else ""
            print(f"  {DIM}░{RESET} {DIM}\"{claim}...\"{RESET}")
            print(f"    actor: {MAGENTA}{src}{RESET} (bias={actor['escalation_bias']:+.1f}, "
                  f"cred={actor['credibility']:.1f}) "
                  f"[{dir_color}{dir_label}{RESET}]{costly_tag}")
            print(f"    score={CYAN}{score:.2f}{RESET} × dir={direction:+.0f} "
                  f"→ {YELLOW}{contribution:+.3f}{RESET}")
            time.sleep(LIVE_DELAY)

    if live:
        print(f"\n  {BOLD}Net signal: {GREEN}{net_signal:+.3f}{RESET}  "
              f"{DIM}({fact_count} facts, {escalatory_count} esc, "
              f"{deescalatory_count} de-esc, {costly_signal_count} costly){RESET}")
        time.sleep(LIVE_DELAY * 2)

    return net_signal, fact_count, escalatory_count, deescalatory_count, costly_signal_count


def compute_consensus_scale(escalatory_count, deescalatory_count):
    """Scale sensitivity based on directional consensus."""
    total_directional = escalatory_count + deescalatory_count
    if total_directional == 0:
        return 1.0

    # Ratio of dominant direction
    dominant = max(escalatory_count, deescalatory_count)
    ratio = dominant / total_directional

    if ratio >= CONSENSUS_HIGH_THRESHOLD:
        return CONSENSUS_HIGH_SCALE
    elif ratio < CONSENSUS_LOW_THRESHOLD:
        return CONSENSUS_LOW_SCALE
    else:
        return 1.0


def forecast_market(market_key, market_data, facts, horizon_hours=4, live=False):
    """Generate a single market forecast using game theory framework for a specific horizon.

    Args:
        horizon_hours: Forecast horizon in hours (24 or 168)
    """
    current = market_data["current"]

    # Scale coefficients by horizon_hours / 4 (linear scaling from old 4h baseline)
    horizon_scale = horizon_hours / 4.0
    scaled_escalation_sensitivity = ESCALATION_SENSITIVITY * horizon_scale

    net_signal, fact_count, esc_count, deesc_count, costly_count = compute_signal_score(facts, market_key, live=live)

    # Consensus-adjusted sensitivity (scaled by horizon)
    total_directional = esc_count + deesc_count
    consensus_ratio = max(esc_count, deesc_count) / total_directional if total_directional > 0 else 0.0
    consensus_scale = compute_consensus_scale(esc_count, deesc_count)
    effective_sensitivity = scaled_escalation_sensitivity * consensus_scale

    if live:
        print(f"\n{BOLD}▸ Consensus analysis{RESET}")
        print(f"  Escalatory:     {YELLOW}{esc_count}{RESET}")
        print(f"  De-escalatory:  {CYAN}{deesc_count}{RESET}")
        print(f"  Consensus ratio: {GREEN}{consensus_ratio:.3f}{RESET}")
        label = "HIGH" if consensus_ratio >= CONSENSUS_HIGH_THRESHOLD else \
                "LOW" if consensus_ratio < CONSENSUS_LOW_THRESHOLD else "MODERATE"
        print(f"  Consensus scale: {GREEN}{consensus_scale:.1f}×{RESET} ({label})")
        print(f"  Effective sensitivity: {CYAN}{effective_sensitivity:.4f}{RESET}")
        time.sleep(LIVE_DELAY * 3)

    shift = net_signal * effective_sensitivity

    prediction = current + shift

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
        print(f"│ signal: {net_signal:+.3f} | costly: {costly_count}"
              f"{' ' * max(0, 31 - len(f'signal: {net_signal:+.3f} | costly: {costly_count}'))}│")
        print(f"└─────────────────────────────────────────────────┘")

    return {
        "prediction": round(prediction, 6),
        "current": current,
        "net_signal": round(net_signal, 3),
        "signal_shift": round(shift, 6),
        "fact_count": fact_count,
        "escalatory_facts": esc_count,
        "deescalatory_facts": deesc_count,
        "consensus_ratio": round(consensus_ratio, 3),
        "consensus_scale": consensus_scale,
        "costly_signal_count": costly_count,
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
        print(f"┌─ {BOLD}GAME THEORIST v{METHODOLOGY_VERSION}{RESET} ───────────────────────────────┐")
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
        "agent": "game_theorist",
        "timestamp": timestamp,
        "predictions": predictions,
        "methodology_version": METHODOLOGY_VERSION,
        "source_weights": SOURCE_WEIGHTS,
        "parameters": {
            "actors": ACTORS,
            "signal_weights": SIGNAL_WEIGHTS,
            "escalation_sensitivity": ESCALATION_SENSITIVITY,
            "costly_signal_bonus": COSTLY_SIGNAL_BONUS,
            "consensus_high_threshold": CONSENSUS_HIGH_THRESHOLD,
            "consensus_low_threshold": CONSENSUS_LOW_THRESHOLD,
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
        print(f"[game_theorist v{METHODOLOGY_VERSION}] {timestamp}")
        for mk, horizons in predictions.items():
            for hz_label, pred in horizons.items():
                print(f"  {mk} @ {hz_label}: {pred['current']:.4f} -> {pred['prediction']:.4f} "
                      f"(signal={pred['net_signal']:.3f}, consensus={pred['consensus_ratio']:.2f}, "
                      f"costly={pred['costly_signal_count']}, esc={pred['escalatory_facts']}/"
                      f"deesc={pred['deescalatory_facts']})")

    return forecast


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 agents/game_theorist/forecast.py <briefing_path> [--live]")
        sys.exit(1)
    live_mode = "--live" in sys.argv
    briefing_arg = [a for a in sys.argv[1:] if a != "--live"][0]
    make_forecasts(briefing_arg, live=live_mode)
