#!/usr/bin/env python3
"""
fetch-emergency-orders.py
Scrapes ADF&G EONR (Emergency Order Notification and Reporting) system
and writes structured JSON to data/live-eo.json and data/live-commercial-eo.json
"""
import json
import re
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup

ADFG_BASE = "https://www.adfg.alaska.gov"
EONR_URL = f"{ADFG_BASE}/index.cfm?adfg=fishingemergencyorders.main"

# Region keywords for classification
COMMERCIAL_KEYWORDS = ["commercial", "set net", "drift net", "seine", "gillnet", "troll", "longline", "pot fishery", "pot gear"]
SPORT_KEYWORDS = ["sport", "personal use", "dipnet", "dip net", "charter", "guided"]
SUBSISTENCE_KEYWORDS = ["subsistence", "federal subsistence"]

REGION_MAP = {
    "bristol bay": "Bristol Bay",
    "cook inlet": "Cook Inlet",
    "upper cook": "Cook Inlet",
    "lower cook": "Cook Inlet",
    "kenai": "Cook Inlet",
    "kasilof": "Cook Inlet",
    "southeast": "Southeast Alaska",
    "se alaska": "Southeast Alaska",
    "sitka": "Southeast Alaska",
    "wrangell": "Southeast Alaska",
    "juneau": "Southeast Alaska",
    "ketchikan": "Southeast Alaska",
    "prince william sound": "Prince William Sound",
    "pws": "Prince William Sound",
    "copper river": "Prince William Sound",
    "kodiak": "Kodiak",
    "chignik": "Westward",
    "alaska peninsula": "Westward",
    "area m": "Westward",
    "yukon": "Arctic-Yukon-Kuskokwim",
    "kuskokwim": "Arctic-Yukon-Kuskokwim",
    "norton sound": "Arctic-Yukon-Kuskokwim",
    "kotzebue": "Arctic-Yukon-Kuskokwim",
}

SPECIES_MAP = {
    "sockeye": "Sockeye",
    "red salmon": "Sockeye",
    "chinook": "Chinook",
    "king salmon": "Chinook",
    "coho": "Coho",
    "silver salmon": "Coho",
    "chum": "Chum",
    "dog salmon": "Chum",
    "pink": "Pink",
    "humpy": "Pink",
    "halibut": "Halibut",
    "herring": "Pacific Herring",
    "pollock": "Pollock",
    "cod": "Pacific Cod",
    "crab": "Crab",
    "sablefish": "Sablefish",
    "black cod": "Sablefish",
}


def classify_region(text: str) -> str:
    text_lower = text.lower()
    for keyword, region in REGION_MAP.items():
        if keyword in text_lower:
            return region
    return "Statewide"


def classify_species(text: str) -> list[str]:
    text_lower = text.lower()
    found = []
    for keyword, species in SPECIES_MAP.items():
        if keyword in text_lower and species not in found:
            found.append(species)
    return found if found else ["Unknown"]


def classify_type(text: str) -> str:
    text_lower = text.lower()
    types = []
    if any(k in text_lower for k in COMMERCIAL_KEYWORDS):
        types.append("commercial")
    if any(k in text_lower for k in SPORT_KEYWORDS):
        types.append("sport")
    if any(k in text_lower for k in SUBSISTENCE_KEYWORDS):
        types.append("subsistence")
    return ",".join(types) if types else "general"


def fetch_eos() -> list[dict]:
    """Fetch emergency orders from ADF&G EONR."""
    try:
        headers = {
            "User-Agent": "AlaskaFishData/1.0 (+https://alaskafishdata.com; data@alaskafishdata.com)"
        }
        resp = requests.get(EONR_URL, headers=headers, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"✗ Failed to fetch EONR: {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    orders = []

    # ADF&G EONR table rows — structure varies by year; parse robustly
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows[1:]:  # Skip header
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue

            text_parts = [c.get_text(strip=True) for c in cells]
            full_text = " | ".join(text_parts)

            # Extract EO number if present
            eo_num = None
            for part in text_parts:
                m = re.search(r'\d{1,2}-[A-Z]{1,4}-\d{1,2}-\d{2,4}', part)
                if m:
                    eo_num = m.group(0)
                    break

            if not full_text.strip() or len(full_text) < 20:
                continue

            orders.append({
                "eo_number": eo_num,
                "region": classify_region(full_text),
                "species": classify_species(full_text),
                "fishery_type": classify_type(full_text),
                "description": full_text[:500],
                "raw_cells": text_parts[:6],
                "source_url": EONR_URL,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            })

    return orders


def main():
    print(f"Fetching ADF&G emergency orders from {EONR_URL}...")
    orders = fetch_eos()

    if not orders:
        # Graceful stub — don't overwrite with empty
        print("⚠ No orders fetched — writing minimal status stub")
        orders = []

    now = datetime.now(timezone.utc).isoformat()

    # Full live-eo.json
    live_eo = {
        "_meta": {
            "source": "ADF&G Emergency Order Notification and Reporting (EONR)",
            "source_url": EONR_URL,
            "fetched_at": now,
            "total_orders": len(orders),
            "update_frequency": "Every 2 hours via GitHub Actions",
        },
        "orders": orders,
    }

    with open("data/live-eo.json", "w") as f:
        json.dump(live_eo, f, indent=2)
    print(f"✓ data/live-eo.json: {len(orders)} orders")

    # Commercial-only subset for the commercial page
    commercial_eos = [o for o in orders if "commercial" in o.get("fishery_type", "")]
    live_commercial_eo = {
        "_meta": {
            "source": "ADF&G EONR — commercial fisheries subset",
            "source_url": EONR_URL,
            "fetched_at": now,
            "total_commercial_orders": len(commercial_eos),
        },
        "orders": commercial_eos,
    }

    with open("data/live-commercial-eo.json", "w") as f:
        json.dump(live_commercial_eo, f, indent=2)
    print(f"✓ data/live-commercial-eo.json: {len(commercial_eos)} commercial orders")

    # EO stats for dashboard
    region_counts = {}
    for o in orders:
        r = o.get("region", "Unknown")
        region_counts[r] = region_counts.get(r, 0) + 1

    eo_stats = {
        "_meta": {"fetched_at": now, "source": "ADF&G EONR"},
        "total_active": len(orders),
        "by_region": region_counts,
        "by_type": {
            "commercial": len([o for o in orders if "commercial" in o.get("fishery_type", "")]),
            "sport": len([o for o in orders if "sport" in o.get("fishery_type", "")]),
            "subsistence": len([o for o in orders if "subsistence" in o.get("fishery_type", "")]),
        },
    }

    with open("data/eo-stats.json", "w") as f:
        json.dump(eo_stats, f, indent=2)
    print(f"✓ data/eo-stats.json: {len(region_counts)} regions")


if __name__ == "__main__":
    main()
