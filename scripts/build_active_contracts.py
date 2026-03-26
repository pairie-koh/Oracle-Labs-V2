#!/usr/bin/env python3
"""Build active_contracts.json from curated contract list + Gamma API data."""

import requests
import json
import time
from datetime import datetime, timezone


def fetch_event(slug):
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    r = requests.get(url, timeout=10)
    data = r.json()
    if data and len(data) > 0:
        return data[0]
    return None


def build_contract(event, contract_name, category, domain, contract_type, frequency, horizon,
                   resolution_rules="", geo_scope="", key_actors="", resolution_type=""):
    """Build a contract entry from a Gamma API event."""
    markets = event.get("markets", [])
    if not markets:
        return None

    if len(markets) == 1 or contract_type == "binary":
        m = markets[0]
        clob_tokens = m.get("clobTokenIds", "")
        if clob_tokens:
            tokens = json.loads(clob_tokens)
            yes_token = tokens[0] if len(tokens) > 0 else ""
            no_token = tokens[1] if len(tokens) > 1 else ""
        else:
            yes_token = no_token = ""

        prices = m.get("outcomePrices", "")
        if prices:
            price_list = json.loads(prices)
            yes_price = float(price_list[0]) if len(price_list) > 0 else 0.5
        else:
            yes_price = 0.5

        return {
            "contract_name": contract_name,
            "question": m.get("question", event.get("title", "")),
            "slug": event.get("slug", ""),
            "market_slug": m.get("slug", ""),
            "condition_id": m.get("conditionId", ""),
            "yes_token_id": yes_token,
            "no_token_id": no_token,
            "end_date": event.get("endDate", ""),
            "category": category,
            "domain": domain,
            "contract_type": contract_type,
            "prediction_frequency": frequency,
            "prediction_horizon": horizon,
            "resolution_rules": resolution_rules,
            "geo_scope": geo_scope,
            "key_actors": key_actors,
            "resolution_type": resolution_type,
            "current_prices": {"yes": round(yes_price, 4), "no": round(1 - yes_price, 4)},
            "volume": float(m.get("volume", 0) or 0),
            "event_slug": event.get("slug", ""),
            "num_outcomes": 2,
        }
    else:
        # Multi-outcome event
        outcomes = []
        for m in markets:
            clob_tokens = m.get("clobTokenIds", "")
            tokens = json.loads(clob_tokens) if clob_tokens else ["", ""]
            prices = m.get("outcomePrices", "")
            price_list = json.loads(prices) if prices else [0.5, 0.5]
            outcomes.append({
                "question": m.get("question", ""),
                "condition_id": m.get("conditionId", ""),
                "yes_token_id": tokens[0] if len(tokens) > 0 else "",
                "yes_price": round(float(price_list[0]), 4) if len(price_list) > 0 else 0.5,
                "market_slug": m.get("slug", ""),
            })

        return {
            "contract_name": contract_name,
            "question": event.get("title", ""),
            "slug": event.get("slug", ""),
            "end_date": event.get("endDate", ""),
            "category": category,
            "domain": domain,
            "contract_type": contract_type,
            "prediction_frequency": frequency,
            "prediction_horizon": horizon,
            "resolution_rules": resolution_rules,
            "geo_scope": geo_scope,
            "key_actors": key_actors,
            "resolution_type": resolution_type,
            "volume": float(event.get("volume", 0) or 0),
            "event_slug": event.get("slug", ""),
            "num_outcomes": len(markets),
            "outcomes": outcomes,
        }


