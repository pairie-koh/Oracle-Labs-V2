#!/usr/bin/env python3
"""One-time script to patch active_contracts.json with metadata fields.

Run this when the Gamma API is unavailable and you can't rebuild from scratch.
Patches the existing file in-place using the rules defined in build_active_contracts.py.
Fields patched: resolution_rules, category, domain, geo_scope, key_actors, resolution_type.
"""

import json
import os

RULES = {
    "us-iran-nuclear-deal-before-2027": {
        "resolution_rules": "Resolves YES if the US and Iran reach a formal nuclear agreement (JCPOA revival or new deal) before 2027. Must be an official agreement, not just talks or frameworks.",
        "category": "geopolitics", "domain": "geopolitics",
        "geo_scope": "Middle East, US, Iran",
        "key_actors": "US State Dept, Iran Foreign Ministry, IAEA, EU (E3 mediators)",
        "resolution_type": "official_announcement",
    },
    "us-iran-nuclear-deal-by-april-30": {
        "resolution_rules": "Resolves YES if a formal US-Iran nuclear agreement is reached by April 30, 2026. Same criteria as the 2027 version but shorter deadline.",
        "category": "geopolitics", "domain": "geopolitics",
        "geo_scope": "Middle East, US, Iran",
        "key_actors": "US State Dept, Iran Foreign Ministry, IAEA, EU (E3 mediators)",
        "resolution_type": "official_announcement",
    },
    "strait-of-hormuz-traffic-returns-to-normal-by-april-30": {
        "resolution_rules": "Resolves YES if commercial shipping traffic through the Strait of Hormuz returns to pre-disruption levels by April 30, 2026. Based on shipping data and maritime intelligence reports.",
        "category": "geopolitics", "domain": "geopolitics",
        "geo_scope": "Persian Gulf, Middle East",
        "key_actors": "Iran Navy, IRGC, US CENTCOM, shipping companies, maritime intelligence firms",
        "resolution_type": "data_threshold",
    },
    "will-iran-close-the-strait-of-hormuz-by-2027": {
        "resolution_rules": "Resolves based on whether Iran takes action to block or significantly disrupt commercial shipping through the Strait of Hormuz before 2027.",
        "category": "geopolitics", "domain": "geopolitics",
        "geo_scope": "Persian Gulf, Middle East",
        "key_actors": "Iran government, IRGC Navy, US military, oil tanker operators, Gulf states",
        "resolution_type": "event_occurrence",
    },
    "next-leader-out-of-power-before-2027-795": {
        "resolution_rules": "Resolves for whichever listed head of state/government is next to leave office before 2027. Includes resignation, removal, death, or end of term. The leader must actually vacate power, not just announce departure.",
        "category": "geopolitics", "domain": "geopolitics",
        "geo_scope": "global",
        "key_actors": "listed heads of state/government (varies by outcome)",
        "resolution_type": "event_occurrence",
    },
    "save-act-signed-into-law-in-2026": {
        "resolution_rules": "Resolves YES if the Safeguard American Voter Eligibility (SAVE) Act is signed into law by the President in 2026. Must pass both House and Senate and receive presidential signature.",
        "category": "geopolitics", "domain": "politics",
        "geo_scope": "US",
        "key_actors": "US House, US Senate, President, House Speaker",
        "resolution_type": "official_announcement",
    },
    "save-act-becomes-law-by": {
        "resolution_rules": "Resolves YES if the Safeguard American Voter Eligibility (SAVE) Act is signed into law by the President by the specified date. Must pass both House and Senate and receive presidential signature.",
        "category": "geopolitics", "domain": "politics",
        "geo_scope": "US",
        "key_actors": "US House, US Senate, President, House Speaker",
        "resolution_type": "official_announcement",
    },
    "us-recession-by-end-of-2026": {
        "resolution_rules": "Resolves YES if the NBER Business Cycle Dating Committee declares a US recession that includes any part of 2026, OR if two consecutive quarters of negative real GDP growth occur with at least one quarter in 2026.",
        "category": "economics", "domain": "economics",
        "geo_scope": "US",
        "key_actors": "NBER Business Cycle Dating Committee, BEA, Federal Reserve",
        "resolution_type": "data_release",
    },
    "fed-decision-in-april": {
        "resolution_rules": "Resolves based on the FOMC decision announced after the April 29-30, 2026 meeting. Options: rate cut (25bps or 50+bps), no change, or rate hike. Based on the official FOMC statement.",
        "category": "economics", "domain": "economics",
        "geo_scope": "US",
        "key_actors": "FOMC, Jerome Powell, Federal Reserve Board governors",
        "resolution_type": "official_announcement",
    },
    "march-inflation-us-annual": {
        "resolution_rules": "Resolves based on the official BLS Consumer Price Index report for March 2026, using the year-over-year all-items CPI-U percentage change, rounded to one decimal place.",
        "category": "economics", "domain": "economics",
        "geo_scope": "US",
        "key_actors": "Bureau of Labor Statistics (BLS)",
        "resolution_type": "data_release",
    },
    "what-price-will-bitcoin-hit-before-2027": {
        "resolution_rules": "Each outcome resolves YES if BTC/USD reaches the specified price level at any point before January 1, 2027, on major exchanges (Coinbase, Binance). Intraday wicks count.",
        "category": "economics", "domain": "crypto",
        "geo_scope": "global",
        "key_actors": "Coinbase, Binance, crypto market participants, Bitcoin ETF issuers",
        "resolution_type": "price_threshold",
    },
    "will-gas-hit-by-end-of-march": {
        "resolution_rules": "Resolves based on the AAA national average regular gasoline price as of March 31, 2026. Each outcome corresponds to a specific price threshold being reached.",
        "category": "economics", "domain": "economics",
        "geo_scope": "US",
        "key_actors": "AAA, EIA, OPEC+, US refiners",
        "resolution_type": "data_threshold",
    },
    "jerome-powell-out-as-fed-chair-by": {
        "resolution_rules": "Resolves based on the date Jerome Powell ceases to serve as Federal Reserve Chair. Includes resignation, removal, or term expiration. His current term as Chair expires May 2026.",
        "category": "politics", "domain": "politics",
        "geo_scope": "US",
        "key_actors": "Jerome Powell, President, White House",
        "resolution_type": "event_occurrence",
    },
    "who-will-be-confirmed-as-fed-chair": {
        "resolution_rules": "Resolves for whichever individual is confirmed by the US Senate as the next Federal Reserve Chair. Requires formal Senate confirmation vote.",
        "category": "politics", "domain": "politics",
        "geo_scope": "US",
        "key_actors": "President, US Senate Banking Committee, Fed Chair nominees",
        "resolution_type": "official_announcement",
    },
    "which-party-will-win-the-house-in-2026": {
        "resolution_rules": "Resolves based on which party wins a majority of seats in the US House of Representatives in the November 2026 midterm elections. Based on certified election results.",
        "category": "politics", "domain": "politics",
        "geo_scope": "US",
        "key_actors": "Democratic Party, Republican Party, state election officials",
        "resolution_type": "election_result",
    },
    "balance-of-power-2026-midterms": {
        "resolution_rules": "Resolves based on the combined House and Senate outcomes in 2026 midterms: e.g., Dem trifecta, Rep trifecta, split government. Based on certified election results and January 2027 Congress composition.",
        "category": "politics", "domain": "politics",
        "geo_scope": "US",
        "key_actors": "Democratic Party, Republican Party, state election officials",
        "resolution_type": "election_result",
    },
    "2026-fifa-world-cup-winner-595": {
        "resolution_rules": "Resolves for whichever national team wins the 2026 FIFA World Cup final (June-July 2026, hosted by US/Canada/Mexico). Based on official FIFA results.",
        "category": "sports", "domain": "sports",
        "geo_scope": "global (US/Canada/Mexico host)",
        "key_actors": "FIFA, 48 qualified national teams",
        "resolution_type": "event_outcome",
    },
    "2026-nba-champion": {
        "resolution_rules": "Resolves for whichever team wins the 2025-26 NBA Finals. Based on official NBA results.",
        "category": "sports", "domain": "sports",
        "geo_scope": "US, Canada",
        "key_actors": "NBA, 30 NBA teams",
        "resolution_type": "event_outcome",
    },
    "which-company-has-the-best-ai-model-end-of-march-751": {
        "resolution_rules": "Resolves based on which company has the #1 ranked model on the LMSYS Chatbot Arena leaderboard (overall Elo) as of March 31, 2026.",
        "category": "tech", "domain": "ai",
        "geo_scope": "global",
        "key_actors": "Anthropic, OpenAI, Google DeepMind, Meta AI, LMSYS (benchmark operator)",
        "resolution_type": "benchmark_ranking",
    },
    "which-company-will-have-the-best-ai-model-for-coding-on-march-31": {
        "resolution_rules": "Resolves based on which company has the #1 ranked model on the LMSYS Chatbot Arena Coding leaderboard as of March 31, 2026.",
        "category": "tech", "domain": "ai",
        "geo_scope": "global",
        "key_actors": "Anthropic, OpenAI, Google DeepMind, Meta AI, LMSYS (benchmark operator)",
        "resolution_type": "benchmark_ranking",
    },
    "will-the-us-confirm-that-aliens-exist-before-2027": {
        "resolution_rules": "Resolves YES if the US government (President, Congress, DOD, or NASA) makes an official public statement confirming the existence of extraterrestrial life before 2027.",
        "category": "tech", "domain": "science",
        "geo_scope": "US",
        "key_actors": "President, Congress, DOD, NASA, UAP task force",
        "resolution_type": "official_announcement",
    },
    "survivor-50-winner": {
        "resolution_rules": "Resolves for whichever contestant wins Survivor Season 50 as announced in the CBS finale broadcast.",
        "category": "entertainment", "domain": "entertainment",
        "geo_scope": "US",
        "key_actors": "CBS, Survivor contestants, Jeff Probst",
        "resolution_type": "event_outcome",
    },
    "new-stranger-things-episode-released-by-wednesday": {
        "resolution_rules": "Resolves based on when Netflix releases new Stranger Things Season 5 episodes. YES if episode(s) are available on Netflix by the specified date.",
        "category": "entertainment", "domain": "entertainment",
        "geo_scope": "global",
        "key_actors": "Netflix, Duffer Brothers",
        "resolution_type": "content_release",
    },
    "gta-6-launch-postponed-again": {
        "resolution_rules": "Resolves YES if Rockstar Games or Take-Two officially announces a delay to GTA 6 beyond its previously announced Fall 2025 release window. Based on official company communications.",
        "category": "entertainment", "domain": "gaming",
        "geo_scope": "global",
        "key_actors": "Rockstar Games, Take-Two Interactive",
        "resolution_type": "official_announcement",
    },
}


def main():
    path = os.path.join(os.path.dirname(__file__), "..", "contracts", "active_contracts.json")
    path = os.path.abspath(path)

    with open(path) as f:
        data = json.load(f)

    patched = 0
    for contract in data.get("contracts", []):
        slug = contract.get("slug", "")
        if slug in RULES:
            for k, v in RULES[slug].items():
                contract[k] = v
            patched += 1

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    total = len(data.get("contracts", []))
    print(f"Patched {patched}/{total} contracts with metadata (resolution_rules, geo_scope, key_actors, resolution_type)")

    # Show a sample
    for c in data["contracts"][:3]:
        print(f"  {c.get('slug', '?')}:")
        print(f"    geo_scope: {c.get('geo_scope', 'MISSING')}")
        print(f"    key_actors: {c.get('key_actors', 'MISSING')}")
        print(f"    resolution_type: {c.get('resolution_type', 'MISSING')}")


if __name__ == "__main__":
    main()
