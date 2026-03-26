"""
Oracle Lab — Progress Plot (Karpathy-style)
Reads scores_history.csv (live) or backtest_results.csv (backtest) and generates
a progress.png showing agent performance over time.

Usage:
    python3 scripts/plot_progress.py              # live scores
    python3 scripts/plot_progress.py --backtest   # backtest data
"""

import os
import sys
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIVE_CSV = os.path.join(PROJECT_ROOT, "scores_history.csv")
BACKTEST_CSV = os.path.join(PROJECT_ROOT, "backtest_results.csv")
OUTPUT_PNG = os.path.join(PROJECT_ROOT, "progress.png")

AGENT_COLORS = {
    "momentum":       "#e74c3c",
    "historian":      "#3498db",
    "game_theorist":  "#f39c12",
    "quant":          "#2ecc71",
    "naive_baseline": "#999999",
}

AGENT_LABELS = {
    "momentum":       "Momentum",
    "historian":      "Historian",
    "game_theorist":  "Game Theorist",
    "quant":          "Quant",
    "naive_baseline": "Naive (no change)",
}

AGENTS = ["momentum", "historian", "game_theorist", "quant"]


def load_live_data():
    """Load scores_history.csv into a DataFrame with datetime index."""
    df = pd.read_csv(LIVE_CSV)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = df.sort_values("datetime").reset_index(drop=True)
    # Assign sequential cycle numbers per agent for rolling calculations
    for agent in AGENTS + ["naive_baseline"]:
        mask = df["agent"] == agent
        df.loc[mask, "cycle"] = range(mask.sum())
    return df


def load_backtest_data():
    """Load backtest_results.csv (legacy format)."""
    df = pd.read_csv(BACKTEST_CSV)
    df["datetime"] = pd.RangeIndex(len(df))  # no real timestamps
    return df


