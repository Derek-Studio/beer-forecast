#!/usr/bin/env python3
"""
Phase 1: Fetch London pubs from OpenStreetMap via Overpass API and store in SQLite.

Usage:
    python3 scripts/fetch_pubs.py
"""

import json
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "pubs.db"
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


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pubs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            osm_id      TEXT UNIQUE NOT NULL,
            name        TEXT,
            lat         REAL NOT NULL,
            lng         REAL NOT NULL,
            address     TEXT,
            website     TEXT,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS promotions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            pub_id       INTEGER NOT NULL REFERENCES pubs(id),
            data         TEXT,
            last_updated TEXT,
            raw_query    TEXT
        );
    """)
    conn.commit()


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


def upsert_pubs(conn: sqlite3.Connection, pubs: list[dict]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for pub in pubs:
        try:
            conn.execute(
                """
                INSERT INTO pubs (osm_id, name, lat, lng, address, website, created_at)
                VALUES (:osm_id, :name, :lat, :lng, :address, :website, :created_at)
                ON CONFLICT(osm_id) DO UPDATE SET
                    name    = excluded.name,
                    lat     = excluded.lat,
                    lng     = excluded.lng,
                    address = excluded.address,
                    website = excluded.website
                """,
                {**pub, "created_at": now},
            )
            inserted += 1
        except sqlite3.Error as e:
            print(f"  Warning: could not insert {pub['osm_id']}: {e}")
    conn.commit()
    return inserted


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    elements = fetch_pubs_from_osm()

    pubs = []
    for el in elements:
        parsed = parse_element(el)
        if parsed:
            pubs.append(parsed)

    print(f"Parsed {len(pubs)} named pubs with coordinates")

    count = upsert_pubs(conn, pubs)
    print(f"Upserted {count} pubs into {DB_PATH}")

    total = conn.execute("SELECT COUNT(*) FROM pubs").fetchone()[0]
    print(f"Total pubs in DB: {total}")
    conn.close()


if __name__ == "__main__":
    main()
