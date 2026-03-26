#!/usr/bin/env python3
"""Oracle Lab — Agent Iteration via OpenRouter (replaces headless Claude Code).

Reads an agent's scorecard, leaderboard, program.md, and forecast.py,
sends them to Sonnet via OpenRouter, and applies the suggested code change.

Usage: python iterate_agent.py <agent_name>
       python iterate_agent.py momentum
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

import requests

# Use project root (one level up from scripts/)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from constants import OPENROUTER_API_URL

# Use Sonnet for iteration — smart enough to make good code changes
ITERATION_MODEL = "anthropic/claude-sonnet-4"


def read_file_safe(path):
    """Read a file, return contents or error message."""
    try:
        with open(path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return f"[File not found: {path}]"
    except Exception as e:
        return f"[Error reading {path}: {e}]"


def call_openrouter(prompt, max_tokens=4096):
    """Call OpenRouter API. Returns raw text response."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/oracle-lab",
        "X-Title": "Oracle Lab Iteration",
    }
    payload = {
        "model": ITERATION_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }

    resp = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def extract_code_block(response):
    """Extract the full forecast.py from the response.

    Looks for a fenced code block marked as python that contains the full file.
    """
    # Find all python code blocks
    blocks = re.findall(r"```python\n(.*?)```", response, re.DOTALL)
    if not blocks:
        # Try without language specifier
        blocks = re.findall(r"```\n(.*?)```", response, re.DOTALL)

    if not blocks:
        return None

    # Return the longest block (most likely the full file)
    return max(blocks, key=len)


def extract_change_summary(response):
    """Extract the change summary from the response."""
    # Look for text between CHANGE_SUMMARY markers or after "Summary:" etc.
    match = re.search(r"CHANGE_SUMMARY:\s*\n(.*?)(?:\n```|\Z)", response, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Fallback: first paragraph before any code block
    before_code = response.split("```")[0]
    lines = [l.strip() for l in before_code.strip().split("\n") if l.strip()]
    if lines:
        return " ".join(lines[-3:])[:500]

    return "No summary provided."


def iterate_agent(agent_name):
    """Run one iteration cycle for a single agent."""
    agent_dir = os.path.join(PROJECT_ROOT, "agents", agent_name)
    if not os.path.isdir(agent_dir):
        print(f"ERROR: Agent directory not found: {agent_dir}")
        return False

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"=== Iterating: {agent_name} ({date_str}) ===")

    # Read all context files
    scorecard = read_file_safe(os.path.join(agent_dir, "scorecard.json"))
    leaderboard = read_file_safe(os.path.join(PROJECT_ROOT, "scoreboard", "latest.json"))
    program = read_file_safe(os.path.join(agent_dir, "program.md"))
    forecast_py = read_file_safe(os.path.join(agent_dir, "forecast.py"))

    if "[File not found" in forecast_py:
        print(f"ERROR: {agent_name}/forecast.py not found")
        return False

    # Get current version
    version_match = re.search(r'METHODOLOGY_VERSION\s*=\s*["\']([^"\']+)["\']', forecast_py)
    prev_version = version_match.group(1) if version_match else "unknown"
    print(f"  Current version: {prev_version}")

    # Build prompt
    prompt = f"""You are the researcher for the {agent_name} forecasting agent in Oracle Lab.

Here are the files you need to review:

=== 1. SCORECARD (agents/{agent_name}/scorecard.json) ===
{scorecard}

=== 2. LEADERBOARD (scoreboard/latest.json) ===
{leaderboard}

=== 3. RESEARCH INSTRUCTIONS (agents/{agent_name}/program.md) ===
{program}

=== 4. CURRENT FORECAST CODE (agents/{agent_name}/forecast.py) ===
{forecast_py}

Following the instructions in program.md:
- Review your performance honestly. Are you beating the naive baseline?
- Identify ONE specific change to make to forecast.py
- If your last change made things worse (current MSE > previous MSE), revert it first, then try something different.

IMPORTANT: Make only ONE change. Do not rewrite the entire file.

You must respond in exactly this format:

CHANGE_SUMMARY:
[3-5 sentences explaining what you changed and why]

```python
[The COMPLETE updated forecast.py file — include ALL code, not just the changed parts]
```

The code block must contain the ENTIRE forecast.py file with your ONE change applied and METHODOLOGY_VERSION bumped to the next version number."""

    print(f"  Calling {ITERATION_MODEL}...")
    try:
        response = call_openrouter(prompt, max_tokens=8192)
    except Exception as e:
        print(f"  ERROR calling OpenRouter: {e}")
        return False

    # Extract the new forecast.py
    new_code = extract_code_block(response)
    if not new_code:
        print("  ERROR: Could not extract code block from response")
        print(f"  Response preview: {response[:500]}...")
        return False

    # Validate it looks like forecast.py
    if "make_forecasts" not in new_code and "METHODOLOGY_VERSION" not in new_code:
        print("  ERROR: Extracted code doesn't look like a valid forecast.py")
        return False

    # Check version was bumped
    new_version_match = re.search(r'METHODOLOGY_VERSION\s*=\s*["\']([^"\']+)["\']', new_code)
    new_version = new_version_match.group(1) if new_version_match else "unknown"
    if new_version == prev_version:
        print(f"  WARNING: Version not bumped (still {prev_version})")

    # Write the updated forecast.py (atomic: write temp, then rename)
    forecast_path = os.path.join(agent_dir, "forecast.py")
    tmp_path = forecast_path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            f.write(new_code)
        os.replace(tmp_path, forecast_path)
        print(f"  Updated forecast.py (v{prev_version} -> v{new_version})")
    except OSError as e:
        print(f"  ERROR: Failed to write forecast.py: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False

    # Write methodology change log
    summary = extract_change_summary(response)
    log_dir = os.path.join(agent_dir, "log", "methodology_changes")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{date_str}.md")
    with open(log_path, "w") as f:
        f.write(f"# {agent_name} — {date_str}\n\n")
        f.write(f"Version: {prev_version} -> {new_version}\n\n")
        f.write(summary + "\n")
    print(f"  Wrote change log to {log_path}")

    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python iterate_agent.py <agent_name>")
        print("       python iterate_agent.py momentum")
        print("       python iterate_agent.py all")
        sys.exit(1)

    agent_name = sys.argv[1]

    if agent_name == "all":
        agents = ["momentum", "historian", "game_theorist", "quant"]
    else:
        agents = [agent_name]

    results = {}
    for agent in agents:
        success = iterate_agent(agent)
        results[agent] = "ok" if success else "failed"
        print()

    print("=== Results ===")
    for agent, result in results.items():
        print(f"  {agent}: {result}")

    if all(r == "ok" for r in results.values()):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