def plot(df, use_time_axis=True):
    """Generate the two-panel Karpathy-style plot."""
    n_points = len(df[df["agent"].isin(AGENTS)])
    n_agents_with_data = sum(1 for a in AGENTS if len(df[df["agent"] == a]) > 0)

    if n_points == 0:
        print("No scored predictions yet. Nothing to plot.")
        return

    # Adaptive rolling window: 20% of data points, min 3, max 20
    per_agent = n_points // max(n_agents_with_data, 1)
    rolling_window = max(3, min(20, per_agent // 5))
    min_periods = max(2, rolling_window // 3)

    x_col = "datetime" if use_time_axis else "cycle"

    fig, axes = plt.subplots(2, 1, figsize=(16, 12), height_ratios=[3, 1],
                              gridspec_kw={"hspace": 0.30})
    fig.patch.set_facecolor("#fafafa")

    # ── Top panel: Squared Error scatter + rolling MSE ─────────────────────
    ax = axes[0]
    ax.set_facecolor("#fafafa")

    # Naive baseline band
    naive = df[df["agent"] == "naive_baseline"].sort_values(x_col)
    if len(naive) >= min_periods:
        naive_rolling = naive["squared_error"].rolling(rolling_window, min_periods=min_periods).mean()
        ax.fill_between(naive[x_col], 0, naive_rolling,
                        color="#eeeeee", alpha=0.6, zorder=1)
        ax.plot(naive[x_col], naive_rolling,
                color="#999999", linewidth=1.5, alpha=0.7, zorder=2,
                label="Naive baseline (rolling MSE)")

    # Each agent
    for agent in AGENTS:
        agent_df = df[df["agent"] == agent].sort_values(x_col)
        if len(agent_df) == 0:
            continue
        color = AGENT_COLORS[agent]
        label = AGENT_LABELS[agent]

        # Individual points
        ax.scatter(agent_df[x_col], agent_df["squared_error"],
                   c=color, s=12, alpha=0.2, zorder=3)

        # Rolling MSE line
        if len(agent_df) >= min_periods:
            rolling_mse = agent_df["squared_error"].rolling(rolling_window, min_periods=min_periods).mean()
            ax.plot(agent_df[x_col].values, rolling_mse.values,
                    color=color, linewidth=2.5, alpha=0.85, zorder=4, label=label)

    # Methodology version changes (vertical lines)
    for agent in AGENTS:
        agent_df = df[df["agent"] == agent].sort_values(x_col)
        if len(agent_df) < 2:
            continue
        versions = agent_df["methodology_version"]
        changes = versions.ne(versions.shift())
        change_points = agent_df[changes & (agent_df.index != agent_df.index[0])]
        for _, row in change_points.iterrows():
            ax.axvline(x=row[x_col], color=AGENT_COLORS[agent],
                       linewidth=0.8, linestyle=":", alpha=0.4, zorder=1)

    # Big price moves
    if len(naive) > 0 and "current_price" in naive.columns:
        price_changes = naive[["datetime" if use_time_axis else "cycle", "current_price", "actual"]].copy()
        price_changes["abs_change"] = (price_changes["actual"] - price_changes["current_price"]).abs()
        big_moves = price_changes[price_changes["abs_change"] > 0.03]
        for _, row in big_moves.iterrows():
            ax.axvline(x=row[x_col], color="#dddddd", linewidth=0.8, linestyle="--", zorder=1)

    # Stats
    best_agent = min(AGENTS, key=lambda a: df[df["agent"] == a]["squared_error"].mean()
                     if len(df[df["agent"] == a]) > 0 else float("inf"))
    best_mse = df[df["agent"] == best_agent]["squared_error"].mean()
    naive_mse = naive["squared_error"].mean() if len(naive) > 0 else float("nan")
    total_scored = per_agent

    ax.set_ylabel("Squared Error (lower is better)", fontsize=12)
    ax.set_title(
        f"Oracle Lab Agent Performance — {total_scored} Scored Predictions per Agent\n"
        f"Best: {AGENT_LABELS[best_agent]} (MSE={best_mse:.6f}) vs Naive (MSE={naive_mse:.6f})",
        fontsize=14
    )
    ax.legend(loc="upper right", fontsize=9, framealpha=0.9)
    ax.grid(True, alpha=0.15)

    # Cap y-axis
    agent_se = df[df["agent"].isin(AGENTS)]["squared_error"]
    if len(agent_se) > 0:
        p95 = agent_se.quantile(0.95)
        ax.set_ylim(-0.0001, min(p95 * 2.5, 0.02))

    # ── Bottom panel: Price tracking ──────────────────────────────────────
    ax2 = axes[1]
    ax2.set_facecolor("#fafafa")

    if len(naive) > 0:
        ax2.plot(naive[x_col], naive["actual"],
                 color="black", linewidth=1.8, alpha=0.8, label="Actual price (T+4h)", zorder=5)

    for agent in AGENTS:
        agent_df = df[df["agent"] == agent].sort_values(x_col)
        if len(agent_df) == 0:
            continue
        color = AGENT_COLORS[agent]
        label = AGENT_LABELS[agent]

        # Raw predictions as faint dots
        ax2.scatter(agent_df[x_col], agent_df["predicted"],
                    c=color, s=6, alpha=0.3, zorder=3)

        # Smoothed prediction line
        if len(agent_df) >= min_periods:
            pred_smooth = agent_df["predicted"].rolling(rolling_window, min_periods=min_periods).mean()
            ax2.plot(agent_df[x_col].values, pred_smooth.values,
                     color=color, linewidth=1.5, alpha=0.7, zorder=4, label=label)

    ax2.set_ylabel("Price", fontsize=12)
    ax2.set_title("Price Tracking: Actual vs Agent Predictions", fontsize=12)
    ax2.legend(loc="upper left", fontsize=8, ncol=3, framealpha=0.9)
    ax2.grid(True, alpha=0.15)

    # Format x-axis
    if use_time_axis:
        for a in [ax, ax2]:
            a.xaxis.set_major_formatter(mdates.DateFormatter("%b %d\n%H:%M"))
            a.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax2.set_xlabel("Time (UTC)", fontsize=12)
    else:
        ax2.set_xlabel("Cycle #", fontsize=12)

    plt.savefig(OUTPUT_PNG, dpi=150, bbox_inches="tight")
    print(f"Saved to {OUTPUT_PNG} ({total_scored} predictions/agent, rolling window={rolling_window})")


def main():
    backtest = "--backtest" in sys.argv

    if backtest:
        if not os.path.exists(BACKTEST_CSV):
            print(f"No backtest data at {BACKTEST_CSV}")
            sys.exit(1)
        df = load_backtest_data()
        plot(df, use_time_axis=False)
    else:
        if not os.path.exists(LIVE_CSV):
            print(f"No live scores at {LIVE_CSV} — run a few forecast cycles first.")
            sys.exit(1)
        df = load_live_data()
        plot(df, use_time_axis=True)


if __name__ == "__main__":
    main()
