"""
Oracle Lab — evaluate.py
Scoring engine: scores matured predictions against actual prices,
updates scorecards, and builds the leaderboard.
"""

import json
import os
import csv
import glob
import time
from datetime import datetime, timezone

from constants import (
    MARKETS, AGENTS, AGENTS_DIR, SCOREBOARD_DIR, LEADERBOARD_FILE,
    PRICE_CSV, FORECAST_HORIZON_HOURS, FORECAST_HORIZONS,
)

SCORES_CSV = "scores_history.csv"
SCORES_COLUMNS = [
    "timestamp", "agent", "market", "predicted", "actual", "current_price",
    "squared_error", "naive_se", "direction_correct", "methodology_version", "horizon",
]


# ── Scores History ───────────────────────────────────────────────────────────

def append_score_rows(rows):
    """Append scored prediction rows to the cumulative scores CSV."""
    file_exists = os.path.exists(SCORES_CSV) and os.path.getsize(SCORES_CSV) > 0
    with open(SCORES_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SCORES_COLUMNS)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ── Price Lookup ─────────────────────────────────────────────────────────────

def load_price_history():
    """Load price CSV into list of {timestamp, market_key: price} dicts."""
    if not os.path.exists(PRICE_CSV):
        return []
    rows = []
    with open(PRICE_CSV, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                parsed = {"timestamp": float(row["timestamp"])}
                for key in MARKETS:
                    val = row.get(key, "")
                    if val != "":
                        parsed[key] = float(val)
                rows.append(parsed)
            except (ValueError, KeyError):
                continue
    return rows


def find_price_at_time(price_history, target_ts, market_key, tolerance_hours=1):
    """Find the price closest to target_ts within tolerance. Returns None if no match."""
    tolerance_secs = tolerance_hours * 3600
    best = None
    best_dist = float("inf")

    for row in price_history:
        if market_key not in row:
            continue
        dist = abs(row["timestamp"] - target_ts)
        if dist < best_dist and dist <= tolerance_secs:
            best_dist = dist
            best = row[market_key]

    return best


# ── Scoring ──────────────────────────────────────────────────────────────────

def score_prediction(pred_price, actual_price):
    """Compute squared error and directional info for a single prediction."""
    se = (pred_price - actual_price) ** 2
    return {"squared_error": se, "predicted": pred_price, "actual": actual_price}


def compute_naive_baseline(price_at_t, price_at_t4h):
    """Naive baseline: predict no change. Returns SE."""
    return (price_at_t - price_at_t4h) ** 2


def compute_virtual_pnl(forecast_price, current_price, actual_price, threshold=0.02):
    """If forecast diverges from current by > threshold, simulate a $100 trade.
    Returns dict with trade details or None if no trade."""
    divergence = forecast_price - current_price
    if abs(divergence) < threshold:
        return None

    # Direction of bet
    direction = 1 if divergence > 0 else -1  # 1 = buy yes, -1 = sell yes
    actual_move = actual_price - current_price

    # P&L: did the actual move go in the same direction as our bet?
    pnl = direction * actual_move * 100  # $100 notional

    return {
        "direction": "long" if direction > 0 else "short",
        "divergence": round(divergence, 6),
        "actual_move": round(actual_move, 6),
        "pnl": round(pnl, 2),
        "won": pnl > 0,
    }


# ── Agent Log Scanning ───────────────────────────────────────────────────────

def get_scored_through(agent):
    """Get the timestamp through which this agent has been scored."""
    path = os.path.join(AGENTS_DIR, agent, "scored_through.txt")
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r") as f:
            return float(f.read().strip())
    except (ValueError, IOError):
        return 0


def mark_scored(agent, through_ts):
    """Mark that this agent has been scored through this timestamp."""
    path = os.path.join(AGENTS_DIR, agent, "scored_through.txt")
    with open(path, "w") as f:
        f.write(str(through_ts))


def find_matured_predictions(agent, price_history):
    """Find predictions that are old enough to score per horizon.
    Returns list of (prediction_dict, actual_prices_dict, pred_ts, horizon_label) tuples.
    Handles both old format (flat predictions) and new format (horizon-nested predictions).
    """
    log_dir = os.path.join(AGENTS_DIR, agent, "log")
    if not os.path.isdir(log_dir):
        return []

    scored_through = get_scored_through(agent)
    now = time.time()
    matured = []

    for log_file in sorted(glob.glob(os.path.join(log_dir, "*.json"))):
        try:
            with open(log_file, "r") as f:
                pred = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        # Parse prediction timestamp
        pred_ts_str = pred.get("timestamp", "")
        try:
            pred_dt = datetime.fromisoformat(pred_ts_str.replace("Z", "+00:00"))
            pred_ts = pred_dt.timestamp()
        except (ValueError, AttributeError):
            continue

        # Skip if already scored
        if pred_ts <= scored_through:
            continue

        predictions = pred.get("predictions", {})
        if not predictions:
            continue

        # Check format: old (flat) vs new (horizon-nested)
        first_market = next(iter(predictions.values()))
        is_horizon_nested = isinstance(first_market, dict) and ("24h" in first_market or "7d" in first_market)

        if is_horizon_nested:
            # New format: predictions are nested by horizon
            for horizon_label, horizon_hours in FORECAST_HORIZONS.items():
                horizon_secs = horizon_hours * 3600

                # Skip if not yet matured for this horizon
                if now - pred_ts < horizon_secs:
                    continue

                # Look up actual prices at T+horizon
                target_ts = pred_ts + horizon_secs
                # Scale tolerance with horizon: 2h for 24h, 8h for 7d
                tolerance_hours = 2 if horizon_hours == 24 else 8
                actual_prices = {}

                for market_key in predictions:
                    if horizon_label in predictions[market_key]:
                        actual = find_price_at_time(price_history, target_ts, market_key, tolerance_hours=tolerance_hours)
                        if actual is not None:
                            actual_prices[market_key] = actual

                if actual_prices:
                    matured.append((pred, actual_prices, pred_ts, horizon_label))
        else:
            # Old format: backward compatibility - treat as 4h predictions
            horizon_secs = 4 * 3600

            # Skip if not yet matured
            if now - pred_ts < horizon_secs:
                continue

            # Look up actual prices at T+4h
            target_ts = pred_ts + horizon_secs
            actual_prices = {}
            for market_key in predictions:
                actual = find_price_at_time(price_history, target_ts, market_key, tolerance_hours=1)
                if actual is not None:
                    actual_prices[market_key] = actual

            if actual_prices:
                matured.append((pred, actual_prices, pred_ts, "4h"))

    return matured


# ── Scorecard ────────────────────────────────────────────────────────────────

def load_scorecard(agent):
    """Load existing scorecard or create default."""
    path = os.path.join(AGENTS_DIR, agent, "scorecard.json")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    return {
        "agent": agent,
        "last_updated": None,
        "total_predictions": 0,
        "overall": {
            "mse": None,
            "directional_accuracy": None,
            "naive_baseline_mse": None,
        },
        "per_market": {},
        "per_horizon": {},
        "mse_trend_last_5": [],
        "source_performance": {},
        "virtual_pnl": {
            "total": 0.0,
            "trades": 0,
            "wins": 0,
            "losses": 0,
        },
        "methodology_version": "1.0.0",
    }


def update_scorecard(agent, new_scores):
    """Update agent's scorecard with new score entries.
    new_scores is a list of dicts with: market_key, predicted, actual, current,
    se, naive_se, direction_correct, pnl_trade, source_weights, methodology_version, horizon.
    """
    scorecard = load_scorecard(agent)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Migrate old scorecards missing newer keys
    scorecard.setdefault("per_horizon", {})
    scorecard.setdefault("per_market", {})
    scorecard.setdefault("mse_trend_last_5", [])
    scorecard.setdefault("source_performance", {})
    scorecard.setdefault("virtual_pnl", {"total": 0.0, "trades": 0, "wins": 0, "losses": 0})

    # Accumulate
    all_se = []
    all_naive_se = []
    all_correct = []
    per_market_data = {}
    per_horizon_data = {}

    # Load existing per-market stats
    for mk, stats in scorecard.get("per_market", {}).items():
        per_market_data[mk] = {
            "se_list": [stats["mse"]] * stats.get("count", 1) if stats["mse"] is not None else [],
            "correct_list": [stats["directional_accuracy"]] * stats.get("count", 1) if stats["directional_accuracy"] is not None else [],
            "naive_se_list": [stats.get("naive_baseline_mse")] * stats.get("count", 1) if stats.get("naive_baseline_mse") is not None else [],
            "count": stats.get("count", 0),
        }

    # Load existing per-horizon stats
    for hz, stats in scorecard.get("per_horizon", {}).items():
        per_horizon_data[hz] = {
            "se_list": [stats["mse"]] * stats.get("count", 1) if stats["mse"] is not None else [],
            "correct_list": [stats["directional_accuracy"]] * stats.get("count", 1) if stats["directional_accuracy"] is not None else [],
            "naive_se_list": [stats.get("naive_baseline_mse")] * stats.get("count", 1) if stats.get("naive_baseline_mse") is not None else [],
            "count": stats.get("count", 0),
        }

    for score in new_scores:
        mk = score["market_key"]
        hz = score.get("horizon", "4h")  # Default to 4h for backward compat
        se = score["se"]
        naive_se = score["naive_se"]
        correct = score["direction_correct"]

        all_se.append(se)
        all_naive_se.append(naive_se)
        all_correct.append(correct)

        if mk not in per_market_data:
            per_market_data[mk] = {"se_list": [], "correct_list": [], "naive_se_list": [], "count": 0}
        per_market_data[mk]["se_list"].append(se)
        per_market_data[mk]["correct_list"].append(correct)
        per_market_data[mk]["naive_se_list"].append(naive_se)
        per_market_data[mk]["count"] += 1

        if hz not in per_horizon_data:
            per_horizon_data[hz] = {"se_list": [], "correct_list": [], "naive_se_list": [], "count": 0}
        per_horizon_data[hz]["se_list"].append(se)
        per_horizon_data[hz]["correct_list"].append(correct)
        per_horizon_data[hz]["naive_se_list"].append(naive_se)
        per_horizon_data[hz]["count"] += 1

        # Virtual P&L
        trade = score.get("pnl_trade")
        if trade:
            scorecard["virtual_pnl"]["total"] += trade["pnl"]
            scorecard["virtual_pnl"]["trades"] += 1
            if trade["won"]:
                scorecard["virtual_pnl"]["wins"] += 1
            else:
                scorecard["virtual_pnl"]["losses"] += 1

        # Source performance tracking
        src_weights = score.get("source_weights", {})
        for src, weight in src_weights.items():
            if src not in scorecard.get("source_performance", {}):
                scorecard["source_performance"][src] = {"correct": 0, "total": 0}
            scorecard["source_performance"][src]["total"] += 1
            if correct:
                scorecard["source_performance"][src]["correct"] += 1

    # Update overall stats
    prev_total = scorecard["total_predictions"]
    new_total = prev_total + len(new_scores)
    scorecard["total_predictions"] = new_total

    # Recompute overall MSE as weighted average
    if scorecard["overall"]["mse"] is not None and prev_total > 0:
        prev_sum_se = scorecard["overall"]["mse"] * prev_total
        new_sum_se = prev_sum_se + sum(all_se)
        scorecard["overall"]["mse"] = round(new_sum_se / new_total, 8)
    else:
        scorecard["overall"]["mse"] = round(sum(all_se) / len(all_se), 8) if all_se else None

    if scorecard["overall"]["naive_baseline_mse"] is not None and prev_total > 0:
        prev_sum = scorecard["overall"]["naive_baseline_mse"] * prev_total
        new_sum = prev_sum + sum(all_naive_se)
        scorecard["overall"]["naive_baseline_mse"] = round(new_sum / new_total, 8)
    else:
        scorecard["overall"]["naive_baseline_mse"] = round(sum(all_naive_se) / len(all_naive_se), 8) if all_naive_se else None

    if scorecard["overall"]["directional_accuracy"] is not None and prev_total > 0:
        prev_correct = scorecard["overall"]["directional_accuracy"] * prev_total
        new_correct = prev_correct + sum(1 for c in all_correct if c)
        scorecard["overall"]["directional_accuracy"] = round(new_correct / new_total, 4)
    else:
        scorecard["overall"]["directional_accuracy"] = round(sum(1 for c in all_correct if c) / len(all_correct), 4) if all_correct else None

    # Per-market stats
    for mk, data in per_market_data.items():
        scorecard["per_market"][mk] = {
            "mse": round(sum(data["se_list"]) / len(data["se_list"]), 8) if data["se_list"] else None,
            "directional_accuracy": round(sum(1 for c in data["correct_list"] if c) / len(data["correct_list"]), 4) if data["correct_list"] else None,
            "naive_baseline_mse": round(sum(s for s in data["naive_se_list"] if s is not None) / len([s for s in data["naive_se_list"] if s is not None]), 8) if [s for s in data["naive_se_list"] if s is not None] else None,
            "count": data["count"],
        }

    # Per-horizon stats
    for hz, data in per_horizon_data.items():
        scorecard["per_horizon"][hz] = {
            "mse": round(sum(data["se_list"]) / len(data["se_list"]), 8) if data["se_list"] else None,
            "directional_accuracy": round(sum(1 for c in data["correct_list"] if c) / len(data["correct_list"]), 4) if data["correct_list"] else None,
            "naive_baseline_mse": round(sum(s for s in data["naive_se_list"] if s is not None) / len([s for s in data["naive_se_list"] if s is not None]), 8) if [s for s in data["naive_se_list"] if s is not None] else None,
            "count": data["count"],
        }

    # MSE trend (last 5 per-cycle MSEs)
    if all_se:
        cycle_mse = round(sum(all_se) / len(all_se), 8)
        scorecard["mse_trend_last_5"].append(cycle_mse)
        scorecard["mse_trend_last_5"] = scorecard["mse_trend_last_5"][-5:]

    # Source performance: compute directional accuracy
    for src in scorecard.get("source_performance", {}):
        sp = scorecard["source_performance"][src]
        if sp["total"] > 0:
            sp["directional_accuracy"] = round(sp["correct"] / sp["total"], 4)

    # Metadata
    scorecard["last_updated"] = now
    if new_scores:
        scorecard["methodology_version"] = new_scores[-1].get("methodology_version", scorecard.get("methodology_version", "1.0.0"))

    # Save
    path = os.path.join(AGENTS_DIR, agent, "scorecard.json")
    with open(path, "w") as f:
        json.dump(scorecard, f, indent=2)

    return scorecard


# ── Leaderboard ──────────────────────────────────────────────────────────────

def update_leaderboard():
    """Build leaderboard from all agent scorecards + naive baseline.
    Primary ranking uses 24h MSE if available, falls back to overall MSE.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entries = []
    for agent in AGENTS:
        scorecard = load_scorecard(agent)
        if scorecard["total_predictions"] == 0:
            continue

        # Primary ranking uses 24h MSE if available
        primary_mse = scorecard.get("per_horizon", {}).get("24h", {}).get("mse")
        if primary_mse is None:
            primary_mse = scorecard["overall"]["mse"]

        entries.append({
            "agent": agent,
            "mse": scorecard["overall"]["mse"],
            "mse_24h": scorecard.get("per_horizon", {}).get("24h", {}).get("mse"),
            "mse_7d": scorecard.get("per_horizon", {}).get("7d", {}).get("mse"),
            "primary_mse": primary_mse,
            "directional_accuracy": scorecard["overall"]["directional_accuracy"],
            "total_predictions": scorecard["total_predictions"],
            "methodology_version": scorecard.get("methodology_version", "?"),
        })

    # Add naive baseline entry from first available scorecard
    naive_mse = None
    for agent in AGENTS:
        sc = load_scorecard(agent)
        if sc["overall"]["naive_baseline_mse"] is not None:
            naive_mse = sc["overall"]["naive_baseline_mse"]
            break

    if naive_mse is not None:
        entries.append({
            "agent": "naive_baseline",
            "mse": naive_mse,
            "directional_accuracy": None,
            "total_predictions": None,
            "methodology_version": "N/A",
        })

    # Sort by primary MSE (24h if available, ascending = better)
    ranked_by_mse = sorted([e for e in entries if e["primary_mse"] is not None], key=lambda x: x["primary_mse"])
    for i, entry in enumerate(ranked_by_mse):
        entry["mse_rank"] = i + 1

    # Sort by directional accuracy (descending = better)
    ranked_by_dir = sorted(
        [e for e in entries if e["directional_accuracy"] is not None],
        key=lambda x: x["directional_accuracy"],
        reverse=True,
    )
    for i, entry in enumerate(ranked_by_dir):
        entry["dir_rank"] = i + 1

    # Per-market MSE
    per_market_mse = {}
    for market_key in MARKETS:
        per_market_mse[market_key] = {}
        for agent in AGENTS:
            sc = load_scorecard(agent)
            mk_stats = sc.get("per_market", {}).get(market_key, {})
            if mk_stats.get("mse") is not None:
                per_market_mse[market_key][agent] = mk_stats["mse"]

    leaderboard = {
        "last_updated": now,
        "total_cycles": max((e.get("total_predictions", 0) or 0) for e in entries) if entries else 0,
        "rankings_by_mse": [{"agent": e["agent"], "mse": e["mse"], "mse_24h": e.get("mse_24h"), "mse_7d": e.get("mse_7d"), "primary_mse": e["primary_mse"], "rank": e.get("mse_rank")} for e in ranked_by_mse],
        "rankings_by_directional": [{"agent": e["agent"], "directional_accuracy": e["directional_accuracy"], "rank": e.get("dir_rank")} for e in ranked_by_dir],
        "per_market_mse": per_market_mse,
    }

    os.makedirs(SCOREBOARD_DIR, exist_ok=True)
    with open(LEADERBOARD_FILE, "w") as f:
        json.dump(leaderboard, f, indent=2)

    return leaderboard


# ── Main Evaluation Pipeline ─────────────────────────────────────────────────

def run_evaluation():
    """Score all matured predictions across all agents."""
    print("=== Evaluation ===")

    price_history = load_price_history()
    if not price_history:
        print("  No price history available. Skipping evaluation.")
        return

    print(f"  Loaded {len(price_history)} price history rows")

    any_scored = False

    for agent in AGENTS:
        agent_dir = os.path.join(AGENTS_DIR, agent)
        if not os.path.isdir(agent_dir):
            continue

        matured = find_matured_predictions(agent, price_history)
        if not matured:
            print(f"  {agent}: no matured predictions to score")
            continue

        print(f"  {agent}: scoring {len(matured)} predictions...")
        new_scores = []
        max_pred_ts = 0

        for pred, actual_prices, pred_ts, horizon_label in matured:
            max_pred_ts = max(max_pred_ts, pred_ts)

            predictions = pred.get("predictions", {})
            for market_key in predictions:
                if market_key not in actual_prices:
                    continue

                # Handle both old (flat) and new (horizon-nested) formats
                if horizon_label == "4h":
                    # Old format: direct access
                    pred_data = predictions[market_key]
                    predicted = pred_data["prediction"]
                    current = pred_data["current"]
                else:
                    # New format: horizon-nested
                    if horizon_label not in predictions[market_key]:
                        continue
                    pred_data = predictions[market_key][horizon_label]
                    predicted = pred_data["prediction"]
                    current = pred_data["current"]

                actual = actual_prices[market_key]

                se = (predicted - actual) ** 2
                naive_se = (current - actual) ** 2

                # Directional accuracy: did we predict the right direction of movement?
                predicted_direction = predicted - current  # our predicted move
                actual_direction = actual - current        # what actually happened
                direction_correct = (predicted_direction * actual_direction) > 0

                # Virtual P&L
                pnl_trade = compute_virtual_pnl(predicted, current, actual)

                new_scores.append({
                    "market_key": market_key,
                    "predicted": predicted,
                    "actual": actual,
                    "current": current,
                    "se": round(se, 8),
                    "naive_se": round(naive_se, 8),
                    "direction_correct": direction_correct,
                    "pnl_trade": pnl_trade,
                    "source_weights": pred.get("source_weights", {}),
                    "methodology_version": pred.get("methodology_version", "?"),
                    "pred_ts": pred_ts,
                    "horizon": horizon_label,
                })

        if new_scores:
            # Append to cumulative scores CSV (for plotting)
            csv_rows = []
            seen_naive = set()
            for s in new_scores:
                csv_rows.append({
                    "timestamp": s["pred_ts"],
                    "agent": agent,
                    "market": s["market_key"],
                    "predicted": s["predicted"],
                    "actual": s["actual"],
                    "current_price": s["current"],
                    "squared_error": s["se"],
                    "naive_se": s["naive_se"],
                    "direction_correct": s["direction_correct"],
                    "methodology_version": s["methodology_version"],
                    "horizon": s["horizon"],
                })
                # One naive baseline row per (timestamp, market, horizon) triple
                naive_key = (s["pred_ts"], s["market_key"], s["horizon"])
                if naive_key not in seen_naive:
                    seen_naive.add(naive_key)
                    csv_rows.append({
                        "timestamp": s["pred_ts"],
                        "agent": "naive_baseline",
                        "market": s["market_key"],
                        "predicted": s["current"],
                        "actual": s["actual"],
                        "current_price": s["current"],
                        "squared_error": s["naive_se"],
                        "naive_se": s["naive_se"],
                        "direction_correct": False,
                        "methodology_version": "N/A",
                        "horizon": s["horizon"],
                    })
            append_score_rows(csv_rows)

            scorecard = update_scorecard(agent, new_scores)
            mark_scored(agent, max_pred_ts)
            any_scored = True

            avg_se = sum(s["se"] for s in new_scores) / len(new_scores)
            correct = sum(1 for s in new_scores if s["direction_correct"])
            print(f"    Scored {len(new_scores)} predictions: MSE={avg_se:.6f}, "
                  f"Directional={correct}/{len(new_scores)}")

    if any_scored:
        leaderboard = update_leaderboard()
        print(f"\n  Leaderboard updated ({len(leaderboard['rankings_by_mse'])} entries)")
        for entry in leaderboard["rankings_by_mse"]:
            mse_24h_str = f", 24h={entry['mse_24h']:.6f}" if entry.get('mse_24h') is not None else ""
            mse_7d_str = f", 7d={entry['mse_7d']:.6f}" if entry.get('mse_7d') is not None else ""
            print(f"    #{entry['rank']} {entry['agent']}: MSE={entry['mse']:.6f}{mse_24h_str}{mse_7d_str}")
    else:
        print("  No predictions scored this cycle.")
        # Still update leaderboard with whatever exists
        update_leaderboard()


if __name__ == "__main__":
    run_evaluation()
