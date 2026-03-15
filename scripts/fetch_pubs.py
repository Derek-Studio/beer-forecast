#!/usr/bin/env python3
"""
Phase 1: Fetch London pubs from OpenStreetMap via Overpass API and store in pubs.json.

Usage:
    python3 scripts/fetch_pubs.py
"""

import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data" / "pubs.json"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Greater London bounding box: south, west, north, east
LONDON_BBOX = (51.28, -0.51, 51.69, 0.33)

OVERPASS_QUERY = """
[out:json][timeout:60];
(
  node["amenity"="pub"]({south},{west},{north},{east});
  way["amenity"="pub"]({south},{west},{north},{east});
);
out center tags;
""".strip()


def load_pubs() -> list[dict]:
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text())
    return []


def save_pubs(pubs: list[dict]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(pubs, indent=2))


def fetch_pubs_from_osm() -> list[dict]:
    south, west, north, east = LONDON_BBOX
    query = OVERPASS_QUERY.format(south=south, west=west, north=north, east=east)

    print("Querying Overpass API for London pubs...")
    data = query.encode("utf-8")
    req = urllib.request.Request(
        OVERPASS_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    elements = result.get("elements", [])
    print(f"Received {len(elements)} elements from Overpass")
    return elements


def parse_element(el: dict) -> dict | None:
    tags = el.get("tags", {})
    name = tags.get("name", "").strip()
    if not name:
        return None

    # lat/lng: nodes have them directly; ways have a 'center'
    if el["type"] == "node":
        lat = el.get("lat")
        lng = el.get("lon")
    else:
        center = el.get("center", {})
        lat = center.get("lat")
        lng = center.get("lon")

    if lat is None or lng is None:
        return None

    osm_id = f"{el['type']}/{el['id']}"

    # Build address from OSM addr tags
    parts = []
    housenumber = tags.get("addr:housenumber", "")
    street = tags.get("addr:street", "")
    if housenumber and street:
        parts.append(f"{housenumber} {street}")
    elif street:
        parts.append(street)
    city = tags.get("addr:city", "") or tags.get("addr:suburb", "")
    if city:
        parts.append(city)
    address = ", ".join(parts) if parts else None

    website = tags.get("website") or tags.get("contact:website")

    return {
        "osm_id": osm_id,
        "name": name,
        "lat": lat,
        "lng": lng,
        "address": address,
        "website": website,
    }


def upsert_pubs(existing: list[dict], incoming: list[dict]) -> tuple[list[dict], int]:
    by_osm_id = {p["osm_id"]: p for p in existing}
    now = datetime.now(timezone.utc).isoformat()
    upserted = 0

    for pub in incoming:
        osm_id = pub["osm_id"]
        if osm_id in by_osm_id:
            # Update fields but preserve id, created_at, and promotions
            existing_pub = by_osm_id[osm_id]
            existing_pub.update({
                "name": pub["name"],
                "lat": pub["lat"],
                "lng": pub["lng"],
                "address": pub["address"],
                "website": pub["website"],
            })
        else:
            new_id = max((p["id"] for p in by_osm_id.values()), default=0) + 1
            by_osm_id[osm_id] = {
                "id": new_id,
                "osm_id": osm_id,
                "name": pub["name"],
                "lat": pub["lat"],
                "lng": pub["lng"],
                "address": pub["address"],
                "website": pub["website"],
                "created_at": now,
                "promotions": None,
                "promotions_last_updated": None,
                "promotions_query": None,
            }
        upserted += 1

    return list(by_osm_id.values()), upserted


def main() -> None:
    existing = load_pubs()
    elements = fetch_pubs_from_osm()

    parsed = []
    for el in elements:
        pub = parse_element(el)
        if pub:
            parsed.append(pub)

    print(f"Parsed {len(parsed)} named pubs with coordinates")

    pubs, count = upsert_pubs(existing, parsed)
    save_pubs(pubs)
    print(f"Upserted {count} pubs into {DATA_PATH}")
    print(f"Total pubs in file: {len(pubs)}")


if __name__ == "__main__":
    main()
