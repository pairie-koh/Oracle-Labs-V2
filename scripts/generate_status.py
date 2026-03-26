"""
Oracle Lab — Status Page Generator
Reads scorecards, leaderboard, briefings, and agent logs to produce
a mobile-friendly static HTML dashboard at status/index.html.

Usage: python3 scripts/generate_status.py
"""

import csv
import glob
import html
import json
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")

PROJECT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
os.chdir(PROJECT_ROOT)

AGENTS = ["momentum", "historian", "game_theorist", "quant"]
AGENT_COLORS = {
    "momentum": "#e74c3c",
    "historian": "#3498db",
    "game_theorist": "#f39c12",
    "quant": "#2ecc71",
    "naive_baseline": "#888888",
}
AGENT_LABELS = {
    "momentum": "Momentum",
    "historian": "Historian",
    "game_theorist": "Game Theorist",
    "quant": "Quant",
}

# Cron schedule: 5 */4 * * * — cycles at 00:05, 04:05, 08:05, 12:05, 16:05, 20:05 UTC
CYCLE_HOURS = [0, 4, 8, 12, 16, 20]
CYCLE_MINUTE = 5


def load_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def get_latest_agent_logs(agent, n=2):
    """Return the last n log entries (newest first)."""
    log_dir = os.path.join("agents", agent, "log")
    files = sorted(glob.glob(os.path.join(log_dir, "*.json")))
    if not files:
        return []
    results = []
    for f in files[-n:]:
        data = load_json(f)
        if data:
            results.append(data)
    results.reverse()  # newest first
    return results


def get_latest_agent_log(agent):
    logs = get_latest_agent_logs(agent, 1)
    return logs[0] if logs else None


def get_latest_methodology_change(agent):
    changes_dir = os.path.join("agents", agent, "log", "methodology_changes")
    files = sorted(glob.glob(os.path.join(changes_dir, "*.md")))
    if not files:
        return None
    try:
        with open(files[-1], "r") as f:
            return f.read().strip()
    except IOError:
        return None


def compute_next_cycle(now):
    for hour in CYCLE_HOURS:
        candidate = now.replace(hour=hour, minute=CYCLE_MINUTE, second=0, microsecond=0)
        if candidate > now:
            return candidate
    # Next day, first cycle
    tomorrow = now + timedelta(days=1)
    return tomorrow.replace(hour=CYCLE_HOURS[0], minute=CYCLE_MINUTE, second=0, microsecond=0)


def time_ago(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        minutes = int(delta.total_seconds() / 60)
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h {minutes % 60}m ago"
        days = hours // 24
        return f"{days}d {hours % 24}h ago"
    except (ValueError, TypeError, AttributeError):
        return "unknown"


def sparkline_svg(values, color, width=120, height=30):
    if not values or len(values) < 2:
        return ""
    lo = min(values)
    hi = max(values)
    spread = hi - lo if hi != lo else 1
    points = []
    for i, v in enumerate(values):
        x = (i / (len(values) - 1)) * width
        y = height - ((v - lo) / spread) * (height - 4) - 2
        points.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(points)
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2" />'
        f'<circle cx="{points[-1].split(",")[0]}" cy="{points[-1].split(",")[1]}" '
        f'r="3" fill="{color}" />'
        f'</svg>'
    )


def count_forecast_logs():
    """Count total forecast log files across all agents."""
    total = 0
    for agent in AGENTS:
        log_dir = os.path.join("agents", agent, "log")
        total += len(glob.glob(os.path.join(log_dir, "*.json")))
    return total


def get_price_history_tail(n=30):
    """Get last n rows from prices.csv."""
    path = "price_history/prices.csv"
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows[-n:]


def delta_str(current, previous):
    """Format a delta between two numeric values."""
    if current is None or previous is None:
        return ""
    d = current - previous
    if d == 0:
        return '<span class="dim">unchanged</span>'
    cls = "up" if d > 0 else "down"
    return f'<span class="{cls}">{d:+.4f}</span>'


