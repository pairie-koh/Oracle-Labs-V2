"""
Oracle Lab — lessons.py
Feedback loop: scan past predictions, compute per-contract and per-domain
performance stats, inject lessons into future prompts.

Two entry points:
  rebuild_lessons_cache()  — called after scoring (evaluate_rolling.py)
  build_lessons_block()    — called during prompt building (llm_forecast.py)
"""

import glob
import json
import os
from datetime import datetime, timezone

CACHE_PATH = os.path.join("data", "lessons_cache.json")
PREDICTIONS_DIR = "llm_predictions"
CONTRACTS_PATH = os.path.join("contracts", "active_contracts.json")

MAX_HISTORY = 5       # last N predictions to show in prompt
MIN_CONTRACT = 2      # min predictions before showing per-contract lesson
MIN_DOMAIN = 5        # min predictions before showing per-domain lesson
BIAS_THRESHOLD = 0.02 # |avg_error| above this = bias

_cache = None  # module-level singleton


# ── Cache Building ────────────────────────────────────────────────────────────

def _load_domain_lookup():
    """Build slug -> (category, domain) mapping from active_contracts.json."""
    lookup = {}
    if not os.path.exists(CONTRACTS_PATH):
        return lookup
    try:
        with open(CONTRACTS_PATH) as f:
            data = json.load(f)
        for c in data.get("contracts", []):
            slug = c.get("slug", "")
            if slug:
                lookup[slug] = (c.get("category", ""), c.get("domain", ""))
    except Exception:
        pass
    return lookup


def rebuild_lessons_cache():
    """Scan all prediction files, compute stats, write cache."""
    domain_lookup = _load_domain_lookup()

    # Collect all predictions grouped by contract key
    by_contract = {}  # key -> list of {timestamp, prediction, market_price, tier, type}

    pattern = os.path.join(PREDICTIONS_DIR, "predictions_*.json")
    files = sorted(glob.glob(pattern))

    for path in files:
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            continue

        for p in data.get("predictions", []):
            key = p.get("key", "")
            if not key:
                continue

            entry = {
                "timestamp": p.get("timestamp", ""),
                "tier": p.get("tier", ""),
                "type": p.get("type", "binary"),
            }

            if p.get("type") == "binary":
                pred = p.get("prediction")
                mkt = p.get("market_price")
                if pred is None or mkt is None:
                    continue
                entry["prediction"] = pred
                entry["market_price"] = mkt
                entry["signed_error"] = pred - mkt
            elif p.get("type") == "multi-outcome":
                preds = p.get("outcome_predictions", [])
                mkts = p.get("outcome_market_prices", [])
                if not preds or not mkts or len(preds) != len(mkts):
                    continue
                # Compute average absolute divergence across outcomes
                divs = [abs(pr - mk) for pr, mk in zip(preds, mkts)]
                entry["avg_outcome_div"] = sum(divs) / len(divs)
                entry["max_outcome_div"] = max(divs)
                entry["n_outcomes"] = len(preds)
            else:
                continue

            by_contract.setdefault(key, []).append(entry)

    # Sort each contract's history by timestamp
    for key in by_contract:
        by_contract[key].sort(key=lambda e: e["timestamp"])

    # Build per-contract stats
    per_contract = {}
    for key, entries in by_contract.items():
        binary_entries = [e for e in entries if e["type"] == "binary"]
        multi_entries = [e for e in entries if e["type"] == "multi-outcome"]

        stats = {
            "n_predictions": len(entries),
            "history": entries[-MAX_HISTORY:],  # last N for prompt display
        }

        if binary_entries:
            errors = [e["signed_error"] for e in binary_entries]
            avg_err = sum(errors) / len(errors)
            avg_abs = sum(abs(e) for e in errors) / len(errors)
            stats["avg_signed_error"] = round(avg_err, 3)
            stats["avg_abs_error"] = round(avg_abs, 3)
            if avg_err < -BIAS_THRESHOLD:
                stats["bias"] = "TOO LOW"
            elif avg_err > BIAS_THRESHOLD:
                stats["bias"] = "TOO HIGH"
            else:
                stats["bias"] = "neutral"

        if multi_entries:
            avg_divs = [e["avg_outcome_div"] for e in multi_entries]
            stats["avg_multi_div"] = round(sum(avg_divs) / len(avg_divs), 3)

        per_contract[key] = stats

    # Build per-domain stats
    per_domain = {}
    for key, entries in by_contract.items():
        cat, dom = domain_lookup.get(key, ("", ""))
        # Use category as primary domain grouping
        domain_key = cat or dom
        if not domain_key:
            continue

        if domain_key not in per_domain:
            per_domain[domain_key] = {"errors": [], "abs_errors": [], "multi_divs": []}

        for e in entries:
            if e["type"] == "binary" and "signed_error" in e:
                per_domain[domain_key]["errors"].append(e["signed_error"])
                per_domain[domain_key]["abs_errors"].append(abs(e["signed_error"]))
            elif e["type"] == "multi-outcome" and "avg_outcome_div" in e:
                per_domain[domain_key]["multi_divs"].append(e["avg_outcome_div"])

    # Finalize domain stats
    domain_stats = {}
    for domain_key, raw in per_domain.items():
        n = len(raw["errors"]) + len(raw["multi_divs"])
        if n == 0:
            continue

        stats = {"n_predictions": n}

        if raw["errors"]:
            avg_err = sum(raw["errors"]) / len(raw["errors"])
            avg_abs = sum(raw["abs_errors"]) / len(raw["abs_errors"])
            stats["avg_signed_error"] = round(avg_err, 3)
            stats["avg_abs_error"] = round(avg_abs, 3)
            if avg_err < -BIAS_THRESHOLD:
                stats["bias"] = "TOO LOW"
            elif avg_err > BIAS_THRESHOLD:
                stats["bias"] = "TOO HIGH"
            else:
                stats["bias"] = "neutral"

        if raw["multi_divs"]:
            stats["avg_multi_div"] = round(
                sum(raw["multi_divs"]) / len(raw["multi_divs"]), 3
            )

        domain_stats[domain_key] = stats

    # Write cache
    cache = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_files_scanned": len(files),
        "per_contract": per_contract,
        "per_domain": domain_stats,
    }

    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=2)
    except OSError as e:
        print(f"  WARNING: Could not write lessons cache: {e}")

    n_contracts = len(per_contract)
    n_domains = len(domain_stats)
    print(f"  Lessons cache: {n_contracts} contracts, {n_domains} domains "
          f"(from {len(files)} prediction files)")
    return cache


