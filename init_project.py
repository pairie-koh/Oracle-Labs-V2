"""
Oracle Lab — init_project.py
Creates all required directories and initial empty files
so the first cycle doesn't fail on missing data.
"""

import os
import json

from constants import AGENTS, AGENTS_DIR

# All directories that need to exist
DIRS = [
    "briefings",
    "state",
    "price_history",
    "fact_history",
    "scoreboard",
    "logs",
    "scripts",
]

# Agent subdirectories
AGENT_SUBDIRS = ["log", "log/methodology_changes"]


def init():
    print("=== Initializing Oracle Lab ===")

    # Create top-level directories
    for d in DIRS:
        os.makedirs(d, exist_ok=True)
        print(f"  {d}/")

    # Create agent directories
    for agent in AGENTS:
        agent_dir = os.path.join(AGENTS_DIR, agent)
        os.makedirs(agent_dir, exist_ok=True)
        print(f"  {agent_dir}/")
        for sub in AGENT_SUBDIRS:
            sub_dir = os.path.join(agent_dir, sub)
            os.makedirs(sub_dir, exist_ok=True)
            print(f"    {sub}/")

    # Create initial empty files so first cycle doesn't crash
    empty_files = {
        "fact_history/latest.json": "[]",
        "state/current.json": json.dumps({
            "last_updated": None,
            "markets": {}
        }, indent=2),
    }

    for path, content in empty_files.items():
        if not os.path.exists(path):
            with open(path, "w") as f:
                f.write(content)
            print(f"  Created {path}")
        else:
            print(f"  {path} already exists, skipping")

    print("\n=== Initialization complete ===")
    print("Next steps:")
    print("  1. Set up .env with API keys")
    print("  2. Run: python3 newswire.py")
    print("  3. Run: python3 state.py")
    print("  4. Run: python3 prepare.py")
    print("  5. Run agent forecasts")


if __name__ == "__main__":
    init()
