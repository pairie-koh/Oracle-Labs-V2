"""
Oracle Lab — evaluate_rolling.py
Scores LLM predictions on rolling contracts against actual resolution outcomes.

Rolling contracts resolve daily, so each cycle we check if yesterday's contracts
have resolved and score our predictions against the actual outcomes.

Usage: python evaluate_rolling.py [--date YYYY-MM-DD]
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests

from constants import POLYMARKET_GAMMA_URL
from lessons import rebuild_lessons_cache

ROLLING_SCORES_CSV = "rolling_scores_history.csv"
ROLLING_SCORES_COLUMNS = [
    "date", "contract_key", "contract_name", "contract_type",
    "prediction", "market_price", "outcome", "correct",
    "squared_error", "market_squared_error", "edge_vs_market",
    "tier", "timestamp",
]

# Predictions made after this hour (UTC) are excluded — by late day the market
# already reflects the outcome, so "predicting" the market price is hindsight.
INFO_LEAKAGE_CUTOFF_HOUR = 14  # 2pm UTC = ~10am ET


def load_predictions_for_date(target_date):
    """Load LLM predictions that were made DURING the target date's contract window.

    Rolling contracts for date D cover the calendar day in UTC. We only score
    predictions made on that same calendar day AND before the info leakage
    cutoff (early enough that the outcome wasn't already known from the market).
    """
    predictions_dir = "llm_predictions"
    if not os.path.isdir(predictions_dir):
        return []

    target_str = target_date.strftime("%Y-%m-%d")
    cutoff_hour = INFO_LEAKAGE_CUTOFF_HOUR

    all_preds = []

    for fname in sorted(os.listdir(predictions_dir)):
        if not fname.endswith(".json") or fname == "latest.json":
            continue

        path = os.path.join(predictions_dir, fname)
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        pred_timestamp = data.get("timestamp", "")
        if not pred_timestamp:
            continue

        # Parse prediction timestamp
        try:
            pred_dt = datetime.fromisoformat(pred_timestamp.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue

        # Only include predictions made ON the target date (same calendar day UTC)
        if pred_dt.strftime("%Y-%m-%d") != target_str:
            continue

        # Info leakage filter: reject predictions made after cutoff
        if pred_dt.hour >= cutoff_hour:
            print(f"    SKIP {fname}: made at {pred_dt.strftime('%H:%M')} UTC "
                  f"(after {cutoff_hour}:00 cutoff)")
            continue

        preds = data.get("predictions", [])
        rolling_preds = [p for p in preds if p.get("source") == "rolling"]
        if rolling_preds:
            all_preds.append({
                "timestamp": pred_timestamp,
                "predictions": rolling_preds,
            })

    return all_preds


def fetch_resolved_contract(slug_template, target_date):
    """Fetch a resolved rolling contract to check its outcome.

    Returns the event data with resolution info, or None.
    """
    from rolling_contracts import build_slug

    slug = build_slug(slug_template, target_date)
    url = f"{POLYMARKET_GAMMA_URL}/events"
    params = {"slug": slug}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        events = resp.json()
        if events and len(events) > 0:
            return events[0]
    except requests.exceptions.RequestException as e:
        print(f"  ERROR fetching resolved event {slug}: {e}")

    return None


def check_binary_resolution(event):
    """Check if a binary rolling contract has resolved and what the outcome was.

    Returns:
        (resolved: bool, outcome: float or None)
        outcome = 1.0 if YES, 0.0 if NO, None if not resolved
    """
    markets = event.get("markets", [])
    if not markets:
        return False, None

    market = markets[0]

    # Check if resolved via the 'resolved' field
    if market.get("resolved"):
        # Check winning outcome
        outcomes_raw = market.get("outcomes", "")
        prices_raw = market.get("outcomePrices", "")

        if isinstance(outcomes_raw, str):
            try:
                outcomes = json.loads(outcomes_raw)
            except json.JSONDecodeError:
                outcomes = []
        else:
            outcomes = outcomes_raw or []

        if isinstance(prices_raw, str):
            try:
                prices = [float(p) for p in json.loads(prices_raw)]
            except (json.JSONDecodeError, ValueError):
                prices = []
        else:
            prices = [float(p) for p in (prices_raw or [])]

        # After resolution, winning outcome price = 1.0, losing = 0.0
        if prices:
            yes_price = prices[0]
            # If YES price is ~1.0, outcome is YES (1.0). If ~0.0, outcome is NO (0.0)
            if yes_price > 0.9:
                return True, 1.0
            elif yes_price < 0.1:
                return True, 0.0

        return True, None

    # Check if end date has passed (contract should have resolved)
    end_date = market.get("endDate", "")
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > end_dt:
                # Contract past end date but not showing as resolved yet
                # Check if prices have converged to 0 or 1
                prices_raw = market.get("outcomePrices", "")
                if isinstance(prices_raw, str):
                    try:
                        prices = [float(p) for p in json.loads(prices_raw)]
                    except (json.JSONDecodeError, ValueError):
                        prices = []
                else:
                    prices = [float(p) for p in (prices_raw or [])]

                if prices and prices[0] > 0.95:
                    return True, 1.0
                elif prices and prices[0] < 0.05:
                    return True, 0.0
        except (ValueError, AttributeError):
            pass

    return False, None


def check_multi_outcome_resolution(event):
    """Check if a multi-outcome rolling contract has resolved.

    Returns:
        (resolved: bool, outcomes: list of (question, resolved_price) or None)
    """
    markets = event.get("markets", [])
    if not markets:
        return False, None

    # Check if any market is resolved
    any_resolved = any(m.get("resolved") for m in markets)

    if not any_resolved:
        # Check if past end date
        end_date = markets[0].get("endDate", "")
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) <= end_dt:
                    return False, None
            except (ValueError, AttributeError):
                return False, None

    # Extract resolution outcomes
    outcomes = []
    for m in markets:
        question = m.get("question", "")
        prices_raw = m.get("outcomePrices", "")
        if isinstance(prices_raw, str):
            try:
                prices = [float(p) for p in json.loads(prices_raw)]
            except (json.JSONDecodeError, ValueError):
                prices = []
        else:
            prices = [float(p) for p in (prices_raw or [])]

        yes_price = prices[0] if prices else None
        outcomes.append({
            "question": question,
            "resolved_price": yes_price,
        })

    # Only consider resolved if prices have converged (one ~1.0, rest ~0.0)
    if outcomes:
        resolved_prices = [o["resolved_price"] for o in outcomes if o["resolved_price"] is not None]
        if resolved_prices:
            max_price = max(resolved_prices)
            if max_price > 0.9:
                return True, outcomes

    return any_resolved, outcomes if any_resolved else None


def score_binary_prediction(prediction, outcome):
    """Score a binary prediction against the resolved outcome.

    prediction: float (our estimated probability of YES)
    outcome: float (1.0 = YES resolved, 0.0 = NO resolved)

    Returns dict with scoring metrics.
    """
    se = (prediction - outcome) ** 2

    # Did we predict the right side?
    predicted_yes = prediction > 0.5
    actual_yes = outcome > 0.5
    correct = predicted_yes == actual_yes

    return {
        "squared_error": round(se, 6),
        "correct": correct,
    }


def score_multi_outcome_prediction(predictions, outcomes):
    """Score multi-outcome predictions against resolved outcomes.

    predictions: list of floats (our probability for each outcome)
    outcomes: list of dicts with 'resolved_price'

    Returns dict with scoring metrics.
    """
    if len(predictions) != len(outcomes):
        return None

    total_se = 0
    correct_winner = False

    resolved_prices = [o["resolved_price"] for o in outcomes]

    for pred, actual in zip(predictions, resolved_prices):
        if actual is not None:
            total_se += (pred - actual) ** 2

    # Did we pick the right winner? (highest prediction = highest outcome)
    if resolved_prices and predictions:
        pred_winner = predictions.index(max(predictions))
        valid_prices = [p for p in resolved_prices if p is not None]
        if valid_prices:
            actual_winner = resolved_prices.index(max(resolved_prices))
            correct_winner = pred_winner == actual_winner

    avg_se = total_se / len(predictions) if predictions else 0

    return {
        "squared_error": round(avg_se, 6),
        "correct": correct_winner,
    }


def load_already_scored_rolling():
    """Load set of (date, contract_key, timestamp) already in rolling CSV."""
    already = set()
    if os.path.exists(ROLLING_SCORES_CSV):
        with open(ROLLING_SCORES_CSV, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row.get("date", ""), row.get("contract_key", ""),
                       row.get("timestamp", ""))
                already.add(key)
    return already


def _read_all_rolling_rows():
    """Read all rows from rolling CSV, tolerating schema mismatches."""
    if not os.path.exists(ROLLING_SCORES_CSV) or os.path.getsize(ROLLING_SCORES_CSV) == 0:
        return []
    with open(ROLLING_SCORES_CSV, "r", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _deduplicate_rows(rows):
    """Remove duplicate rows by (date, contract_key, timestamp) key, keeping first."""
    seen = set()
    unique = []
    for row in rows:
        key = (row.get("date", ""), row.get("contract_key", ""),
               row.get("timestamp", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _rewrite_rolling_csv(rows):
    """Rewrite the entire rolling CSV with current schema and deduplicated rows."""
    with open(ROLLING_SCORES_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ROLLING_SCORES_COLUMNS,
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def append_rolling_scores(rows):
    """Append scored rolling predictions to the cumulative CSV, skipping duplicates.

    Also deduplicates the entire file on each write to prevent drift from
    schema changes or repeated evaluation runs.
    """
    existing = _read_all_rolling_rows()
    all_rows = existing + rows
    deduped = _deduplicate_rows(all_rows)

    new_count = len(deduped) - len(_deduplicate_rows(existing))
    _rewrite_rolling_csv(deduped)

    return new_count


STATIC_SCORES_CSV = "static_scores_history.csv"
STATIC_SCORES_COLUMNS = [
    "timestamp", "prediction_timestamp", "contract_key", "contract_name",
    "prediction", "market_price_at_pred", "market_price_now",
    "predicted_direction", "actual_direction", "direction_correct",
    "squared_error", "market_squared_error", "edge_vs_market",
    "tier",
]


def append_static_scores(rows):
    """Append scored static predictions to the cumulative CSV."""
    file_exists = os.path.exists(STATIC_SCORES_CSV) and os.path.getsize(STATIC_SCORES_CSV) > 0
    with open(STATIC_SCORES_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=STATIC_SCORES_COLUMNS)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def get_clob_midpoint(token_id):
    """Fetch current midpoint price from Polymarket CLOB API."""
    try:
        resp = requests.get(
            "https://clob.polymarket.com/midpoint",
            params={"token_id": token_id},
            timeout=10,
        )
        resp.raise_for_status()
        return float(resp.json().get("mid", 0))
    except Exception:
        return None


def run_static_evaluation(min_age_hours=20):
    """Score static contract predictions by comparing to current market price.

    Finds LLM predictions on static contracts that are at least min_age_hours old,
    fetches current prices, and scores directional accuracy + squared error.
    """
    print("\n=== Static Contract Evaluation ===")

    predictions_dir = "llm_predictions"
    if not os.path.isdir(predictions_dir):
        print("  No predictions directory found. Skipping.")
        return

    # Track what we've already scored to avoid duplicates
    already_scored = set()
    if os.path.exists(STATIC_SCORES_CSV):
        with open(STATIC_SCORES_CSV, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row.get("prediction_timestamp", ""), row.get("contract_key", ""))
                already_scored.add(key)

    now = datetime.now(timezone.utc)
    scored_rows = []

    # Scan prediction files for static contract predictions old enough to score
    for fname in sorted(os.listdir(predictions_dir)):
        if not fname.endswith(".json") or fname == "latest.json":
            continue

        path = os.path.join(predictions_dir, fname)
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        pred_timestamp = data.get("timestamp", "")
        if not pred_timestamp:
            continue

        # Check age
        try:
            pred_dt = datetime.fromisoformat(pred_timestamp.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue

        age_hours = (now - pred_dt).total_seconds() / 3600
        if age_hours < min_age_hours:
            continue

        # Find static predictions in this file
        for pred in data.get("predictions", []):
            if pred.get("source") != "static":
                continue
            if pred.get("type") != "binary":
                continue

            contract_key = pred.get("key", "")
            score_key = (pred_timestamp, contract_key)
            if score_key in already_scored:
                continue

            prediction = pred.get("prediction", 0.5)
            market_price_at_pred = pred.get("market_price", 0.5)
            tier = pred.get("tier", "unknown")
            question = pred.get("question", "")

            # We need the token ID to fetch current price
            # Load from active_contracts.json
            contracts_path = os.path.join("contracts", "active_contracts.json")
            if not os.path.exists(contracts_path):
                continue

            with open(contracts_path) as f:
                contracts_data = json.load(f)

            # Find matching contract by slug
            yes_token = None
            for c in contracts_data.get("contracts", []):
                if c.get("slug", "") == contract_key:
                    yes_token = c.get("yes_token_id", "")
                    break

            if not yes_token:
                continue

            # Fetch current price
            current_price = get_clob_midpoint(yes_token)
            if current_price is None:
                continue

            # Score: directional accuracy
            predicted_direction = prediction - market_price_at_pred  # which way we thought it would move
            actual_direction = current_price - market_price_at_pred  # which way it actually moved

            if abs(predicted_direction) < 0.001:
                direction_correct = abs(actual_direction) < 0.01  # predicted no change, was there no change?
            else:
                direction_correct = (predicted_direction * actual_direction) > 0

            # Squared error vs outcome price
            se = (prediction - current_price) ** 2
            market_se = (market_price_at_pred - current_price) ** 2
            edge = market_se - se  # positive = we beat the market

            dir_str = "CORRECT" if direction_correct else "WRONG"
            edge_str = f"+{edge:.4f}" if edge > 0 else f"{edge:.4f}"
            print(f"  {question[:50]} | pred={prediction:.3f} mkt_then={market_price_at_pred:.3f} "
                  f"mkt_now={current_price:.3f} | {dir_str} | edge={edge_str}")

            scored_rows.append({
                "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "prediction_timestamp": pred_timestamp,
                "contract_key": contract_key,
                "contract_name": question[:100],
                "prediction": round(prediction, 4),
                "market_price_at_pred": round(market_price_at_pred, 4),
                "market_price_now": round(current_price, 4),
                "predicted_direction": "up" if predicted_direction > 0.001 else ("down" if predicted_direction < -0.001 else "flat"),
                "actual_direction": "up" if actual_direction > 0.001 else ("down" if actual_direction < -0.001 else "flat"),
                "direction_correct": direction_correct,
                "squared_error": round(se, 6),
                "market_squared_error": round(market_se, 6),
                "edge_vs_market": round(edge, 6),
                "tier": tier,
            })

            import time as _time
            _time.sleep(0.1)  # Rate limit CLOB API

    if scored_rows:
        append_static_scores(scored_rows)
        correct_count = sum(1 for r in scored_rows if r["direction_correct"])
        avg_se = sum(r["squared_error"] for r in scored_rows) / len(scored_rows)
        avg_edge = sum(r["edge_vs_market"] for r in scored_rows) / len(scored_rows)
        print(f"\n  === Scored {len(scored_rows)} static predictions ===")
        print(f"  Direction accuracy: {correct_count}/{len(scored_rows)} ({100*correct_count/len(scored_rows):.0f}%)")
        print(f"  Average SE: {avg_se:.6f}")
        print(f"  Average edge vs market: {avg_edge:.6f}")
        print(f"  Saved to {STATIC_SCORES_CSV}")
    else:
        print("  No static predictions ready to score this cycle.")


def run_rolling_evaluation(target_date=None):
    """Score rolling contract predictions against actual resolutions."""
    print("=== Rolling Contract Evaluation ===")

    if target_date is None:
        # Check yesterday's contracts (they should have resolved by now)
        target_date = datetime.now(timezone.utc) - timedelta(days=1)

    date_str = target_date.strftime("%Y-%m-%d")
    print(f"  Checking resolutions for: {date_str}")

    # Load rolling contract definitions
    from rolling_contracts import ROLLING_CONTRACTS, build_slug

    # Load all prediction files that have rolling predictions
    all_pred_files = load_predictions_for_date(target_date)
    if not all_pred_files:
        print("  No LLM predictions found for rolling contracts. Skipping.")
        return

    # Check which predictions match this date's contracts
    scored_rows = []

    for contract_key, config in ROLLING_CONTRACTS.items():
        slug = build_slug(config["slug_template"], target_date)
        print(f"\n  {config['name']} ({date_str}): {slug}")

        # Fetch the resolved contract
        event = fetch_resolved_contract(config["slug_template"], target_date)
        if not event:
            print(f"    Event not found — skipping")
            continue

        if config["type"] == "binary":
            resolved, outcome = check_binary_resolution(event)
            if not resolved:
                print(f"    Not yet resolved — skipping")
                continue

            if outcome is None:
                print(f"    Resolved but outcome unclear — skipping")
                continue

            outcome_str = "YES" if outcome > 0.5 else "NO"
            print(f"    Resolved: {outcome_str}")

            # Find matching predictions
            for pred_file in all_pred_files:
                for pred in pred_file["predictions"]:
                    if pred.get("key") != contract_key:
                        continue

                    prediction = pred.get("prediction", 0.5)
                    market_price = pred.get("market_price", 0.5)
                    tier = pred.get("tier", "unknown")

                    score = score_binary_prediction(prediction, outcome)
                    market_score = score_binary_prediction(market_price, outcome)
                    mkt_se = market_score["squared_error"]
                    edge = mkt_se - score["squared_error"]

                    correct_str = "CORRECT" if score["correct"] else "WRONG"
                    edge_str = f"+{edge:.4f}" if edge > 0 else f"{edge:.4f}"
                    print(f"    Prediction: {prediction:.3f} | Market: {market_price:.3f} | "
                          f"Outcome: {outcome:.0f} | {correct_str} | "
                          f"SE: {score['squared_error']:.4f} (market SE: {mkt_se:.4f}) edge={edge_str}")

                    scored_rows.append({
                        "date": date_str,
                        "contract_key": contract_key,
                        "contract_name": config["name"],
                        "contract_type": "binary",
                        "prediction": round(prediction, 4),
                        "market_price": round(market_price, 4),
                        "outcome": outcome,
                        "correct": score["correct"],
                        "squared_error": score["squared_error"],
                        "market_squared_error": mkt_se,
                        "edge_vs_market": round(edge, 6),
                        "tier": tier,
                        "timestamp": pred_file["timestamp"],
                    })

        elif config["type"] == "multi-outcome":
            resolved, outcomes = check_multi_outcome_resolution(event)
            if not resolved or outcomes is None:
                print(f"    Not yet resolved — skipping")
                continue

            # Find the winning outcome
            winner = None
            for o in outcomes:
                if o["resolved_price"] is not None and o["resolved_price"] > 0.9:
                    winner = o["question"][:50]
                    break
            print(f"    Resolved. Winner: {winner or 'unclear'}")

            # Find matching predictions
            for pred_file in all_pred_files:
                for pred in pred_file["predictions"]:
                    if pred.get("key") != contract_key:
                        continue

                    predictions = pred.get("outcome_predictions", [])
                    market_prices = pred.get("outcome_market_prices", [])
                    tier = pred.get("tier", "unknown")

                    score = score_multi_outcome_prediction(predictions, outcomes)
                    if score is None:
                        print(f"    Prediction/outcome count mismatch — skipping")
                        continue

                    market_score = score_multi_outcome_prediction(market_prices, outcomes)
                    mkt_se = market_score["squared_error"] if market_score else 0
                    edge = mkt_se - score["squared_error"]

                    correct_str = "CORRECT WINNER" if score["correct"] else "WRONG WINNER"
                    edge_str = f"+{edge:.4f}" if edge > 0 else f"{edge:.4f}"
                    print(f"    {correct_str} | SE: {score['squared_error']:.4f} "
                          f"(market SE: {mkt_se:.4f}) edge={edge_str}")

                    scored_rows.append({
                        "date": date_str,
                        "contract_key": contract_key,
                        "contract_name": config["name"],
                        "contract_type": "multi-outcome",
                        "prediction": json.dumps([round(p, 4) for p in predictions]),
                        "market_price": json.dumps([round(p, 4) for p in market_prices]),
                        "outcome": json.dumps([o["resolved_price"] for o in outcomes]),
                        "correct": score["correct"],
                        "squared_error": score["squared_error"],
                        "market_squared_error": round(mkt_se, 6),
                        "edge_vs_market": round(edge, 6),
                        "tier": tier,
                        "timestamp": pred_file["timestamp"],
                    })

    # Save scores (dedup happens inside append_rolling_scores)
    if scored_rows:
        new_count = append_rolling_scores(scored_rows)
        correct_count = sum(1 for r in scored_rows if r["correct"])
        avg_se = sum(r["squared_error"] for r in scored_rows) / len(scored_rows)
        avg_mkt_se = sum(r["market_squared_error"] for r in scored_rows) / len(scored_rows)
        avg_edge = sum(r["edge_vs_market"] for r in scored_rows) / len(scored_rows)
        print(f"\n  === Scored {len(scored_rows)} rolling predictions ({new_count} new, {len(scored_rows) - new_count} already in CSV) ===")
        print(f"  Accuracy: {correct_count}/{len(scored_rows)} ({100*correct_count/len(scored_rows):.0f}%)")
        print(f"  Average SE: {avg_se:.4f}")
        print(f"  Average market SE: {avg_mkt_se:.4f}")
        print(f"  Average edge vs market: {avg_edge:.4f} ({'BEATING' if avg_edge > 0 else 'LOSING TO'} market)")
        print(f"  Saved to {ROLLING_SCORES_CSV}")
    else:
        print(f"\n  No rolling predictions scored this cycle.")


def main():
    parser = argparse.ArgumentParser(description="Evaluate LLM predictions (rolling + static)")
    parser.add_argument("--date", type=str, help="Date to check rolling (YYYY-MM-DD), defaults to yesterday")
    parser.add_argument("--days-back", type=int, default=1, help="Check this many days back (default: 1)")
    parser.add_argument("--rolling-only", action="store_true", help="Only evaluate rolling contracts")
    parser.add_argument("--static-only", action="store_true", help="Only evaluate static contracts")
    args = parser.parse_args()

    if not args.static_only:
        if args.date:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            run_rolling_evaluation(target_date)
        else:
            for days_ago in range(args.days_back, 0, -1):
                target_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
                run_rolling_evaluation(target_date)

    if not args.rolling_only:
        run_static_evaluation()

    # Rebuild lessons cache so next forecast cycle has updated bias stats
    print("\n=== Rebuilding Lessons Cache ===")
    rebuild_lessons_cache()


if __name__ == "__main__":
    main()