# ── Cache Loading ─────────────────────────────────────────────────────────────

def load_lessons_cache():
    """Load cache from disk with in-memory singleton."""
    global _cache
    if _cache is not None:
        return _cache
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH) as f:
            _cache = json.load(f)
        return _cache
    except Exception:
        return {}


def reset_cache():
    """Clear the in-memory cache (useful between test runs)."""
    global _cache
    _cache = None


# ── Prompt Block Building ─────────────────────────────────────────────────────

def build_lessons_block(contract_key, domain=None):
    """Build a text block for prompt injection.

    Returns a formatted string showing past performance on this contract
    and/or domain, or "" if insufficient data.
    """
    cache = load_lessons_cache()
    if not cache:
        return ""

    lines = []

    # Per-contract lesson
    contract_data = cache.get("per_contract", {}).get(contract_key, {})
    n_contract = contract_data.get("n_predictions", 0)

    if n_contract >= MIN_CONTRACT:
        history = contract_data.get("history", [])
        binary_hist = [h for h in history if h.get("type") == "binary"]
        multi_hist = [h for h in history if h.get("type") == "multi-outcome"]

        if binary_hist:
            preds = [f"{h['prediction']:.2f}" for h in binary_hist[-MAX_HISTORY:]]
            mkts = [f"{h['market_price']:.2f}" for h in binary_hist[-MAX_HISTORY:]]
            lines.append(
                f"PAST PERFORMANCE ON THIS CONTRACT ({len(binary_hist)} predictions):"
            )
            lines.append(f"  You: {', '.join(preds)} | Market: {', '.join(mkts)}")

            bias = contract_data.get("bias", "")
            avg_err = contract_data.get("avg_signed_error", 0)
            if bias and bias != "neutral":
                lines.append(
                    f"  Bias: consistently {bias} vs market (avg error: {avg_err:+.3f})"
                )

        elif multi_hist:
            divs = [f"{h.get('avg_outcome_div', 0):.2f}" for h in multi_hist[-MAX_HISTORY:]]
            avg_div = contract_data.get("avg_multi_div", 0)
            lines.append(
                f"PAST PERFORMANCE ON THIS CONTRACT ({len(multi_hist)} predictions):"
            )
            lines.append(f"  Avg outcome divergence: {', '.join(divs)} (mean: {avg_div:.3f})")

    # Per-domain lesson (as fallback or supplement)
    domain_data = cache.get("per_domain", {}).get(domain or "", {})
    n_domain = domain_data.get("n_predictions", 0)

    if n_domain >= MIN_DOMAIN and n_contract < 3:
        bias = domain_data.get("bias", "")
        avg_abs = domain_data.get("avg_abs_error", 0)
        avg_multi = domain_data.get("avg_multi_div", 0)

        domain_line = f"DOMAIN PATTERN ({domain}, {n_domain} predictions): "
        if bias and bias != "neutral":
            domain_line += f"you tend to predict {bias} (avg abs error: {avg_abs:.3f})"
        elif avg_multi:
            domain_line += f"avg outcome divergence: {avg_multi:.3f}"
        else:
            domain_line += f"avg abs error: {avg_abs:.3f}"

        lines.append(domain_line)

    if not lines:
        return ""

    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "rebuild":
        rebuild_lessons_cache()
    elif len(sys.argv) > 1 and sys.argv[1] == "show":
        # Show lessons for all contracts
        rebuild_lessons_cache()
        reset_cache()
        cache = load_lessons_cache()
        for key in sorted(cache.get("per_contract", {}).keys()):
            cat = ""
            domain_lookup = _load_domain_lookup()
            if key in domain_lookup:
                cat = domain_lookup[key][0]
            block = build_lessons_block(key, domain=cat)
            if block:
                print(f"\n--- {key} ---")
                print(block)
        print(f"\n--- Domain summaries ---")
        for dom, stats in cache.get("per_domain", {}).items():
            print(f"  {dom}: {stats}")
    else:
        print("Usage: python lessons.py rebuild   — rebuild cache from prediction files")
        print("       python lessons.py show      — rebuild + show all lessons")
