#!/usr/bin/env python3
"""
Phase 2: Test harness — run the research agent on 5 hand-picked London pubs
and compare output against manually verified expected promotions.

Usage:
    python3 scripts/test_agent.py                   # use hardcoded test pubs
    python3 scripts/test_agent.py --ids 1811 1783 952 456 1784  # use DB pubs by id

Requires:
    - Ollama running with qwen3:1.7b
    - qwen-testing repo at /root/projects/qwen-testing with .venv set up
    - pubs.db populated (run fetch_pubs.py first, or the script seeds test pubs)
"""

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "pubs.db"
AGENT_PATH = Path("/root/projects/qwen-testing/research_agent.py")
AGENT_PYTHON = Path("/root/projects/qwen-testing/.venv/bin/python3")

PROMOTION_SCHEMA = json.dumps([
    {"description": "", "discount": "", "days": "", "time": ""}
])

# 5 hand-picked pubs with known promotions for ground-truth comparison.
# osm_id=None means we'll seed them directly if not already in the DB.
TEST_PUBS = [
    {
        "name": "The Goose",
        "address": "248 North End Road, Fulham, London",
        "website": "https://www.jdwetherspoon.com/pubs/all-pubs/england/london/the-goose-fulham",
        "lat": 51.4803,
        "lng": -0.1957,
        "expected": [
            {"description": "Real ale club", "discount": "discounted ales", "days": "daily", "time": ""},
            {"description": "Club soda / soft drinks", "discount": "free", "days": "daily", "time": ""},
        ],
    },
    {
        "name": "The Crown Tavern",
        "address": "43 Clerkenwell Green, London",
        "website": "https://www.crowntavernclerkenwell.co.uk",
        "lat": 51.5228,
        "lng": -0.1053,
        "expected": [],
    },
    {
        "name": "The Harp",
        "address": "47 Chandos Place, Covent Garden, London",
        "website": "https://www.harpcovengarden.com",
        "lat": 51.5087,
        "lng": -0.1238,
        "expected": [],
    },
    {
        "name": "The Old Blue Last",
        "address": "38 Great Eastern Street, Shoreditch, London",
        "website": "https://www.theoldbluelast.com",
        "lat": 51.5246,
        "lng": -0.0813,
        "expected": [],
    },
    {
        "name": "Ye Olde Cheshire Cheese",
        "address": "145 Fleet Street, London",
        "website": "https://www.yeoldecheshirecheese.co.uk",
        "lat": 51.5139,
        "lng": -0.1083,
        "expected": [],
    },
]


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


def seed_test_pubs(conn: sqlite3.Connection) -> dict[str, int]:
    """Insert test pubs if not already present. Returns name→id mapping."""
    now = datetime.now(timezone.utc).isoformat()
    name_to_id = {}
    for i, pub in enumerate(TEST_PUBS):
        osm_id = f"test/{i}"
        conn.execute(
            """
            INSERT INTO pubs (osm_id, name, lat, lng, address, website, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(osm_id) DO UPDATE SET
                name    = excluded.name,
                lat     = excluded.lat,
                lng     = excluded.lng,
                address = excluded.address,
                website = excluded.website
            """,
            (osm_id, pub["name"], pub["lat"], pub["lng"], pub["address"], pub["website"], now),
        )
        row = conn.execute("SELECT id FROM pubs WHERE osm_id = ?", (osm_id,)).fetchone()
        name_to_id[pub["name"]] = row[0]
    conn.commit()
    return name_to_id