def build_agent_analysis(agent, current_log, prev_log, market_key="regime_fall"):
    """Build HTML for a single agent's detailed analysis card."""
    color = AGENT_COLORS[agent]
    label = AGENT_LABELS[agent]

    curr = current_log.get("predictions", {}).get(market_key, {}) if current_log else {}
    prev = prev_log.get("predictions", {}).get(market_key, {}) if prev_log else {}

    if not curr:
        return ""

    prediction = curr.get("prediction", 0)
    current_price = curr.get("current", 0)

    # Timestamp
    ts_raw = current_log.get("timestamp", "")
    ts_display = utc_to_pacific_str(ts_raw) if ts_raw else ""
    prev_ts_raw = prev_log.get("timestamp", "") if prev_log else ""
    prev_ts_display = utc_to_pacific_str(prev_ts_raw) if prev_ts_raw else ""

    prev_pred = prev.get("prediction") if prev else None
    pred_delta = ""
    if prev_pred is not None:
        d = prediction - prev_pred
        cls = "up" if d > 0 else "down" if d < 0 else ""
        pred_delta = f' <span class="{cls}">({d:+.4f} vs prev)</span>'

    version = current_log.get("methodology_version", "?")

    # Agent-specific metrics
    metrics_html = ""

    if agent == "momentum":
        rows = [
            ("Mode", curr.get("mode", "?"), prev.get("mode") if prev else None, "text"),
            ("News intensity", curr.get("decay_adjusted_intensity"), prev.get("decay_adjusted_intensity") if prev else None, ".3f"),
            ("Blend weight", curr.get("blend_weight"), prev.get("blend_weight") if prev else None, ".4f"),
            ("Momentum signal", curr.get("momentum_signal"), prev.get("momentum_signal") if prev else None, ".4f"),
            ("4h change", curr.get("change_4h"), prev.get("change_4h") if prev else None, "+.4f"),
            ("24h change", curr.get("change_24h"), prev.get("change_24h") if prev else None, "+.4f"),
        ]
    elif agent == "historian":
        rows = [
            ("Adaptive base rate", curr.get("adaptive_base_rate"), prev.get("adaptive_base_rate") if prev else None, ".4f"),
            ("Reversion pull", curr.get("reversion_pull"), prev.get("reversion_pull") if prev else None, ".4f"),
            ("Raw signal", curr.get("raw_signal"), prev.get("raw_signal") if prev else None, ".3f"),
            ("Capped shift", curr.get("capped_shift"), prev.get("capped_shift") if prev else None, "+.4f"),
        ]
    elif agent == "game_theorist":
        rows = [
            ("Fact count", curr.get("fact_count"), prev.get("fact_count") if prev else None, "d"),
            ("Escalatory", curr.get("escalatory_facts"), prev.get("escalatory_facts") if prev else None, "d"),
            ("De-escalatory", curr.get("deescalatory_facts"), prev.get("deescalatory_facts") if prev else None, "d"),
            ("Consensus ratio", curr.get("consensus_ratio"), prev.get("consensus_ratio") if prev else None, ".2f"),
            ("Costly signals", curr.get("costly_signal_count"), prev.get("costly_signal_count") if prev else None, "d"),
            ("Net signal", curr.get("net_signal"), prev.get("net_signal") if prev else None, ".3f"),
            ("Signal shift", curr.get("signal_shift"), prev.get("signal_shift") if prev else None, "+.4f"),
        ]
    elif agent == "quant":
        rows = [
            ("EWMA", curr.get("ewma"), prev.get("ewma") if prev else None, ".4f"),
            ("Long-term mean", curr.get("long_term_mean"), prev.get("long_term_mean") if prev else None, ".4f"),
            ("Volatility", curr.get("volatility"), prev.get("volatility") if prev else None, ".4f"),
            ("Adaptive blend", curr.get("adaptive_blend"), prev.get("adaptive_blend") if prev else None, ".4f"),
            ("News adjustment", curr.get("news_adjustment"), prev.get("news_adjustment") if prev else None, "+.4f"),
            ("Series length", curr.get("series_length"), prev.get("series_length") if prev else None, "d"),
        ]
    else:
        rows = []

    for label_text, val, prev_val, fmt in rows:
        if val is None:
            continue
        if fmt == "text":
            val_str = html.escape(str(val))
            if prev_val is not None and prev_val != val:
                delta = f' <span class="dim">(was: {html.escape(str(prev_val))})</span>'
            else:
                delta = ""
        elif fmt == "d":
            val_str = f"{int(val)}"
            if prev_val is not None:
                d = int(val) - int(prev_val)
                if d != 0:
                    cls = "up" if d > 0 else "down"
                    delta = f' <span class="{cls}">({d:+d})</span>'
                else:
                    delta = ' <span class="dim">(=)</span>'
            else:
                delta = ""
        else:
            val_str = f"{val:{fmt}}"
            if prev_val is not None:
                d = float(val) - float(prev_val)
                if abs(d) > 0.00005:
                    cls = "up" if d > 0 else "down"
                    delta = f' <span class="{cls}">({d:+.4f})</span>'
                else:
                    delta = ' <span class="dim">(=)</span>'
            else:
                delta = ""

        metrics_html += f"""
            <div class="analysis-metric">
                <span class="metric-label">{html.escape(label_text)}</span>
                <span class="metric-val">{val_str}{delta}</span>
            </div>"""

    return f"""
    <div class="analysis-card">
        <div class="analysis-header">
            <span class="dot" style="background:{color}"></span>
            <strong>{html.escape(label)}</strong>
            <span class="dim">v{html.escape(version)}</span>
        </div>
        <div class="analysis-pred">
            {current_price:.4f} &rarr; <strong>{prediction:.4f}</strong>{pred_delta}
        </div>
        <div class="analysis-time dim">{html.escape(ts_display)}{f' (prev: {html.escape(prev_ts_display)})' if prev_ts_display else ''}</div>
        <div class="analysis-metrics">{metrics_html}</div>
    </div>"""


