#!/usr/bin/env python3
"""Oracle Lab — LLM Forecast Iteration.

Reviews past LLM predictions vs outcomes, identifies patterns in mistakes,
and asks Sonnet to improve llm_forecast.py (prompts, parameters, reasoning approach).

Uses a search-and-replace approach: Sonnet returns the specific old text to find
and new text to replace it with, rather than outputting the entire file.

Features:
- Before/after performance tracking to measure iteration impact
- Auto-revert if last iteration degraded performance
- LLM reasoning excerpts included in performance report
- Persistent experiment log tracking what was tried and results
- "No change" option when performance is improving

Runs daily after agent iteration. Logs all changes to llm_iteration_log/.

Usage: python scripts/iterate_llm.py
"""

import csv
import glob
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
EXPERIMENT_LOG_PATH = os.path.join(LOG_DIR, "experiment_log.json")
PREDICTIONS_DIR = os.path.join(PROJECT_ROOT, "llm_predictions")
MIN_SCORED_PREDICTIONS = 20  # Need meaningful data before iterating


def call_openrouter(prompt, max_tokens=4000):
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

    with open(ROLLING_SCORES_PATH) as f:
        rows = list(csv.DictReader(f))
    return rows


def load_experiment_log():
    """Load the persistent experiment log."""
    if not os.path.exists(EXPERIMENT_LOG_PATH):
        return []
    try:
        with open(EXPERIMENT_LOG_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_experiment_log(log):
    """Save the persistent experiment log."""
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(EXPERIMENT_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)


def get_last_iteration_date():
    """Get the date of the last iteration from log files."""
    if not os.path.isdir(LOG_DIR):
        return None
    logs = sorted(f for f in os.listdir(LOG_DIR) if f.endswith(".md"))
    if not logs:
        return None
    # Filename format: 2026-03-30.md
    return logs[-1].replace(".md", "")


def compute_before_after_performance(scores, split_date):
    """Split scores into before/after a date and compute avg SE for each.

    Returns (before_avg_se, after_avg_se, before_count, after_count).
    """
    before_errors = []
    after_errors = []

    for r in scores:
        ts = r.get("timestamp", "")
        try:
            se = float(r.get("squared_error", 0))
        except (ValueError, TypeError):
            continue

        # Compare the date portion of the timestamp
        row_date = ts[:10] if ts else ""
        if row_date < split_date:
            before_errors.append(se)
        else:
            after_errors.append(se)

    before_avg = sum(before_errors) / len(before_errors) if before_errors else None
    after_avg = sum(after_errors) / len(after_errors) if after_errors else None

    return before_avg, after_avg, len(before_errors), len(after_errors)


def load_reasoning_excerpts():
    """Load reasoning excerpts from recent prediction files.

    Returns a list of dicts with contract key, reasoning snippet, prediction, etc.
    """
    excerpts = []
    pred_files = sorted(glob.glob(os.path.join(PREDICTIONS_DIR, "predictions_*.json")))

    # Only look at last 5 prediction files
    for path in pred_files[-5:]:
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        for pred in data.get("predictions", []):
            reasoning = pred.get("reasoning_excerpt", "")
            if not reasoning:
                continue

            excerpts.append({
                "key": pred.get("key", ""),
                "type": pred.get("type", ""),
                "tier": pred.get("tier", ""),
                "timestamp": pred.get("timestamp", ""),
                "reasoning": reasoning[:300],  # Keep it concise
            })

    return excerpts


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

    # Edge vs market (if column exists)
    edges = []
    for r in scores:
        try:
            e = float(r.get("edge_vs_market", ""))
            edges.append(e)
        except (ValueError, TypeError):
            pass
    if edges:
        avg_edge = sum(edges) / len(edges)
        lines.append(f"Avg edge vs market: {avg_edge:+.6f} ({'BEATING' if avg_edge > 0 else 'LOSING TO'} market)")
        lines.append("  (positive = our SE < market SE = we add value)")

    # Before/after comparison if we have a previous iteration
    last_date = get_last_iteration_date()
    if last_date:
        before_avg, after_avg, before_n, after_n = compute_before_after_performance(scores, last_date)
        lines.append("")
        lines.append(f"=== BEFORE/AFTER LAST ITERATION ({last_date}) ===")
        if before_avg is not None:
            lines.append(f"  Before: avg SE = {before_avg:.6f} ({before_n} predictions)")
        else:
            lines.append(f"  Before: no data")
        if after_avg is not None:
            lines.append(f"  After: avg SE = {after_avg:.6f} ({after_n} predictions)")
        else:
            lines.append(f"  After: no data yet")
        if before_avg is not None and after_avg is not None:
            delta = after_avg - before_avg
            direction = "WORSE" if delta > 0 else "BETTER" if delta < 0 else "SAME"
            lines.append(f"  Delta: {delta:+.6f} ({direction})")

    return "\n".join(lines)


def build_reasoning_report(excerpts):
    """Format reasoning excerpts into a report section."""
    if not excerpts:
        return "No reasoning excerpts available yet (will appear after next forecast cycle)."

    lines = ["Recent LLM reasoning samples (showing how the model thinks):"]
    # Group by contract key
    by_key = {}
    for e in excerpts:
        by_key.setdefault(e["key"], []).append(e)

    for key, items in by_key.items():
        lines.append(f"\n  {key} (last reasoning, tier={items[-1]['tier']}):")
        # Show the most recent reasoning for this contract
        latest = items[-1]
        # Truncate for prompt budget
        snippet = latest["reasoning"][:250].replace("\n", " ")
        lines.append(f"    \"{snippet}...\"")

    return "\n".join(lines)


def build_experiment_history(experiment_log):
    """Format experiment log into a report section."""
    if not experiment_log:
        return "No previous experiments recorded."

    lines = ["Previous experiments and their measured results:"]
    # Show last 10 experiments
    for entry in experiment_log[-10:]:
        date = entry.get("date", "?")
        summary = entry.get("summary", "?")[:120]
        result = entry.get("result", "pending")
        before_se = entry.get("before_avg_se")
        after_se = entry.get("after_avg_se")

        if before_se is not None and after_se is not None:
            delta = after_se - before_se
            result_str = f"SE {before_se:.4f} -> {after_se:.4f} ({delta:+.4f}, {'WORSE' if delta > 0 else 'BETTER'})"
        else:
            result_str = result

        lines.append(f"  [{date}] {summary}")
        lines.append(f"    Result: {result_str}")

    return "\n".join(lines)


def extract_replacements(response):
    """Extract SEARCH/REPLACE blocks from Sonnet's response.

    Expected format:
    <<<SEARCH
    old text to find
    >>>
    <<<REPLACE
    new text to put in its place
    >>>
    """
    pairs = []
    # Find all SEARCH...REPLACE pairs
    pattern = r"<<<SEARCH\n(.*?)>>>\s*<<<REPLACE\n(.*?)>>>"
    matches = re.findall(pattern, response, re.DOTALL)
    for old, new in matches:
        old = old.rstrip("\n")
        new = new.rstrip("\n")
        if old and old != new:
            pairs.append((old, new))
    return pairs


def check_no_change(response):
    """Check if Sonnet explicitly recommended no change."""
    return "NO_CHANGE" in response


def extract_change_summary(response):
    """Extract the change summary."""
    match = re.search(r"CHANGE_SUMMARY:\s*\n(.*?)(?:\n<<<SEARCH|\nNO_CHANGE|\Z)", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: take text before first SEARCH block
    before = response.split("<<<SEARCH")[0]
    lines = [l.strip() for l in before.strip().split("\n") if l.strip()]
    if lines:
        return " ".join(lines[-5:])[:800]
    return "No summary provided."


def load_previous_changes():
    """Load summaries of previous iteration changes for context."""
    if not os.path.isdir(LOG_DIR):
        return "No previous iterations."

    logs = sorted(f for f in os.listdir(LOG_DIR) if f.endswith(".md"))[-5:]
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


def check_should_revert(scores):
    """Check if the last iteration made things worse and we should revert.

    Returns (should_revert, before_avg_se, after_avg_se) tuple.
    Revert if after SE is measurably worse than before AND we have enough data.
    """
    last_date = get_last_iteration_date()
    if not last_date:
        return False, None, None

    before_avg, after_avg, before_n, after_n = compute_before_after_performance(scores, last_date)

    # Need at least 9 predictions in each period to judge
    if before_n < 9 or after_n < 9:
        return False, before_avg, after_avg

    if before_avg is None or after_avg is None:
        return False, before_avg, after_avg

    # Revert if performance degraded by more than 10%
    if after_avg > before_avg * 1.10:
        return True, before_avg, after_avg

    return False, before_avg, after_avg


def try_revert_last_change(date_str):
    """Attempt to revert the last iteration's changes.

    Reads the last iteration log and applies the reverse of each replacement.
    Returns True if revert was successful.
    """
    last_date = get_last_iteration_date()
    if not last_date:
        return False

    log_path = os.path.join(LOG_DIR, f"{last_date}.md")
    if not os.path.exists(log_path):
        return False

    with open(log_path) as f:
        log_content = f.read()

    # Parse the old->new pairs from the log
    # Code blocks come in pairs (old, new) under each "### Change N" section
    all_blocks = re.findall(r"```\n(.*?)\n```", log_content, re.DOTALL)
    # Pair them: [old1, new1, old2, new2, ...]
    pairs = [(all_blocks[i], all_blocks[i+1]) for i in range(0, len(all_blocks) - 1, 2)] if len(all_blocks) >= 2 else []
    if not pairs:
        print(f"  Could not parse replacements from {log_path}")
        return False

    with open(LLM_FORECAST_PATH) as f:
        current_code = f.read()

    new_code = current_code
    reverted = 0
    for new_text, old_text_was_new in pairs:
        # The log stores old->new, so to revert we find new_text and replace with old_text
        new_text = new_text.rstrip("\n")
        old_text_was_new = old_text_was_new.rstrip("\n")

        if old_text_was_new in new_code:
            new_code = new_code.replace(old_text_was_new, new_text, 1)
            reverted += 1

    if reverted == 0:
        print("  Could not find text to revert (code may have changed further)")
        return False

    # Syntax check the reverted code
    try:
        compile(new_code, "llm_forecast.py", "exec")
    except SyntaxError as e:
        print(f"  Revert would cause syntax error: {e}")
        return False

    # Write reverted code
    tmp_path = LLM_FORECAST_PATH + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            f.write(new_code)
        os.replace(tmp_path, LLM_FORECAST_PATH)
        print(f"  Reverted {reverted} replacement(s) from {last_date}")
    except OSError as e:
        print(f"  ERROR writing reverted file: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False

    # Log the revert
    revert_log_path = os.path.join(LOG_DIR, f"{date_str}.md")
    with open(revert_log_path, "w") as f:
        f.write(f"# LLM Forecast Iteration — {date_str}\n\n")
        f.write(f"**AUTO-REVERT**: Reverted changes from {last_date} because performance degraded.\n\n")
        f.write(f"Reverted {reverted} replacement(s).\n")

    return True


def extract_key_sections(code):
    """Extract the most important/tunable sections of llm_forecast.py for context.

    Returns a condensed version showing constants, prompt-building functions,
    and key parameters — the parts Sonnet is most likely to change.
    """
    lines = code.split("\n")
    sections = []

    # Always include the first 80 lines (imports, constants, config)
    sections.append(("HEADER (lines 1-80)", "\n".join(lines[:80])))

    # Find key function definitions and extract them
    key_functions = [
        "def build_binary_prompt",
        "def build_multi_outcome_prompt",
        "def build_adversarial_prompt",
        "def apply_shrinkage",
        "def triage_contract",
        "SHRINKAGE_KEEP",
        "SONNET_THRESHOLD",
        "OPUS_THRESHOLD",
        "CATEGORY_CUES",
    ]

    for i, line in enumerate(lines):
        for key in key_functions:
            if key in line and not line.strip().startswith("#"):
                # Extract this function/block (up to 60 lines or next def)
                start = max(0, i - 2)  # Include a couple lines of context before
                end = min(len(lines), i + 60)
                for j in range(i + 1, min(len(lines), i + 80)):
                    if lines[j].startswith("def ") and j > i + 3:
                        end = j
                        break
                section_text = "\n".join(lines[start:end])
                sections.append((f"SECTION around line {i+1}", section_text))
                break

    # Combine, dedup, and return
    seen = set()
    result_parts = []
    for label, text in sections:
        if text not in seen:
            seen.add(text)
            result_parts.append(f"--- {label} ---\n{text}")

    return "\n\n".join(result_parts)


def apply_replacements(current_code, replacements):
    """Apply search/replace pairs to code. Returns (new_code, applied_count)."""
    new_code = current_code
    applied = 0
    for i, (old_text, new_text) in enumerate(replacements):
        if old_text in new_code:
            new_code = new_code.replace(old_text, new_text, 1)
            applied += 1
            print(f"  Replacement {i+1}: applied ({len(old_text)} chars -> {len(new_text)} chars)")
        else:
            print(f"  Replacement {i+1}: SEARCH text not found in file (skipped)")
            # Try a fuzzy match — strip leading/trailing whitespace per line
            old_stripped = "\n".join(l.rstrip() for l in old_text.split("\n"))
            code_stripped = "\n".join(l.rstrip() for l in new_code.split("\n"))
            if old_stripped in code_stripped:
                new_code_lines = new_code.split("\n")
                old_lines = old_text.split("\n")
                new_lines = new_text.split("\n")
                for start in range(len(new_code_lines) - len(old_lines) + 1):
                    match = all(
                        new_code_lines[start + j].rstrip() == old_lines[j].rstrip()
                        for j in range(len(old_lines))
                    )
                    if match:
                        new_code_lines[start:start + len(old_lines)] = new_lines
                        new_code = "\n".join(new_code_lines)
                        applied += 1
                        print(f"  Replacement {i+1}: applied via fuzzy match")
                        break
    return new_code, applied


def main():
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"=== LLM Forecast Iteration ({date_str}) ===")

    # Load scored predictions
    scores = load_rolling_scores()
    print(f"  Scored predictions: {len(scores)}")

    if len(scores) < MIN_SCORED_PREDICTIONS:
        print(f"  Need at least {MIN_SCORED_PREDICTIONS} scored predictions before iterating. Skipping.")
        return

    # Load experiment log
    experiment_log = load_experiment_log()

    # Check if last iteration made things worse — auto-revert if so
    should_revert, before_se, after_se = check_should_revert(scores)
    if should_revert:
        print(f"  Performance degraded after last iteration (SE: {before_se:.4f} -> {after_se:.4f})")
        print(f"  Attempting auto-revert...")
        if try_revert_last_change(date_str):
            # Update experiment log with the revert
            if experiment_log:
                experiment_log[-1]["result"] = "reverted"
                experiment_log[-1]["after_avg_se"] = after_se
            experiment_log.append({
                "date": date_str,
                "summary": f"Auto-reverted changes from {get_last_iteration_date()} due to degraded performance",
                "action": "revert",
                "before_avg_se": before_se,
                "after_avg_se": after_se,
                "result": "reverted",
            })
            save_experiment_log(experiment_log)
            print("  Auto-revert complete. Skipping further iteration today.")
            return
        else:
            print("  Auto-revert failed. Proceeding with normal iteration.")

    # Update the last experiment's measured result if we have after data
    if experiment_log and before_se is not None and after_se is not None:
        last_exp = experiment_log[-1]
        if last_exp.get("result") == "pending":
            last_exp["after_avg_se"] = after_se
            delta = after_se - before_se
            last_exp["result"] = "better" if delta < 0 else "worse" if delta > 0 else "neutral"
            save_experiment_log(experiment_log)

    # Build performance report
    performance_report = build_performance_report(scores)
    print(f"  Performance report built ({len(performance_report)} chars)")

    # Load reasoning excerpts from recent predictions
    reasoning_excerpts = load_reasoning_excerpts()
    reasoning_report = build_reasoning_report(reasoning_excerpts)
    print(f"  Reasoning excerpts: {len(reasoning_excerpts)} found")

    # Build experiment history
    experiment_history = build_experiment_history(experiment_log)

    # Read current llm_forecast.py
    with open(LLM_FORECAST_PATH) as f:
        current_code = f.read()
    print(f"  Current llm_forecast.py: {len(current_code)} chars, {len(current_code.splitlines())} lines")

    # Extract key sections (the file is too large to send in full)
    key_sections = extract_key_sections(current_code)
    print(f"  Key sections extracted: {len(key_sections)} chars")

    # Load previous changes for context
    previous_changes = load_previous_changes()

    # Build the iteration prompt
    prompt = f"""You are the AI researcher responsible for improving Oracle Lab's LLM forecasting system.

The system uses LLMs (Haiku for triage, Sonnet for deep dives) to predict outcomes on Polymarket prediction markets. Your job is to review how the system has been performing and decide whether to make ONE targeted improvement to llm_forecast.py — or leave it alone.

=== PERFORMANCE REPORT ===
{performance_report}

=== LLM REASONING SAMPLES ===
{reasoning_report}

=== EXPERIMENT HISTORY ===
{experiment_history}

=== PREVIOUS ITERATION CHANGES ===
{previous_changes}

=== KEY SECTIONS OF llm_forecast.py ===
{key_sections}

=== YOUR TASK ===

Review the performance data carefully. Look for:
1. Systematic biases — is the LLM consistently over/under-confident?
2. Per-contract patterns — which contracts does it get wrong and why?
3. Prompt weaknesses — are the prompts missing important reasoning instructions?
4. Parameter issues — is SHRINKAGE_KEEP too high/low? Are the tier thresholds right?
5. Missing context — should the prompts include more/different information?
6. Category-specific problems — does it fail on certain types of contracts?
7. Before/after data — did the last iteration help or hurt?
8. Experiment history — what's been tried before? Don't repeat failed experiments.

IMPORTANT DECISION: If performance is IMPROVING or the data is insufficient to identify a clear problem, it is better to make NO CHANGE than to make a speculative tweak. Unnecessary changes introduce noise.

If you decide NO change is needed, respond with:

CHANGE_SUMMARY:
[Explain why no change is needed — what's working, why you'd leave it alone]

NO_CHANGE

If you decide to make a change, use this EXACT format:

CHANGE_SUMMARY:
[3-5 sentences explaining what you found in the performance data, what you changed, and why you expect it to help. Reference specific numbers from the performance report.]

<<<SEARCH
[exact text from llm_forecast.py to find — copy it precisely, including whitespace]
>>>
<<<REPLACE
[new text to replace it with]
>>>

Rules:
- Make at most ONE logical improvement (up to 3 SEARCH/REPLACE pairs if needed)
- Do NOT remove existing functionality
- Do NOT repeat experiments that already failed (check experiment history)
- Do NOT make changes that contradict what you learned from experiment history
- If the before/after data shows the last iteration HELPED, don't undo it
- Reference specific numbers: "avg SE went from X to Y" not "performance degraded"
"""

    print(f"  Calling {ITERATION_MODEL} for iteration...")
    try:
        response = call_openrouter(prompt, max_tokens=4000)
    except Exception as e:
        print(f"  ERROR calling OpenRouter: {e}")
        sys.exit(1)

    print(f"  Response received ({len(response)} chars)")

    # Check if Sonnet recommended no change
    if check_no_change(response):
        summary = extract_change_summary(response)
        print(f"\n  Decision: NO CHANGE")
        print(f"  Reason: {summary[:300]}")

        # Log the no-change decision
        os.makedirs(LOG_DIR, exist_ok=True)
        log_path = os.path.join(LOG_DIR, f"{date_str}.md")
        with open(log_path, "w") as f:
            f.write(f"# LLM Forecast Iteration — {date_str}\n\n")
            f.write(f"**Decision: NO CHANGE**\n\n")
            f.write(summary + "\n")

        # Record in experiment log
        experiment_log.append({
            "date": date_str,
            "summary": f"No change: {summary[:200]}",
            "action": "no_change",
            "before_avg_se": before_se,
            "result": "no_change",
        })
        save_experiment_log(experiment_log)
        print("\n  Done.")
        return

    # Extract search/replace pairs
    replacements = extract_replacements(response)
    if not replacements:
        print("  ERROR: Could not extract SEARCH/REPLACE blocks from response")
        print(f"  Response preview: {response[:500]}...")
        sys.exit(1)

    print(f"  Found {len(replacements)} replacement(s)")

    # Apply replacements
    new_code, applied = apply_replacements(current_code, replacements)

    if applied == 0:
        print("  ERROR: No replacements could be applied")
        print("  This may mean the SEARCH text didn't exactly match the file contents.")
        sys.exit(1)

    # Validate the modified code still has required elements
    required = ["build_binary_prompt", "build_multi_outcome_prompt", "SHRINKAGE_KEEP", "MODELS"]
    missing = [r for r in required if r not in new_code]
    if missing:
        print(f"  ERROR: Modified code missing required elements: {missing}")
        sys.exit(1)

    # Quick syntax check
    try:
        compile(new_code, "llm_forecast.py", "exec")
    except SyntaxError as e:
        print(f"  ERROR: Modified code has syntax error: {e}")
        sys.exit(1)

    # Write updated llm_forecast.py
    tmp_path = LLM_FORECAST_PATH + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            f.write(new_code)
        os.replace(tmp_path, LLM_FORECAST_PATH)
        print(f"  Updated llm_forecast.py ({applied} replacement(s) applied)")
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
        f.write(summary + "\n\n")
        f.write("## Replacements Applied\n\n")
        for i, (old_text, new_text) in enumerate(replacements):
            f.write(f"### Change {i+1}\n")
            f.write(f"```\n{old_text}\n```\n→\n```\n{new_text}\n```\n\n")
    print(f"  Change log: {log_path}")

    # Record in experiment log
    experiment_log.append({
        "date": date_str,
        "summary": summary[:300],
        "action": "change",
        "replacements_applied": applied,
        "before_avg_se": before_se,
        "after_avg_se": None,  # Will be filled in next iteration
        "result": "pending",
    })
    save_experiment_log(experiment_log)

    print(f"\n  Summary: {summary[:200]}...")
    print("\n  Done.")


if __name__ == "__main__":
    main()