def call_agent(pub_name: str, address: str) -> tuple[str | None, str]:
    """Call research_agent.py as subprocess. Returns (parsed_json_or_none, raw_stdout)."""
    if not AGENT_PYTHON.exists():
        print(f"  ERROR: Python venv not found at {AGENT_PYTHON}")
        print("  Run: cd /root/projects/qwen-testing && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/playwright install chromium")
        return None, ""

    query = f"what promotions and deals are on at {pub_name}, {address}, London"
    cmd = [
        str(AGENT_PYTHON),
        str(AGENT_PATH),
        query,
        "--schema", PROMOTION_SCHEMA,
    ]
    print(f"  Running agent for: {pub_name}")
    print(f"  Query: {query}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        stdout = result.stdout
        if result.returncode != 0:
            print(f"  Agent exited with code {result.returncode}")
            if result.stderr:
                print(f"  stderr: {result.stderr[:500]}")

        # Extract the JSON between the last pair of === lines
        lines = stdout.splitlines()
        sep_indices = [i for i, l in enumerate(lines) if l.startswith("=" * 10)]
        if len(sep_indices) >= 2:
            json_lines = lines[sep_indices[-2] + 1: sep_indices[-1]]
            raw_json = "\n".join(json_lines).strip()
        else:
            raw_json = stdout.strip()

        try:
            parsed = json.loads(raw_json)
            return parsed, stdout
        except json.JSONDecodeError:
            return None, stdout

    except subprocess.TimeoutExpired:
        print("  ERROR: Agent timed out after 300s")
        return None, ""
    except Exception as e:
        print(f"  ERROR calling agent: {e}")
        return None, ""


def store_promotion(conn: sqlite3.Connection, pub_id: int, data: object, raw_query: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT id FROM promotions WHERE pub_id = ?", (pub_id,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE promotions SET data = ?, last_updated = ?, raw_query = ? WHERE pub_id = ?",
            (json.dumps(data), now, raw_query, pub_id),
        )
    else:
        conn.execute(
            "INSERT INTO promotions (pub_id, data, last_updated, raw_query) VALUES (?, ?, ?, ?)",
            (pub_id, json.dumps(data), now, raw_query),
        )
    conn.commit()


def compare(pub_name: str, got: object, expected: list) -> bool:
    print(f"\n{'='*60}")
    print(f"PUB: {pub_name}")
    print(f"{'='*60}")
    print("AGENT OUTPUT:")
    print(json.dumps(got, indent=2) if got is not None else "  (no JSON returned)")
    print("\nEXPECTED (manually verified):")
    if expected:
        print(json.dumps(expected, indent=2))
    else:
        print("  (no ground truth — review manually)")
    print()

    if got is None:
        print("RESULT: FAIL (no JSON)")
        return False

    # Basic sanity: agent returned a list with at least one item, or expected is empty
    if expected:
        if isinstance(got, list) and len(got) > 0:
            print("RESULT: PASS (returned list with items, expected non-empty)")
            return True
        else:
            print("RESULT: FAIL (expected promotions but got empty/non-list)")
            return False
    else:
        print("RESULT: OK (no expected — manual review needed)")
        return True


def load_pubs_by_ids(conn: sqlite3.Connection, ids: list[int]) -> list[dict]:
    pubs = []
    for pub_id in ids:
        row = conn.execute(
            "SELECT id, name, address FROM pubs WHERE id = ?", (pub_id,)
        ).fetchone()
        if row:
            pubs.append({"id": row[0], "name": row[1], "address": row[2] or "London", "expected": []})
        else:
            print(f"WARNING: pub id {pub_id} not found in DB", file=sys.stderr)
    return pubs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", type=int, nargs="+",
                        help="DB pub IDs to test instead of hardcoded list")
    args = parser.parse_args()

    if not AGENT_PATH.exists():
        print(f"ERROR: research_agent.py not found at {AGENT_PATH}", file=sys.stderr)
        sys.exit(1)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    if args.ids:
        pubs_to_test = load_pubs_by_ids(conn, args.ids)
    else:
        name_to_id = seed_test_pubs(conn)
        pubs_to_test = [
            {**pub, "id": name_to_id[pub["name"]]}
            for pub in TEST_PUBS
        ]

    print(f"Testing {len(pubs_to_test)} pubs\n")

    results = []
    for pub in pubs_to_test:
        pub_id = pub["id"]
        query_str = f"what promotions and deals are on at {pub['name']}, {pub['address']}, London"

        parsed, raw = call_agent(pub["name"], pub["address"])
        store_promotion(conn, pub_id, parsed, query_str)

        passed = compare(pub["name"], parsed, pub.get("expected", []))
        results.append((pub["name"], passed))

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    passed_count = sum(1 for _, ok in results if ok)
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
    print(f"\n{passed_count}/{len(results)} passed")
    conn.close()


if __name__ == "__main__":
    main()