def utc_to_pacific_str(iso_str):
    """Convert a UTC ISO string to a Pacific time display string."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        pt = dt.astimezone(PACIFIC)
        return pt.strftime("%b %d %I:%M %p PT")
    except (ValueError, TypeError, AttributeError):
        return iso_str


def generate_html():
    now = datetime.now(timezone.utc)
    now_pt = now.astimezone(PACIFIC)
    now_str = now_pt.strftime("%Y-%m-%d %I:%M %p PT")
    next_cycle = compute_next_cycle(now)
    next_cycle_pt = next_cycle.astimezone(PACIFIC)
    next_cycle_str = next_cycle_pt.strftime("%I:%M %p PT")
    minutes_until = int((next_cycle - now).total_seconds() / 60)

    # Load all data
    leaderboard = load_json("scoreboard/latest.json")
    briefing = load_json("briefings/latest.json")
    scorecards = {}
    agent_logs = {}
    agent_prev_logs = {}
    method_changes = {}
    for agent in AGENTS:
        scorecards[agent] = load_json(f"agents/{agent}/scorecard.json")
        recent = get_latest_agent_logs(agent, 2)
        agent_logs[agent] = recent[0] if recent else None
        agent_prev_logs[agent] = recent[1] if len(recent) > 1 else None
        method_changes[agent] = get_latest_methodology_change(agent)

    # --- Header ---
    briefing_ts_raw = briefing.get("timestamp", "unknown") if briefing else "unknown"
    briefing_ts = utc_to_pacific_str(briefing_ts_raw) if briefing else "unknown"
    last_cycle_ago = time_ago(briefing_ts_raw) if briefing else "never"

    total_scored = sum(
        (sc.get("total_predictions", 0) if sc else 0) for sc in scorecards.values()
    )
    total_forecasts = count_forecast_logs()

    header_html = f"""
    <div class="header">
        <h1>Oracle Lab</h1>
        <div class="meta">
            <span>Last cycle: <strong>{html.escape(briefing_ts)}</strong> ({last_cycle_ago})</span>
            <span>Next cycle: <strong>{next_cycle_str}</strong> ({minutes_until}m)</span>
            <span>Scored: <strong>{total_scored}</strong> predictions | Logged: <strong>{total_forecasts}</strong> forecasts</span>
        </div>
    </div>"""

    # --- Leaderboard ---
    leaderboard_rows = ""
    if leaderboard:
        for entry in leaderboard.get("rankings_by_mse", []):
            agent = entry.get("agent", "?")
            mse = entry.get("mse", 0)
            rank = entry.get("rank", "?")
            color = AGENT_COLORS.get(agent, "#888")
            label = AGENT_LABELS.get(agent, agent.replace("_", " ").title())
            is_naive = agent == "naive_baseline"

            # Find directional accuracy
            dir_acc = ""
            if not is_naive:
                sc = scorecards.get(agent)
                if sc:
                    da = sc.get("overall", {}).get("directional_accuracy")
                    if da is not None:
                        dir_acc = f"{da:.0%}"
                    version = sc.get("methodology_version", "?")
                else:
                    version = "?"
            else:
                version = ""

            row_class = "naive-row" if is_naive else ""
            badge = ""
            if not is_naive and leaderboard:
                # Check if beating naive
                naive_mse = None
                for e in leaderboard.get("rankings_by_mse", []):
                    if e["agent"] == "naive_baseline":
                        naive_mse = e.get("mse")
                if naive_mse and mse < naive_mse:
                    badge = ' <span class="badge good">beating naive</span>'

            leaderboard_rows += f"""
            <tr class="{row_class}">
                <td>#{rank}</td>
                <td><span class="dot" style="background:{color}"></span> {html.escape(label)}{badge}</td>
                <td>{mse:.6f}</td>
                <td>{dir_acc}</td>
                <td class="dim">{html.escape(str(version))}</td>
            </tr>"""
    else:
        leaderboard_rows = '<tr><td colspan="5" class="dim">Awaiting first scored cycle</td></tr>'

    leaderboard_html = f"""
    <div class="section">
        <h2>Leaderboard</h2>
        <table>
            <thead><tr><th>#</th><th>Agent</th><th>MSE</th><th>Dir Acc</th><th>Version</th></tr></thead>
            <tbody>{leaderboard_rows}</tbody>
        </table>
    </div>"""

    # --- Latest Forecasts ---
    forecasts_html = ""
    if briefing:
        for market_key, market_data in briefing.get("market_prices", {}).items():
            current = market_data.get("current", 0)
            change_4h = market_data.get("change_4h", 0)
            change_24h = market_data.get("change_24h", 0)
            market_name = market_key.replace("_", " ").title()

            agent_rows = ""
            for agent in AGENTS:
                log = agent_logs.get(agent)
                if not log:
                    continue
                pred_data = log.get("predictions", {}).get(market_key, {})
                if not pred_data:
                    continue
                prediction = pred_data.get("prediction", 0)
                delta = prediction - current
                color = AGENT_COLORS[agent]
                label = AGENT_LABELS[agent]
                delta_class = "up" if delta > 0 else "down" if delta < 0 else ""
                agent_rows += f"""
                <div class="forecast-row">
                    <span class="dot" style="background:{color}"></span>
                    <span class="agent-name">{label}</span>
                    <span class="pred">{prediction:.4f}</span>
                    <span class="delta {delta_class}">{delta:+.4f}</span>
                </div>"""

            sign_4h = "+" if change_4h >= 0 else ""
            sign_24h = "+" if change_24h >= 0 else ""
            forecasts_html += f"""
            <div class="market-block">
                <div class="market-header">
                    <strong>{html.escape(market_name)}</strong>
                    <span class="current-price">{current:.4f}</span>
                </div>
                <div class="price-changes">
                    4h: <span class="{'up' if change_4h > 0 else 'down' if change_4h < 0 else ''}">{sign_4h}{change_4h:.4f}</span>
                    &nbsp; 24h: <span class="{'up' if change_24h > 0 else 'down' if change_24h < 0 else ''}">{sign_24h}{change_24h:.4f}</span>
                </div>
                {agent_rows}
            </div>"""
    else:
        forecasts_html = '<p class="dim">Awaiting first briefing</p>'

    forecasts_section = f"""
    <div class="section">
        <h2>Latest Forecasts</h2>
        {forecasts_html}
    </div>"""

    # --- Agent Analysis ---
    analysis_cards = ""
    for agent in AGENTS:
        analysis_cards += build_agent_analysis(
            agent, agent_logs.get(agent), agent_prev_logs.get(agent)
        )

    if not analysis_cards:
        analysis_cards = '<p class="dim">Awaiting first forecasts</p>'

    analysis_section = f"""
    <div class="section">
        <h2>Agent Analysis <span class="dim">(vs previous cycle)</span></h2>
        {analysis_cards}
    </div>"""

    # --- MSE Trend ---
    trend_html = ""
    for agent in AGENTS:
        sc = scorecards.get(agent)
        if not sc:
            continue
        trend = sc.get("mse_trend_last_5", [])
        color = AGENT_COLORS[agent]
        label = AGENT_LABELS[agent]
        svg = sparkline_svg(trend, color)
        current_mse = trend[-1] if trend else None
        mse_str = f"{current_mse:.6f}" if current_mse is not None else "N/A"

        trend_html += f"""
        <div class="trend-row">
            <span class="dot" style="background:{color}"></span>
            <span class="agent-name">{label}</span>
            <span class="trend-sparkline">{svg}</span>
            <span class="trend-val">{mse_str}</span>
        </div>"""

    trend_section = f"""
    <div class="section">
        <h2>MSE Trend <span class="dim">(last 5 cycles)</span></h2>
        {trend_html if trend_html else '<p class="dim">No scored cycles yet</p>'}
    </div>"""

    # --- Progress Plot ---
    plot_exists = os.path.exists("status/progress.png")
    # Cache-bust with timestamp
    cache_bust = int(now.timestamp())
    plot_section = ""
    if plot_exists:
        plot_section = f"""
    <div class="section">
        <h2>Accuracy Plot</h2>
        <img src="progress.png?v={cache_bust}" alt="Progress plot"
             style="width:100%; border-radius:8px; margin-top:8px;">
    </div>"""

    # --- Virtual P&L ---
    pnl_html = ""
    for agent in AGENTS:
        sc = scorecards.get(agent)
        if not sc:
            continue
        pnl = sc.get("virtual_pnl", {})
        total = pnl.get("total", 0)
        trades = pnl.get("trades", 0)
        wins = pnl.get("wins", 0)
        losses = pnl.get("losses", 0)
        if trades == 0:
            continue
        color = AGENT_COLORS[agent]
        label = AGENT_LABELS[agent]
        pnl_class = "up" if total > 0 else "down" if total < 0 else ""
        pnl_html += f"""
        <div class="pnl-row">
            <span class="dot" style="background:{color}"></span>
            <span class="agent-name">{label}</span>
            <span class="pnl-val {pnl_class}">${total:+.0f}</span>
            <span class="dim">{wins}W/{losses}L ({trades} trades)</span>
        </div>"""

    pnl_section = f"""
    <div class="section">
        <h2>Virtual P&L</h2>
        {pnl_html if pnl_html else '<p class="dim">No trades yet</p>'}
    </div>"""

    # --- News Summary ---
    news_html = ""
    if briefing:
        facts = briefing.get("fresh_facts", [])
        n_facts = len(facts)
        escalation_cats = {"military_pressure", "economic_collapse", "internal_stability"}
        deescalation_cats = {"diplomatic_signals", "international_response"}
        esc = sum(1 for f in facts if f.get("indicator_category") in escalation_cats)
        deesc = sum(1 for f in facts if f.get("indicator_category") in deescalation_cats)
        neutral = n_facts - esc - deesc

        if n_facts > 0:
            news_html = f"""
            <div class="news-summary">
                <strong>{n_facts}</strong> facts:
                <span class="esc">{esc} escalatory</span>,
                <span class="deesc">{deesc} de-escalatory</span>,
                {neutral} neutral
            </div>"""
            # Top 3 claims
            for fact in facts[:3]:
                claim = html.escape(fact.get("claim", "")[:100])
                cat = html.escape(fact.get("indicator_category", ""))
                conf = fact.get("confidence", "")
                news_html += f'<div class="fact"><span class="dim">[{cat}]</span> {claim}</div>'
        else:
            news_html = '<p class="dim">No fresh facts this cycle</p>'
    else:
        news_html = '<p class="dim">Awaiting first newswire</p>'

    news_section = f"""
    <div class="section">
        <h2>Newswire</h2>
        {news_html}
    </div>"""

    # --- Iteration Status ---
    iter_status = load_json("status/iteration_status.json")
    iter_html = ""

    if iter_status:
        last_date = iter_status.get("date", "?")
        last_ts = iter_status.get("timestamp", "")
        overall = iter_status.get("status", "?")
        last_ts_display = utc_to_pacific_str(last_ts) if last_ts else last_date
        last_ago = time_ago(last_ts) if last_ts else ""

        # Status badge
        status_class = {"ok": "iter-ok", "partial": "iter-partial", "failed": "iter-failed", "running": "iter-running"}.get(overall, "iter-failed")
        status_label = {"ok": "ALL OK", "partial": "PARTIAL", "failed": "FAILED", "running": "RUNNING"}.get(overall, overall.upper())

        iter_html += f"""
        <div class="iter-summary">
            <span class="iter-badge {status_class}">{status_label}</span>
            <span>{html.escape(last_ts_display)}</span>
            <span class="dim">({last_ago})</span>
        </div>"""

        # Per-agent results
        agents_data = iter_status.get("agents", {})
        for agent in AGENTS:
            ad = agents_data.get(agent)
            if not ad:
                continue
            color = AGENT_COLORS[agent]
            label = AGENT_LABELS[agent]
            result = ad.get("result", "?")
            duration = ad.get("duration_seconds", 0)
            v_before = ad.get("version_before", "?")
            v_after = ad.get("version_after", "?")
            version_changed = v_before != v_after and v_after != "?"

            result_icon = {"ok": "&#x2705;", "timeout": "&#x23F0;", "failed": "&#x274C;"}.get(result, "&#x2753;")
            version_str = f"v{html.escape(v_before)} &rarr; v{html.escape(v_after)}" if version_changed else f"v{html.escape(v_before)} (unchanged)"

            iter_html += f"""
            <div class="iter-agent-row">
                <span class="dot" style="background:{color}"></span>
                <span class="agent-name">{label}</span>
                <span>{result_icon} {result}</span>
                <span class="dim">{duration}s</span>
                <span class="dim">{version_str}</span>
            </div>"""

        # Methodology change notes
        for agent in AGENTS:
            change = method_changes.get(agent)
            if change:
                color = AGENT_COLORS[agent]
                label = AGENT_LABELS[agent]
                escaped = html.escape(change)
                iter_html += f"""
                <div class="iter-change-note">
                    <span class="dot" style="background:{color}"></span>
                    <strong>{html.escape(label)}</strong>
                    <div class="iter-text">{escaped}</div>
                </div>"""

        # History (last 7 days)
        history = iter_status.get("history", [])
        if history:
            hist_cells = ""
            for entry in history[:7]:
                h_date = entry.get("date", "?")
                h_status = entry.get("status", "?")
                h_class = {"ok": "iter-ok", "partial": "iter-partial", "failed": "iter-failed"}.get(h_status, "iter-failed")
                h_label = {"ok": "OK", "partial": "PARTIAL", "failed": "FAIL"}.get(h_status, "?")
                h_agents = entry.get("agents", {})
                h_details = ", ".join(
                    f"{AGENT_LABELS.get(a, a)[:3]}:{'OK' if d.get('result') == 'ok' else 'FAIL'}"
                    for a, d in h_agents.items()
                )
                hist_cells += f"""
                <div class="hist-cell">
                    <div class="hist-date">{html.escape(h_date[-5:])}</div>
                    <div class="iter-badge {h_class}" style="font-size:10px">{h_label}</div>
                    <div class="dim" style="font-size:9px">{html.escape(h_details)}</div>
                </div>"""

            iter_html += f"""
            <div class="iter-history">
                <div class="dim" style="margin-bottom:6px">Recent iterations:</div>
                <div class="hist-row">{hist_cells}</div>
            </div>"""
    else:
        iter_html = '<p class="dim">No iteration data — iterations have not run yet</p>'

    iter_section = f"""
    <div class="section">
        <h2>Daily Iteration</h2>
        {iter_html}
    </div>"""

    # --- State Summary ---
    state_html = ""
    if briefing:
        state = briefing.get("state", {})
        markets_state = state.get("markets", {})
        for mk, ms in markets_state.items():
            status = html.escape(ms.get("current_status", "")[:200])
            indicators = []
            for key in ["military_pressure", "internal_stability", "succession_dynamics",
                        "diplomatic_signals", "economic_collapse", "international_response"]:
                val = ms.get(key, "")
                if val:
                    level_class = ""
                    if val in ("critical", "high"):
                        level_class = "level-high"
                    elif val == "moderate":
                        level_class = "level-mod"
                    elif val in ("low", "none"):
                        level_class = "level-low"
                    indicators.append(
                        f'<span class="indicator {level_class}">{key.replace("_", " ")}: {val}</span>'
                    )
            state_html += f"""
            <div class="state-block">
                <div class="dim">{html.escape(mk.replace('_', ' ').title())}</div>
                <div class="state-status">{status}</div>
                <div class="indicators">{''.join(indicators)}</div>
            </div>"""

    state_section = f"""
    <div class="section">
        <h2>Situation State</h2>
        {state_html if state_html else '<p class="dim">No state data</p>'}
    </div>"""

    # --- Assemble full HTML ---
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="900">
    <title>Oracle Lab</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: #0f0f1a;
            color: #e0e0e0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
            font-size: 14px;
            line-height: 1.5;
        }}
        .container {{ max-width: 640px; margin: 0 auto; padding: 16px; }}
        .header {{ padding: 20px 0 12px; border-bottom: 1px solid #2a2a3e; margin-bottom: 16px; }}
        .header h1 {{ font-size: 22px; color: #fff; margin-bottom: 8px; letter-spacing: 1px; }}
        .meta {{ display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: #888; }}
        .meta strong {{ color: #bbb; }}
        .section {{ margin-bottom: 24px; }}
        .section h2 {{
            font-size: 13px; text-transform: uppercase; letter-spacing: 1.5px;
            color: #666; margin-bottom: 10px; padding-bottom: 4px;
            border-bottom: 1px solid #1e1e30;
        }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th {{ text-align: left; color: #666; font-weight: 500; padding: 4px 8px; font-size: 11px; text-transform: uppercase; }}
        td {{ padding: 6px 8px; border-top: 1px solid #1a1a2e; }}
        .naive-row td {{ color: #666; font-style: italic; }}
        .dot {{
            display: inline-block; width: 8px; height: 8px; border-radius: 50%;
            margin-right: 6px; vertical-align: middle;
        }}
        .badge {{
            font-size: 10px; padding: 1px 6px; border-radius: 3px;
            margin-left: 6px; vertical-align: middle;
        }}
        .badge.good {{ background: #1a3a1a; color: #4caf50; }}
        .dim {{ color: #555; }}
        .up {{ color: #4caf50; }}
        .down {{ color: #e74c3c; }}
        .market-block {{ margin-bottom: 16px; padding: 12px; background: #16162a; border-radius: 8px; }}
        .market-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
        .current-price {{ font-size: 20px; font-weight: 700; color: #fff; font-family: "SF Mono", "Fira Code", monospace; }}
        .price-changes {{ font-size: 12px; color: #888; margin-bottom: 10px; }}
        .forecast-row {{
            display: flex; align-items: center; gap: 8px; padding: 4px 0;
            font-family: "SF Mono", "Fira Code", monospace; font-size: 13px;
        }}
        .forecast-row .agent-name {{ width: 100px; font-family: -apple-system, sans-serif; }}
        .forecast-row .pred {{ color: #fff; }}
        .forecast-row .delta {{ font-size: 12px; }}
        .trend-row {{ display: flex; align-items: center; gap: 8px; padding: 6px 0; }}
        .trend-row .agent-name {{ width: 100px; font-size: 13px; }}
        .trend-sparkline {{ flex: 1; }}
        .trend-val {{ font-family: "SF Mono", monospace; font-size: 12px; color: #aaa; }}
        .pnl-row {{ display: flex; align-items: center; gap: 8px; padding: 4px 0; }}
        .pnl-row .agent-name {{ width: 100px; font-size: 13px; }}
        .pnl-val {{ font-family: "SF Mono", monospace; font-weight: 700; }}
        .news-summary {{ margin-bottom: 8px; }}
        .esc {{ color: #e74c3c; }}
        .deesc {{ color: #4caf50; }}
        .fact {{ font-size: 12px; color: #999; padding: 3px 0; border-top: 1px solid #1a1a2e; }}
        .iter-row {{ margin-bottom: 12px; }}
        .iter-text {{ font-size: 12px; color: #999; margin-top: 4px; white-space: pre-wrap; }}
        .state-block {{ padding: 10px; background: #16162a; border-radius: 8px; margin-bottom: 8px; }}
        .state-status {{ font-size: 12px; color: #bbb; margin: 6px 0; }}
        .indicators {{ display: flex; flex-wrap: wrap; gap: 6px; }}
        .indicator {{
            font-size: 11px; padding: 2px 8px; border-radius: 4px;
            background: #1e1e30; color: #888;
        }}
        .level-high {{ background: #3a1a1a; color: #e74c3c; }}
        .level-mod {{ background: #3a2a1a; color: #f39c12; }}
        .level-low {{ background: #1a3a1a; color: #4caf50; }}
        .analysis-card {{
            background: #16162a; border-radius: 8px; padding: 12px; margin-bottom: 12px;
            border-left: 3px solid #333;
        }}
        .analysis-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
        .analysis-pred {{
            font-family: "SF Mono", "Fira Code", monospace; font-size: 15px;
            margin-bottom: 4px;
        }}
        .analysis-time {{ font-size: 11px; margin-bottom: 8px; }}
        .analysis-metrics {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2px 12px; }}
        .analysis-metric {{
            display: flex; justify-content: space-between; font-size: 12px;
            padding: 2px 0; border-bottom: 1px solid #1a1a2a;
        }}
        .metric-label {{ color: #777; }}
        .metric-val {{ font-family: "SF Mono", monospace; color: #ccc; text-align: right; }}
        .iter-summary {{ display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }}
        .iter-badge {{
            display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 8px;
            border-radius: 4px; letter-spacing: 0.5px;
        }}
        .iter-ok {{ background: #1a3a1a; color: #4caf50; }}
        .iter-partial {{ background: #3a2a1a; color: #f39c12; }}
        .iter-failed {{ background: #3a1a1a; color: #e74c3c; }}
        .iter-running {{ background: #1a2a3a; color: #3498db; }}
        .iter-agent-row {{
            display: flex; align-items: center; gap: 8px; padding: 4px 0;
            font-size: 13px; border-bottom: 1px solid #1a1a2e;
        }}
        .iter-agent-row .agent-name {{ width: 100px; }}
        .iter-change-note {{ margin: 10px 0 6px; }}
        .iter-history {{ margin-top: 14px; }}
        .hist-row {{ display: flex; gap: 6px; flex-wrap: wrap; }}
        .hist-cell {{
            background: #16162a; border-radius: 6px; padding: 6px 8px;
            text-align: center; min-width: 70px;
        }}
        .hist-date {{ font-size: 11px; color: #888; margin-bottom: 2px; }}
        .footer {{ text-align: center; color: #444; font-size: 11px; padding: 20px 0; border-top: 1px solid #1e1e30; }}
    </style>
</head>
<body>
    <div class="container">
        {header_html}
        {leaderboard_html}
        {iter_section}
        {forecasts_section}
        {analysis_section}
        {trend_section}
        {plot_section}
        {pnl_section}
        {news_section}
        {state_section}
        <div class="footer">
            Generated {html.escape(now_str)} &middot; Auto-refreshes every 15 min
        </div>
    </div>
</body>
</html>"""

    os.makedirs("status", exist_ok=True)
    with open("status/index.html", "w") as f:
        f.write(page)
    print(f"[status] Generated status/index.html at {now_str}")


if __name__ == "__main__":
    generate_html()
