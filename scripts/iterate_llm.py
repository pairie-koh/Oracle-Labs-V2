#!/usr/bin/env python3
"""Oracle Lab — LLM Forecast Iteration.

Reviews past LLM predictions vs outcomes, identifies patterns in mistakes,
and asks Sonnet to improve llm_forecast.py (prompts, parameters, reasoning approach).

Runs daily after agent iteration. Logs all changes to llm_iteration_log/.

Usage: python scripts/iterate_llm.py
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from constants import OPENROUTER_API_URL

ITERATION_MODEL = "anthropic/claude-sonnet-4"
LLM_FORECAST_PATH = os.path.join(PROJECT_ROOT, "llm_forecast.py")
ROLLING_SCORES_PATH = os.path.join(PROJECT_ROOT, "rolling_scores_history.csv")
LOG_DIR = os.path.join(PROJECT_ROOT, "llm_iteration_log")
MIN_SCORED_PREDICTIONS = 3  # Don't iterate until we have enough data


def call_openrouter(prompt, max_tokens=12000):
    """Call OpenRouter API."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    resp = requests.post(
        OPENROUTER_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/oracle-lab",
            "X-Title": "Oracle Lab LLM Iteration",
        },
        json={
            "model": ITERATION_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def load_rolling_scores():
    """Load and parse rolling_scores_history.csv."""
    if not os.path.exists(ROLLING_SCORES_PATH):
        return []

    import csv
    with open(ROLLING_SCORES_PATH) as f:
        rows = list(csv.DictReader(f))
    return rows


def build_performance_report(scores):
    """Build a human-readable performance report from scored predictions."""
    if not scores:
        return "No scored predictions yet."

    lines = []
    lines.append(f"Total scored predictions: {len(scores)}")
    lines.append("")

    # Per-contract breakdown
    by_contract = {}
    for r in scores:
        key = r.get("contract_name", r.get("contract_key", "unknown"))
        if key not in by_contract:
            by_contract[key] = {"total": 0, "correct": 0, "type": r.get("contract_type", ""), "errors": []}
        by_contract[key]["total"] += 1
        if r.get("correct") in (True, "True"):
            by_contract[key]["correct"] += 1
        try:
            se = float(r.get("squared_error", 0))
            by_contract[key]["errors"].append(se)
        except (ValueError, TypeError):
            pass

        # Store raw prediction vs outcome for analysis
        by_contract[key].setdefault("examples", []).append({
            "date": r.get("date", ""),
            "prediction": r.get("prediction", ""),
            "market_price": r.get("market_price", ""),
            "outcome": r.get("outcome", ""),
            "squared_error": r.get("squared_error", ""),
        })

    for contract, data in by_contract.items():
        avg_se = sum(data["errors"]) / len(data["errors"]) if data["errors"] else 0
        acc = data["correct"] / data["total"] if data["total"] > 0 else 0
        lines.append(f"Contract: {contract} ({data['type']})")
        lines.append(f"  Predictions: {data['total']}, Correct: {data['correct']}, Accuracy: {acc:.0%}")
        lines.append(f"  Avg Squared Error: {avg_se:.6f}")

        # Show last 3 examples
        for ex in data["examples"][-3:]:
            lines.append(f"  [{ex['date']}] pred={ex['prediction']} mkt={ex['market_price']} outcome={ex['outcome']} SE={ex['squared_error']}")
        lines.append("")

    # Overall stats
    all_correct = sum(1 for r in scores if r.get("correct") in (True, "True"))
    all_errors = []
    for r in scores:
        try:
            all_errors.append(float(r.get("squared_error", 0)))
        except (ValueError, TypeError):
            pass
    avg_error = sum(all_errors) / len(all_errors) if all_errors else 0

    lines.append(f"Overall accuracy: {all_correct}/{len(scores)} ({all_correct/len(scores):.0%})")
    lines.append(f"Overall avg squared error: {avg_error:.6f}")

    return "\n".join(lines)


def extract_code_block(response):
    """Extract the full llm_forecast.py from the response."""
    blocks = re.findall(r"```python\n(.*?)```", response, re.DOTALL)
    if not blocks:
        blocks = re.findall(r"```\n(.*?)```", response, re.DOTALL)
    if not blocks:
        return None
    return max(blocks, key=len)


def extract_change_summary(response):
    """Extract the change summary."""
    match = re.search(r"CHANGE_SUMMARY:\s*\n(.*?)(?:\n```|\Z)", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    before_code = response.split("```")[0]
    lines = [l.strip() for l in before_code.strip().split("\n") if l.strip()]
    if lines:
        return " ".join(lines[-5:])[:800]
    return "No summary provided."


def load_previous_changes():
    """Load summaries of previous iteration changes for context."""
    if not os.path.isdir(LOG_DIR):
        return "No previous iterations."

    logs = sorted(os.listdir(LOG_DIR))[-5:]  # Last 5 changes
    if not logs:
        return "No previous iterations."

    summaries = []
    for log_file in logs:
        path = os.path.join(LOG_DIR, log_file)
        try:
            with open(path) as f:
                summaries.append(f.read().strip())
        except Exception:
            pass

    return "\n\n---\n\n".join(summaries) if summaries else "No previous iterations."


def main():
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"=== LLM Forecast Iteration ({date_str}) ===")

    # Load scored predictions
    scores = load_rolling_scores()
    print(f"  Scored predictions: {len(scores)}")

    if len(scores) < MIN_SCORED_PREDICTIONS:
        print(f"  Need at least {MIN_SCORED_PREDICTIONS} scored predictions before iterating. Skipping.")
        return

    # Build performance report
    performance_report = build_performance_report(scores)
    print(f"  Performance report built ({len(performance_report)} chars)")

    # Read current llm_forecast.py
    with open(LLM_FORECAST_PATH) as f:
        current_code = f.read()
    print(f"  Current llm_forecast.py: {len(current_code)} chars")

    # Load previous changes for context
    previous_changes = load_previous_changes()

    # Build the iteration prompt
    prompt = f"""You are the AI researcher responsible for improving Oracle Lab's LLM forecasting system.

The system uses LLMs (Haiku for triage, Sonnet for deep dives) to predict outcomes on Polymarket prediction markets. Your job is to review how the system has been performing and make ONE targeted improvement to llm_forecast.py.

=== PERFORMANCE REPORT ===
{performance_report}

=== PREVIOUS ITERATION CHANGES ===
{previous_changes}

=== CURRENT llm_forecast.py ===
{current_code}

=== YOUR TASK ===

Review the performance data carefully. Look for:
1. Systematic biases — is the LLM consistently over/under-confident?
2. Per-contract patterns — which contracts does it get wrong and why?
3. Prompt weaknesses — are the prompts missing important reasoning instructions?
4. Parameter issues — is SHRINKAGE_KEEP too high/low? Are the tier thresholds right?
5. Missing context — should the prompts include more/different information?
6. Category-specific problems — does it fail on certain types of contracts?

Then make ONE specific, targeted change. Examples of good changes:
- Adjusting SHRINKAGE_KEEP based on observed overconfidence
- Adding a specific instruction to the prompt about a systematic mistake
- Improving how temporal context is used
- Adding a domain-specific reasoning hint for a contract type that's consistently wrong
- Fixing the adversarial prompt to better catch errors

Do NOT:
- Rewrite the entire file from scratch
- Make multiple unrelated changes at once
- Change the file structure or imports
- Remove existing functionality
- If the previous iteration made things worse, revert that specific change first

IMPORTANT: Respond in exactly this format:

CHANGE_SUMMARY:
[3-5 sentences explaining what you found in the performance data, what you changed, and why you expect it to help]

```python
[The COMPLETE updated llm_forecast.py file]
```"""

    print(f"  Calling {ITERATION_MODEL} for iteration...")
    try:
        response = call_openrouter(prompt, max_tokens=16000)
    except Exception as e:
        print(f"  ERROR calling OpenRouter: {e}")
        sys.exit(1)

    # Extract new code
    new_code = extract_code_block(response)
    if not new_code:
        print("  ERROR: Could not extract code block from response")
        print(f"  Response preview: {response[:500]}...")
        sys.exit(1)

    # Validate it looks like llm_forecast.py
    required = ["build_binary_prompt", "build_multi_outcome_prompt", "SHRINKAGE_KEEP", "MODELS"]
    missing = [r for r in required if r not in new_code]
    if missing:
        print(f"  ERROR: New code missing required elements: {missing}")
        sys.exit(1)

    # Write updated llm_forecast.py
    tmp_path = LLM_FORECAST_PATH + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            f.write(new_code)
        os.replace(tmp_path, LLM_FORECAST_PATH)
        print(f"  Updated llm_forecast.py")
    except OSError as e:
        print(f"  ERROR writing file: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        sys.exit(1)

    # Write change log
    os.makedirs(LOG_DIR, exist_ok=True)
    summary = extract_change_summary(response)
    log_path = os.path.join(LOG_DIR, f"{date_str}.md")
    with open(log_path, "w") as f:
        f.write(f"# LLM Forecast Iteration — {date_str}\n\n")
        f.write(summary + "\n")
    print(f"  Change log: {log_path}")
    print(f"\n  Summary: {summary[:200]}...")
    print("\n  Done.")


if __name__ == "__main__":
    main()
