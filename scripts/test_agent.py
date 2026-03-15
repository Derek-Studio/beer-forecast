#!/usr/bin/env python3
"""
Phase 2: Test harness — run the research agent on hand-picked London pubs
and compare output against manually verified expected promotions.

Usage:
    python3 scripts/test_agent.py                   # use hardcoded test pubs
    python3 scripts/test_agent.py --ids 1 2 3       # use pubs by id from pubs.json

Requires:
    - Ollama running with qwen3:1.7b
    - qwen-testing repo at /root/projects/qwen-testing with .venv set up
    - pubs.json populated (run fetch_pubs.py first, or the script seeds test pubs)
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data" / "pubs.json"
AGENT_PATH = Path("/root/projects/qwen-testing/research_agent.py")
AGENT_PYTHON = Path("/root/projects/qwen-testing/.venv/bin/python3")

PROMOTION_SCHEMA = json.dumps([
    {"description": "", "discount": "", "days": "", "time": "", "source_url": ""}
])

# Hand-picked pubs with known promotions for ground-truth comparison.
TEST_PUBS = [
    {
        "osm_id": "test/0",
        "name": "The Goose",
        "address": "248 North End Road, Fulham, London",
        "website": "https://www.jdwetherspoon.com/pubs/all-pubs/england/london/the-goose-fulham",
        "lat": 51.4803,
        "lng": -0.1957,
        "expected": [
            {"description": "Real ale club", "discount": "discounted ales", "days": "daily", "time": "", "source_url": ""},
            {"description": "Club soda / soft drinks", "discount": "free", "days": "daily", "time": "", "source_url": ""},
        ],
    },
    {
        "osm_id": "test/1",
        "name": "Prince of Peckham",
        "address": "1 Clayton Road, Peckham, London SE15 5JA",
        "website": "https://princeofpeckham.co.uk",
        "lat": 51.4697,
        "lng": -0.0619,
        "expected": [
            {"description": "Thirsty Thursdays happy hour — double spirit + mixer", "discount": "£6", "days": "Thursday", "time": "22:00-00:00", "source_url": "https://princeofpeckham.co.uk/listings/late-night-happy-hour/"},
            {"description": "All-day cocktails", "discount": "£7", "days": "Wednesday", "time": "all day", "source_url": ""},
        ],
    },
    {
        "osm_id": "test/2",
        "name": "Fabal Beerhall",
        "address": "Arch 88, Druid Street, Bermondsey, London SE1 2HQ",
        "website": "https://fabalbeers.com",
        "lat": 51.5007,
        "lng": -0.0806,
        "expected": [
            {"description": "Quiz and karaoke night — win £75 bar tab", "discount": "£75 bar tab", "days": "Thursday", "time": "19:00-22:45", "source_url": ""},
        ],
    },
    {
        "osm_id": "test/3",
        "name": "The Last Judgment",
        "address": "95 Chancery Lane, London WC2A 1DT",
        "website": "https://thelastjudgment.co.uk",
        "lat": 51.5165,
        "lng": -0.1126,
        "expected": [
            {"description": "Footsie Fridays — drink prices on live stock tickers", "discount": "variable", "days": "Friday", "time": "17:30", "source_url": "https://thelastjudgment.co.uk/whats-on/"},
        ],
    },
]


def load_pubs() -> list[dict]:
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text())
    return []


def save_pubs(pubs: list[dict]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(pubs, indent=2))


def seed_test_pubs(pubs: list[dict]) -> list[dict]:
    """Insert test pubs if not already present. Returns updated pubs list."""
    by_osm_id = {p["osm_id"]: p for p in pubs}
    now = datetime.now(timezone.utc).isoformat()
    next_id = max((p["id"] for p in pubs), default=0) + 1

    for pub in TEST_PUBS:
        if pub["osm_id"] not in by_osm_id:
            by_osm_id[pub["osm_id"]] = {
                "id": next_id,
                "osm_id": pub["osm_id"],
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
            next_id += 1

    return list(by_osm_id.values())


def call_agent(pub_name: str, address: str) -> tuple[object, str]:
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        stdout = result.stdout
        if result.returncode != 0:
            print(f"  Agent exited with code {result.returncode}")
            if result.stderr:
                print(f"  stderr: {result.stderr[:500]}")

        lines = stdout.splitlines()
        sep_indices = [i for i, l in enumerate(lines) if l.startswith("=" * 10)]
        if len(sep_indices) >= 2:
            raw_json = "\n".join(lines[sep_indices[-2] + 1: sep_indices[-1]]).strip()
        else:
            raw_json = stdout.strip()

        try:
            return json.loads(raw_json), stdout
        except json.JSONDecodeError:
            return None, stdout

    except subprocess.TimeoutExpired:
        print("  ERROR: Agent timed out after 300s")
        return None, ""
    except Exception as e:
        print(f"  ERROR calling agent: {e}")
        return None, ""


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", type=int, nargs="+",
                        help="Pub IDs from pubs.json to test instead of hardcoded list")
    args = parser.parse_args()

    if not AGENT_PATH.exists():
        print(f"ERROR: research_agent.py not found at {AGENT_PATH}", file=sys.stderr)
        sys.exit(1)

    pubs = load_pubs()

    if args.ids:
        by_id = {p["id"]: p for p in pubs}
        pubs_to_test = []
        for pub_id in args.ids:
            if pub_id in by_id:
                pubs_to_test.append({**by_id[pub_id], "expected": []})
            else:
                print(f"WARNING: pub id {pub_id} not found in pubs.json", file=sys.stderr)
    else:
        pubs = seed_test_pubs(pubs)
        save_pubs(pubs)
        by_osm_id = {p["osm_id"]: p for p in pubs}
        pubs_to_test = [
            {**by_osm_id[tp["osm_id"]], "expected": tp["expected"]}
            for tp in TEST_PUBS
        ]

    print(f"Testing {len(pubs_to_test)} pubs\n")

    results = []
    for pub in pubs_to_test:
        query_str = f"what promotions and deals are on at {pub['name']}, {pub.get('address') or 'London'}, London"
        parsed, _ = call_agent(pub["name"], pub.get("address") or "London")

        # Save result back into pubs.json
        now = datetime.now(timezone.utc).isoformat()
        by_id = {p["id"]: p for p in pubs}
        by_id[pub["id"]]["promotions"] = parsed
        by_id[pub["id"]]["promotions_last_updated"] = now
        by_id[pub["id"]]["promotions_query"] = query_str
        pubs = list(by_id.values())
        save_pubs(pubs)

        passed = compare(pub["name"], parsed, pub.get("expected", []))
        results.append((pub["name"], passed))

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    passed_count = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"\n{passed_count}/{len(results)} passed")


if __name__ == "__main__":
    main()
