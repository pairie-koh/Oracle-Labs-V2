"""
Oracle Lab — Cycle Report Generator
Assembles a human-readable plaintext report from the latest cycle's outputs.
No dependencies beyond stdlib.
"""

import glob
import json
import os
from datetime import datetime, timezone

AGENTS = ["momentum", "historian", "game_theorist", "quant"]
REPORTS_DIR = "reports"


def load_json(path):
    """Load a JSON file, return None on failure."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def get_latest_agent_log(agent_name):
    """Find the most recent log file for an agent."""
    log_dir = os.path.join("agents", agent_name, "log")
    if not os.path.isdir(log_dir):
        return None
    files = sorted(glob.glob(os.path.join(log_dir, "*.json")))
    if not files:
        return None
    return load_json(files[-1])


def format_market_snapshot(briefing):
    """Format the market price snapshot section."""
    lines = []
    market_prices = briefing.get("market_prices", {})
    for market_key, data in market_prices.items():
        current = data.get("current", 0)
        change_4h = data.get("change_4h", 0)
        change_24h = data.get("change_24h", 0)
        lines.append(f"  {market_key}: {current:.3f} (4h: {change_4h:+.3f}, 24h: {change_24h:+.3f})")
    return "\n".join(lines)


def format_newswire(briefing):
    """Format the newswire summary section."""
    facts = briefing.get("fresh_facts", [])
    if not facts:
        return "  No facts available."

    # Count by direction
    escalation_cats = {"military_pressure", "economic_collapse", "internal_stability"}
    deescalation_cats = {"diplomatic_signals", "international_response"}

    esc_count = 0
    deesc_count = 0
    neutral_count = 0

    for fact in facts:
        cat = fact.get("indicator_category", "")
        if cat in escalation_cats:
            esc_count += 1
        elif cat in deescalation_cats:
            deesc_count += 1
        else:
            neutral_count += 1

    lines = [f"  {len(facts)} facts ({esc_count} escalatory, {deesc_count} de-escalatory, {neutral_count} neutral)"]

    # Top claims (first 3, truncated)
    lines.append("  Top claims:")
    for fact in facts[:3]:
        cat = fact.get("indicator_category", "unknown")
        claim = fact.get("claim", "")
        if len(claim) > 90:
            claim = claim[:87] + "..."
        lines.append(f"    [{cat}] {claim}")

    return "\n".join(lines)


def format_forecasts(briefing, agent_logs):
    """Format the forecasts table."""
    market_prices = briefing.get("market_prices", {})
    markets = list(market_prices.keys())

    lines = []
    predictions_by_market = {m: [] for m in markets}

    header = f"  {'':16s} {'Pred':>7s}  {'Δ':>7s}  Key driver"
    lines.append(header)

    for agent_name in AGENTS:
        log = agent_logs.get(agent_name)
        if not log:
            lines.append(f"  {agent_name:16s} (no data)")
            continue

        preds = log.get("predictions", {})
        for market_key in markets:
            pred_data = preds.get(market_key, {})
            prediction = pred_data.get("prediction", 0)
            current = pred_data.get("current", 0)
            delta = prediction - current

            predictions_by_market[market_key].append(prediction)

            # Build key driver string based on agent
            driver = build_driver_string(agent_name, pred_data)

            lines.append(f"  {agent_name:16s} {prediction:7.3f}  {delta:+7.3f}  {driver}")

    # Spread and direction summary
    for market_key in markets:
        preds = predictions_by_market[market_key]
        if len(preds) >= 2:
            spread = max(preds) - min(preds)
            current = market_prices[market_key].get("current", 0)

            # Which agent is high/low
            agent_preds = []
            for agent_name in AGENTS:
                log = agent_logs.get(agent_name)
                if log:
                    p = log.get("predictions", {}).get(market_key, {}).get("prediction", 0)
                    agent_preds.append((p, agent_name))

            agent_preds.sort()
            high_agent = agent_preds[-1][1] if agent_preds else "?"
            low_agent = agent_preds[0][1] if agent_preds else "?"

            up_count = sum(1 for p in preds if p > current)
            down_count = sum(1 for p in preds if p < current)
            flat_count = sum(1 for p in preds if p == current)
            if up_count > down_count:
                direction = f"UP ({up_count}/{len(preds)})"
            elif down_count > up_count:
                direction = f"DOWN ({down_count}/{len(preds)})"
            else:
                direction = f"MIXED ({up_count} up, {down_count} down)"

            lines.append("")
            lines.append(f"  Spread: {spread:.3f} ({high_agent} high, {low_agent} low)")
            lines.append(f"  Direction: {direction}")

    return "\n".join(lines)


def build_driver_string(agent_name, pred_data):
    """Build a concise key driver string for each agent type."""
    if agent_name == "momentum":
        intensity = pred_data.get("decay_adjusted_intensity", pred_data.get("news_intensity", 0))
        blend = pred_data.get("blend_weight", 0)
        return f"intensity={intensity:.1f} (decayed), blend={blend:.2f}"

    elif agent_name == "historian":
        base = pred_data.get("adaptive_base_rate", pred_data.get("base_rate", 0))
        shift = pred_data.get("capped_shift", pred_data.get("news_shift", 0))
        return f"base={base:.2f} (adaptive), capped_shift={shift:+.3f}"

    elif agent_name == "game_theorist":
        consensus = pred_data.get("consensus_ratio", 0)
        costly = pred_data.get("costly_signal_count", 0)
        return f"consensus={consensus:.2f}, costly_signals={costly}"

    elif agent_name == "quant":
        ewma = pred_data.get("ewma", 0)
        vol = pred_data.get("volatility", 0)
        blend = pred_data.get("adaptive_blend", pred_data.get("blended", 0))
        return f"ewma={ewma:.3f}, vol={vol:.3f}, blend={blend:.2f}"

    return ""


def format_evaluation(scorecards):
    """Format the evaluation section from scorecards."""
    lines = []
    has_data = False

    for agent_name in AGENTS:
        sc = scorecards.get(agent_name)
        if not sc or sc.get("total_predictions", 0) == 0:
            continue

        has_data = True
        total = sc.get("total_predictions", 0)
        overall = sc.get("overall", {})
        mse = overall.get("mse", 0)
        dir_acc = overall.get("directional_accuracy", 0)
        pnl = sc.get("virtual_pnl", {}).get("total", 0)

        lines.append(f"  {agent_name:16s} predictions={total}, MSE={mse:.6f}, "
                     f"dir_acc={dir_acc:.1%}, P&L={pnl:+.1f}")

    if not has_data:
        lines.append("  (No matured predictions yet)")

    return "\n".join(lines)


def format_leaderboard(leaderboard):
    """Format the leaderboard section."""
    if not leaderboard:
        return "  (No leaderboard data)"

    lines = []
    rankings = leaderboard.get("rankings_by_mse", [])
    for entry in rankings:
        agent = entry.get("agent", "?")
        mse = entry.get("mse", 0)
        rank = entry.get("rank", "?")
        lines.append(f"  #{rank} {agent:20s} MSE={mse:.6f}")

    return "\n".join(lines)


def generate_report():
    """Generate the full cycle report."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Load data sources
    briefing = load_json("briefings/latest.json")
    leaderboard = load_json("scoreboard/latest.json")

    agent_logs = {}
    scorecards = {}
    for agent_name in AGENTS:
        agent_logs[agent_name] = get_latest_agent_log(agent_name)
        scorecards[agent_name] = load_json(os.path.join("agents", agent_name, "scorecard.json"))

    # Build report
    sections = []
    sections.append("=== Oracle Lab Cycle Report ===")
    sections.append(timestamp)

    if briefing:
        briefing_ts = briefing.get("timestamp", "unknown")
        sections.append(f"Briefing: {briefing_ts}")

    sections.append("")
    sections.append("── Market Snapshot ──")
    if briefing:
        sections.append(format_market_snapshot(briefing))
    else:
        sections.append("  (No briefing data)")

    sections.append("")
    sections.append("── Newswire ──")
    if briefing:
        sections.append(format_newswire(briefing))
    else:
        sections.append("  (No newswire data)")

    sections.append("")
    sections.append("── Forecasts ──")
    if briefing:
        sections.append(format_forecasts(briefing, agent_logs))
    else:
        sections.append("  (No forecast data)")

    sections.append("")
    sections.append("── Evaluation ──")
    sections.append(format_evaluation(scorecards))

    sections.append("")
    sections.append("── Leaderboard ──")
    sections.append(format_leaderboard(leaderboard))

    sections.append("")

    report = "\n".join(sections)

    # Save report
    os.makedirs(REPORTS_DIR, exist_ok=True)
    report_ts = timestamp.replace(":", "").replace("-", "")
    report_path = os.path.join(REPORTS_DIR, f"{report_ts}.txt")
    latest_path = os.path.join(REPORTS_DIR, "latest.txt")

    with open(report_path, "w") as f:
        f.write(report)
    with open(latest_path, "w") as f:
        f.write(report)

    print(f"[report] Saved to {report_path}")
    print(f"[report] Saved to {latest_path}")

    return report


if __name__ == "__main__":
    report = generate_report()
    print()
    print(report)