# Curated contract definitions mapped to Polymarket event slugs
CONTRACT_DEFS = [
    # GEOPOLITICS
    {
        "slug": "us-iran-nuclear-deal-before-2027",
        "name": "US-Iran nuclear deal before 2027",
        "category": "geopolitics",
        "domain": "geopolitics",
        "type": "binary",
        "frequency": "every_12h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves YES if the US and Iran reach a formal nuclear agreement (JCPOA revival or new deal) before 2027. Must be an official agreement, not just talks or frameworks.",
        "geo_scope": "Middle East, US, Iran",
        "key_actors": "US State Dept, Iran Foreign Ministry, IAEA, EU (E3 mediators)",
        "resolution_type": "official_announcement",
    },
    {
        "slug": "us-iran-nuclear-deal-by-april-30",
        "name": "US-Iran nuclear deal by April 30",
        "category": "geopolitics",
        "domain": "geopolitics",
        "type": "binary",
        "frequency": "every_12h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves YES if a formal US-Iran nuclear agreement is reached by April 30, 2026. Same criteria as the 2027 version but shorter deadline.",
        "geo_scope": "Middle East, US, Iran",
        "key_actors": "US State Dept, Iran Foreign Ministry, IAEA, EU (E3 mediators)",
        "resolution_type": "official_announcement",
    },
    {
        "slug": "strait-of-hormuz-traffic-returns-to-normal-by-april-30",
        "name": "Strait of Hormuz traffic normalizes by April 30",
        "category": "geopolitics",
        "domain": "geopolitics",
        "type": "binary",
        "frequency": "every_12h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves YES if commercial shipping traffic through the Strait of Hormuz returns to pre-disruption levels by April 30, 2026. Based on shipping data and maritime intelligence reports.",
        "geo_scope": "Persian Gulf, Middle East",
        "key_actors": "Iran Navy, IRGC, US CENTCOM, shipping companies, maritime intelligence firms",
        "resolution_type": "data_threshold",
    },
    {
        "slug": "will-iran-close-the-strait-of-hormuz-by-2027",
        "name": "Will Iran close the Strait of Hormuz",
        "category": "geopolitics",
        "domain": "geopolitics",
        "type": "multi-outcome",
        "frequency": "every_12h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves based on whether Iran takes action to block or significantly disrupt commercial shipping through the Strait of Hormuz before 2027.",
        "geo_scope": "Persian Gulf, Middle East",
        "key_actors": "Iran government, IRGC Navy, US military, oil tanker operators, Gulf states",
        "resolution_type": "event_occurrence",
    },
    {
        "slug": "next-leader-out-of-power-before-2027-795",
        "name": "Which world leaders will leave office",
        "category": "geopolitics",
        "domain": "geopolitics",
        "type": "multi-outcome",
        "frequency": "every_12h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves for whichever listed head of state/government is next to leave office before 2027. Includes resignation, removal, death, or end of term. The leader must actually vacate power, not just announce departure.",
        "geo_scope": "global",
        "key_actors": "listed heads of state/government (varies by outcome)",
        "resolution_type": "event_occurrence",
    },
    {
        "slug": "save-act-signed-into-law-in-2026",
        "name": "SAVE Act becomes law in 2026",
        "category": "geopolitics",
        "domain": "politics",
        "type": "binary",
        "frequency": "every_12h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves YES if the Safeguard American Voter Eligibility (SAVE) Act is signed into law by the President in 2026. Must pass both House and Senate and receive presidential signature.",
        "geo_scope": "US",
        "key_actors": "US House, US Senate, President, House Speaker",
        "resolution_type": "official_announcement",
    },
    # ECONOMICS
    {
        "slug": "us-recession-by-end-of-2026",
        "name": "US recession by end of 2026",
        "category": "economics",
        "domain": "economics",
        "type": "binary",
        "frequency": "every_12h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves YES if the NBER Business Cycle Dating Committee declares a US recession that includes any part of 2026, OR if two consecutive quarters of negative real GDP growth occur with at least one quarter in 2026.",
        "geo_scope": "US",
        "key_actors": "NBER Business Cycle Dating Committee, BEA, Federal Reserve",
        "resolution_type": "data_release",
    },
    {
        "slug": "fed-decision-in-april",
        "name": "Fed decision in April",
        "category": "economics",
        "domain": "economics",
        "type": "multi-outcome",
        "frequency": "every_12h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves based on the FOMC decision announced after the April 29-30, 2026 meeting. Options: rate cut (25bps or 50+bps), no change, or rate hike. Based on the official FOMC statement.",
        "geo_scope": "US",
        "key_actors": "FOMC, Jerome Powell, Federal Reserve Board governors",
        "resolution_type": "official_announcement",
    },
    {
        "slug": "march-inflation-us-annual",
        "name": "CPI year-over-year in March",
        "category": "economics",
        "domain": "economics",
        "type": "multi-outcome",
        "frequency": "every_12h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves based on the official BLS Consumer Price Index report for March 2026, using the year-over-year all-items CPI-U percentage change, rounded to one decimal place.",
        "geo_scope": "US",
        "key_actors": "Bureau of Labor Statistics (BLS)",
        "resolution_type": "data_release",
    },
    {
        "slug": "what-price-will-bitcoin-hit-before-2027",
        "name": "Bitcoin price targets 2026",
        "category": "economics",
        "domain": "crypto",
        "type": "multi-outcome",
        "frequency": "every_12h",
        "horizon": "24h+7d",
        "resolution_rules": "Each outcome resolves YES if BTC/USD reaches the specified price level at any point before January 1, 2027, on major exchanges (Coinbase, Binance). Intraday wicks count.",
        "geo_scope": "global",
        "key_actors": "Coinbase, Binance, crypto market participants, Bitcoin ETF issuers",
        "resolution_type": "price_threshold",
    },
    {
        "slug": "will-gas-hit-by-end-of-march",
        "name": "Gas prices end of March",
        "category": "economics",
        "domain": "economics",
        "type": "multi-outcome",
        "frequency": "once_daily",
        "horizon": "end_of_month",
        "resolution_rules": "Resolves based on the AAA national average regular gasoline price as of March 31, 2026. Each outcome corresponds to a specific price threshold being reached.",
        "geo_scope": "US",
        "key_actors": "AAA, EIA, OPEC+, US refiners",
        "resolution_type": "data_threshold",
    },
    # POLITICS
    {
        "slug": "jerome-powell-out-as-fed-chair-by",
        "name": "Powell out as Fed chair",
        "category": "politics",
        "domain": "politics",
        "type": "multi-outcome",
        "frequency": "every_12h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves based on the date Jerome Powell ceases to serve as Federal Reserve Chair. Includes resignation, removal, or term expiration. His current term as Chair expires May 2026.",
        "geo_scope": "US",
        "key_actors": "Jerome Powell, President, White House",
        "resolution_type": "event_occurrence",
    },
    {
        "slug": "who-will-be-confirmed-as-fed-chair",
        "name": "Who will be confirmed as Fed Chair",
        "category": "politics",
        "domain": "politics",
        "type": "multi-outcome",
        "frequency": "every_12h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves for whichever individual is confirmed by the US Senate as the next Federal Reserve Chair. Requires formal Senate confirmation vote.",
        "geo_scope": "US",
        "key_actors": "President, US Senate Banking Committee, Fed Chair nominees",
        "resolution_type": "official_announcement",
    },
    {
        "slug": "which-party-will-win-the-house-in-2026",
        "name": "2026 midterms - House winner",
        "category": "politics",
        "domain": "politics",
        "type": "multi-outcome",
        "frequency": "every_12h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves based on which party wins a majority of seats in the US House of Representatives in the November 2026 midterm elections. Based on certified election results.",
        "geo_scope": "US",
        "key_actors": "Democratic Party, Republican Party, state election officials",
        "resolution_type": "election_result",
    },
    {
        "slug": "balance-of-power-2026-midterms",
        "name": "2026 midterms - Balance of Power",
        "category": "politics",
        "domain": "politics",
        "type": "multi-outcome",
        "frequency": "every_12h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves based on the combined House and Senate outcomes in 2026 midterms: e.g., Dem trifecta, Rep trifecta, split government. Based on certified election results and January 2027 Congress composition.",
        "geo_scope": "US",
        "key_actors": "Democratic Party, Republican Party, state election officials",
        "resolution_type": "election_result",
    },
    # SPORTS
    {
        "slug": "2026-fifa-world-cup-winner-595",
        "name": "FIFA World Cup 2026 winner",
        "category": "sports",
        "domain": "sports",
        "type": "multi-outcome",
        "frequency": "every_24h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves for whichever national team wins the 2026 FIFA World Cup final (June-July 2026, hosted by US/Canada/Mexico). Based on official FIFA results.",
        "geo_scope": "global (US/Canada/Mexico host)",
        "key_actors": "FIFA, 48 qualified national teams",
        "resolution_type": "event_outcome",
    },
    {
        "slug": "2026-nba-champion",
        "name": "NBA Finals 2026 winner",
        "category": "sports",
        "domain": "sports",
        "type": "multi-outcome",
        "frequency": "every_24h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves for whichever team wins the 2025-26 NBA Finals. Based on official NBA results.",
        "geo_scope": "US, Canada",
        "key_actors": "NBA, 30 NBA teams",
        "resolution_type": "event_outcome",
    },
    # TECH / AI / SCIENCE
    {
        "slug": "which-company-has-the-best-ai-model-end-of-march-751",
        "name": "Top AI model this month",
        "category": "tech",
        "domain": "ai",
        "type": "multi-outcome",
        "frequency": "every_24h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves based on which company has the #1 ranked model on the LMSYS Chatbot Arena leaderboard (overall Elo) as of March 31, 2026.",
        "geo_scope": "global",
        "key_actors": "Anthropic, OpenAI, Google DeepMind, Meta AI, LMSYS (benchmark operator)",
        "resolution_type": "benchmark_ranking",
    },
    {
        "slug": "which-company-will-have-the-best-ai-model-for-coding-on-march-31",
        "name": "Best AI coding model end of March",
        "category": "tech",
        "domain": "ai",
        "type": "multi-outcome",
        "frequency": "every_24h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves based on which company has the #1 ranked model on the LMSYS Chatbot Arena Coding leaderboard as of March 31, 2026.",
        "geo_scope": "global",
        "key_actors": "Anthropic, OpenAI, Google DeepMind, Meta AI, LMSYS (benchmark operator)",
        "resolution_type": "benchmark_ranking",
    },
    {
        "slug": "will-the-us-confirm-that-aliens-exist-before-2027",
        "name": "US confirms aliens exist before 2027",
        "category": "tech",
        "domain": "science",
        "type": "multi-outcome",
        "frequency": "every_24h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves YES if the US government (President, Congress, DOD, or NASA) makes an official public statement confirming the existence of extraterrestrial life before 2027.",
        "geo_scope": "US",
        "key_actors": "President, Congress, DOD, NASA, UAP task force",
        "resolution_type": "official_announcement",
    },
    # CULTURE / ENTERTAINMENT
    {
        "slug": "survivor-50-winner",
        "name": "Survivor season 50 winner",
        "category": "entertainment",
        "domain": "entertainment",
        "type": "multi-outcome",
        "frequency": "once_weekly",
        "horizon": "end_of_episode",
        "resolution_rules": "Resolves for whichever contestant wins Survivor Season 50 as announced in the CBS finale broadcast.",
        "geo_scope": "US",
        "key_actors": "CBS, Survivor contestants, Jeff Probst",
        "resolution_type": "event_outcome",
    },
    {
        "slug": "new-stranger-things-episode-released-by-wednesday",
        "name": "Stranger Things new episode release date",
        "category": "entertainment",
        "domain": "entertainment",
        "type": "multi-outcome",
        "frequency": "every_24h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves based on when Netflix releases new Stranger Things Season 5 episodes. YES if episode(s) are available on Netflix by the specified date.",
        "geo_scope": "global",
        "key_actors": "Netflix, Duffer Brothers",
        "resolution_type": "content_release",
    },
    {
        "slug": "gta-6-launch-postponed-again",
        "name": "GTA 6 launch postponed again",
        "category": "entertainment",
        "domain": "gaming",
        "type": "binary",
        "frequency": "every_24h",
        "horizon": "24h+7d",
        "resolution_rules": "Resolves YES if Rockstar Games or Take-Two officially announces a delay to GTA 6 beyond its previously announced Fall 2025 release window. Based on official company communications.",
        "geo_scope": "global",
        "key_actors": "Rockstar Games, Take-Two Interactive",
        "resolution_type": "official_announcement",
    },
]


