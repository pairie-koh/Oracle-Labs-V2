"""
Oracle Lab — Constants
All market definitions, API endpoints, categories, and path constants.
Adding a market = adding a dict entry + indicator categories + query templates.
"""

import os

# ── Markets ──────────────────────────────────────────────────────────────────
# Each market has CLOB identifiers from Polymarket.
# To add a market: add an entry here, add INDICATOR_CATEGORIES, add QUERY_TEMPLATES.

MARKETS = {
    "regime_fall": {
        "name": "Will the Iranian regime fall by June 30?",
        "slug": "regime-fall",
        "condition_id": "0x9352c559e9648ab4cab236087b64ca85c5b7123a4c7d9d7d4efde4a39c18056f",
        "yes_token_id": "38397507750621893057346880033441136112987238933685677349709401910643842844855",
        "no_token_id": "95949957895141858444199258452803633110472396604599808168788254125381075552218",
        "end_date": "2025-06-30",
    },
}

# ── API Endpoints ────────────────────────────────────────────────────────────

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"
POLYMARKET_CLOB_URL = "https://clob.polymarket.com"
POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"

# ── Models ───────────────────────────────────────────────────────────────────

PERPLEXITY_MODEL = "sonar-pro"
HAIKU_MODEL_OPENROUTER = "anthropic/claude-haiku-4.5"

# ── Forecast Settings ────────────────────────────────────────────────────────

FORECAST_HORIZON_HOURS = 24  # Backward compatibility (changed from 4 to 24)
FORECAST_HORIZONS = {"24h": 24, "7d": 168}

# ── Source Categories ────────────────────────────────────────────────────────
# Used by newswire normalization to tag facts.

SOURCE_CATEGORIES = [
    "wire_service",
    "us_prestige",
    "uk_prestige",
    "regional_specialist",
    "government_official",
    "think_tank",
    "osint",
    "social_media",
    "market_commentary",
]

# ── Indicator Categories (per market) ────────────────────────────────────────
# Each market has its own set of indicator categories for fact tagging.

INDICATOR_CATEGORIES = {
    "regime_fall": [
        "military_pressure",
        "internal_stability",
        "succession_dynamics",
        "diplomatic_signals",
        "economic_collapse",
        "international_response",
    ],
}

# ── Agents ───────────────────────────────────────────────────────────────────

AGENTS = ["momentum", "historian", "game_theorist", "quant"]

# ── Paths (relative to project root) ────────────────────────────────────────

BRIEFINGS_DIR = "briefings"
STATE_DIR = "state"
PRICE_HISTORY_DIR = "price_history"
FACT_HISTORY_DIR = "fact_history"
SCOREBOARD_DIR = "scoreboard"
AGENTS_DIR = "agents"
LOGS_DIR = "logs"
SCRIPTS_DIR = "scripts"

STATE_FILE = os.path.join(STATE_DIR, "current.json")
PRICE_CSV = os.path.join(PRICE_HISTORY_DIR, "prices.csv")
FACTS_CSV = os.path.join(FACT_HISTORY_DIR, "facts.csv")
LATEST_FACTS = os.path.join(FACT_HISTORY_DIR, "latest.json")
LATEST_BRIEFING = os.path.join(BRIEFINGS_DIR, "latest.json")
LEADERBOARD_FILE = os.path.join(SCOREBOARD_DIR, "latest.json")

# ── Perplexity Query Templates (per market) ──────────────────────────────────
# 2 queries per market: military/security focus + political/diplomatic/economic focus.
# {market_name} gets substituted at runtime.

QUERY_TEMPLATES = {
    "regime_fall": [
        (
            "military_security",
            "What are the latest developments in the past 24 hours regarding "
            "military pressure on Iran, including US military deployments to the "
            "Middle East, Israeli military operations or threats against Iran, "
            "Iranian military readiness and IRGC activities, any strikes or "
            "military confrontations, and internal security force actions against "
            "Iranian protesters or opposition groups? Include specific sources "
            "and timestamps where possible."
        ),
        (
            "political_diplomatic_economic",
            "What are the latest developments in the past 24 hours regarding "
            "the political stability of the Iranian regime, including diplomatic "
            "negotiations or ultimatums involving Iran, internal political "
            "dynamics and succession questions, economic conditions and sanctions "
            "impact, protest movements or civil unrest inside Iran, and any "
            "international statements or UN actions regarding Iran? Include "
            "specific sources and timestamps where possible."
        ),
    ],
}


if __name__ == "__main__":
    # Quick verification
    print("=== Oracle Lab Constants ===")
    print(f"Markets: {list(MARKETS.keys())}")
    for key, market in MARKETS.items():
        print(f"  {key}: {market['name']}")
        print(f"    YES token: {market['yes_token_id'][:20]}...")
        print(f"    NO token:  {market['no_token_id'][:20]}...")
        print(f"    Indicators: {INDICATOR_CATEGORIES[key]}")
        print(f"    Query templates: {len(QUERY_TEMPLATES[key])}")
    print(f"Agents: {AGENTS}")
    print(f"Source categories: {SOURCE_CATEGORIES}")
    print(f"Forecast horizon (legacy): {FORECAST_HORIZON_HOURS}h")
    print(f"Forecast horizons: {FORECAST_HORIZONS}")
    print(f"Models: {PERPLEXITY_MODEL}, {HAIKU_MODEL_OPENROUTER}")
    print(f"CLOB URL: {POLYMARKET_CLOB_URL}")
    print("All constants OK.")
