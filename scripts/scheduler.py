#!/usr/bin/env python3
"""
Phase 4: Scheduler — loop through all pubs in DB, call research agent for each,
skip pubs updated within the last 7 days.

Usage:
    # Run once through all pubs
    python3 scripts/scheduler.py

    # Run only the first N pubs (for testing)
    python3 scripts/scheduler.py --limit 10

    # Run continuously (re-checks after sleeping)
    python3 scripts/scheduler.py --loop
"""

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "pubs.db"
AGENT_PATH = Path("/root/projects/qwen-testing/research_agent.py")
AGENT_PYTHON = Path("/root/projects/qwen-testing/.venv/bin/python3")

PROMOTION_SCHEMA = json.dumps([
    {"description": "", "discount": "", "days": "", "time": ""}
])

STALE_AFTER_DAYS = 7
LOOP_SLEEP_HOURS = 6


def call_agent(pub_name: str, address: str, raw_query: str) -> tuple[object, str]:
    """Call research agent subprocess. Returns (parsed_json_or_none, raw_stdout)."""
    cmd = [
        str(AGENT_PYTHON),
        str(AGENT_PATH),
        raw_query,
        "--schema", PROMOTION_SCHEMA,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        stdout = result.stdout

        lines = stdout.splitlines()
        sep_indices = [i for i, l in enumerate(lines) if l.startswith("=" * 10)]
        if len(sep_indices) >= 2:
            json_text = "\n".join(lines[sep_indices[-2] + 1: sep_indices[-1]]).strip()
        else:
            json_text = stdout.strip()

        try:
            return json.loads(json_text), stdout
        except json.JSONDecodeError:
            return None, stdout

    except subprocess.TimeoutExpired:
        print(f"    TIMEOUT after 300s for {pub_name}")
        return None, ""
    except Exception as e:
        print(f"    ERROR: {e}")
        return None, ""


def is_stale(last_updated: str | None) -> bool:
    if last_updated is None:
        return True
    try:
        ts = datetime.fromisoformat(last_updated)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - ts > timedelta(days=STALE_AFTER_DAYS)
    except ValueError:
        return True


def run_once(conn: sqlite3.Connection, limit: int | None = None) -> None:
    query = """
        SELECT p.id, p.name, p.address,
               pr.last_updated
        FROM pubs p
        LEFT JOIN promotions pr ON pr.pub_id = p.id
        ORDER BY pr.last_updated ASC NULLS FIRST
    """
    rows = conn.execute(query).fetchall()
    if limit:
        rows = rows[:limit]

    total = len(rows)
    print(f"Processing {total} pubs (stale threshold: {STALE_AFTER_DAYS} days)\n")

    skipped = 0
    updated = 0
    failed = 0

    for i, (pub_id, name, address, last_updated) in enumerate(rows, 1):
        if not is_stale(last_updated):
            skipped += 1
            print(f"[{i}/{total}] SKIP {name} (updated {last_updated})")
            continue

        addr_str = address or "London"
        raw_query = f"what promotions and deals are on at {name}, {addr_str}, London"
        print(f"[{i}/{total}] Processing: {name}")
        print(f"    Query: {raw_query}")

        data, _ = call_agent(name, addr_str, raw_query)
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

        if data is not None:
            updated += 1
            print(f"    OK: {json.dumps(data)[:120]}")
        else:
            failed += 1
            print(f"    WARN: agent returned no JSON")

    print(f"\nDone — updated: {updated}, skipped: {skipped}, failed: {failed}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Only process the first N pubs")
    parser.add_argument("--loop", action="store_true",
                        help=f"Keep running, sleeping {LOOP_SLEEP_HOURS}h between passes")
    args = parser.parse_args()

    if not AGENT_PYTHON.exists():
        print(f"ERROR: venv not found at {AGENT_PYTHON}", file=sys.stderr)
        print("Run: cd /root/projects/qwen-testing && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/playwright install chromium", file=sys.stderr)
        sys.exit(1)

    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found. Run fetch_pubs.py first.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)

    if args.loop:
        while True:
            print(f"\n[{datetime.now(timezone.utc).isoformat()}] Starting pass...")
            run_once(conn, args.limit)
            print(f"Sleeping {LOOP_SLEEP_HOURS}h until next pass...")
            time.sleep(LOOP_SLEEP_HOURS * 3600)
    else:
        run_once(conn, args.limit)

    conn.close()


if __name__ == "__main__":
    main()