def main():
    print(f"Building active_contracts.json with {len(CONTRACT_DEFS)} contracts...")

    contracts = []
    for defn in CONTRACT_DEFS:
        event = fetch_event(defn["slug"])
        if event is None:
            print(f"  SKIP (not found): {defn['slug']}")
            continue

        contract = build_contract(
            event=event,
            contract_name=defn["name"],
            category=defn["category"],
            domain=defn["domain"],
            contract_type=defn["type"],
            frequency=defn["frequency"],
            horizon=defn["horizon"],
            resolution_rules=defn.get("resolution_rules", ""),
            geo_scope=defn.get("geo_scope", ""),
            key_actors=defn.get("key_actors", ""),
            resolution_type=defn.get("resolution_type", ""),
        )
        if contract:
            contracts.append(contract)
            otype = "multi" if defn["type"] == "multi-outcome" else "binary"
            n = contract.get("num_outcomes", 2)
            print(f"  OK: {defn['name']} ({otype}, {n} outcomes)")
        else:
            print(f"  SKIP (no markets): {defn['slug']}")

        time.sleep(0.15)

    output = {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_contracts": len(contracts),
        "note": "Curated contract list. Rolling daily contracts (bitcoin, oil, NYC/Miami temp) are managed separately by rolling_contracts.py.",
        "prediction_frequencies": {
            "every_12h": "Run every 12 hours (geopolitics, economics, politics)",
            "every_24h": "Run once daily (sports, tech, entertainment)",
            "once_daily": "Run once each morning (rolling daily, gas prices)",
            "once_weekly": "Run once per week (Survivor, weekly rolling)",
        },
        "contracts": contracts,
    }

    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    out_path = os.path.join(project_dir, "contracts", "active_contracts.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nDone! Wrote {len(contracts)} contracts to active_contracts.json")
    cats = set(c["category"] for c in contracts)
    freqs = set(c["prediction_frequency"] for c in contracts)
    print(f"Categories: {cats}")
    print(f"Frequencies: {freqs}")


if __name__ == "__main__":
    main()
