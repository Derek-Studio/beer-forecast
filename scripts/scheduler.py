#!/usr/bin/env python3
"""
Phase 4: Scheduler — loop through all pubs in pubs.json, call research agent for each,
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
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data" / "pubs.json"
AGENT_PATH = Path("/root/projects/qwen-testing/research_agent.py")
AGENT_PYTHON = Path("/root/projects/qwen-testing/.venv/bin/python3")

PROMOTION_SCHEMA = json.dumps([
    {"description": "", "discount": "", "days": "", "time": "", "source_url": ""}
])

RICH_SCHEMA = json.dumps({
    "promotions": [{"title": "", "description": "", "discount": "", "days": "", "time": "", "source_url": "", "extract_string": ""}],
    "events": [{"title": "", "description": "", "date": "", "time": "", "source_url": "", "extract_string": ""}],
    "opening_times": {"monday": "", "tuesday": "", "wednesday": "", "thursday": "", "friday": "", "saturday": "", "sunday": "", "source_url": ""},
    "description": {"text": "", "source_url": ""},
    "facilities": [{"name": "", "source_url": ""}],
    "pub_emoji": "",
})

STALE_AFTER_DAYS = 7
LOOP_SLEEP_HOURS = 6
DEFAULT_PROVIDER = os.environ.get("AGENT_PROVIDER", "minimax")         # minimax (default), claude, ollama
DEFAULT_SEARCH_PROVIDER = os.environ.get("AGENT_SEARCH_PROVIDER", "brave")  # brave or ddg


def load_pubs() -> list[dict]:
    return json.loads(DATA_PATH.read_text())


def save_pubs(pubs: list[dict]) -> None:
    DATA_PATH.write_text(json.dumps(pubs, indent=2))


def call_agent(pub_name: str, address: str, raw_query: str, start_url: str | None = None, provider: str = DEFAULT_PROVIDER, search_provider: str = DEFAULT_SEARCH_PROVIDER, rich_mode: bool = True) -> tuple[object, str]:
    """Call research agent subprocess. Returns (parsed_json_or_none, raw_stdout)."""
    if rich_mode:
        cmd = [
            str(AGENT_PYTHON),
            str(AGENT_PATH),
            raw_query,
            "--schema", RICH_SCHEMA,
            "--provider", provider,
            "--search-provider", search_provider,
            "--pub-site-mode",
            "--pub-name", pub_name,
            "--pub-address", address,
        ]
        if start_url:
            cmd += ["--start-url", start_url]
    else:
        cmd = [
            str(AGENT_PYTHON),
            str(AGENT_PATH),
            raw_query,
            "--schema", PROMOTION_SCHEMA,
            "--provider", provider,
            "--search-provider", search_provider,
        ]
        if start_url:
            cmd += ["--start-url", start_url]
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


def run_once(pubs: list[dict], limit: int | None = None) -> list[dict]:
    # Sort by last updated ascending so stalest pubs go first
    ordered = sorted(pubs, key=lambda p: p.get("promotions_last_updated") or "")
    if limit:
        ordered = ordered[:limit]

    total = len(ordered)
    print(f"Processing {total} pubs (stale threshold: {STALE_AFTER_DAYS} days)\n")

    skipped = updated = failed = 0
    by_id = {p["id"]: p for p in pubs}

    for i, pub in enumerate(ordered, 1):
        last_updated = pub.get("promotions_last_updated")
        if not is_stale(last_updated):
            skipped += 1
            print(f"[{i}/{total}] SKIP {pub['name']} (updated {last_updated})")
            continue

        addr_str = pub.get("address") or "London"
        raw_query = f"what promotions and deals are on at {pub['name']}, {addr_str}, London"
        print(f"[{i}/{total}] Processing: {pub['name']}")
        print(f"    Query: {raw_query}")

        data, _ = call_agent(pub["name"], addr_str, raw_query, pub.get("website"), DEFAULT_PROVIDER)
        now = datetime.now(timezone.utc).isoformat()

        if isinstance(data, dict):
            by_id[pub["id"]]["promotions"]        = data.get("promotions") or []
            by_id[pub["id"]]["events"]            = data.get("events") or []
            by_id[pub["id"]]["opening_times"]     = data.get("opening_times") or {}
            by_id[pub["id"]]["venue_description"] = data.get("description") or {}
            by_id[pub["id"]]["facilities"]        = data.get("facilities") or []
            if data.get("pub_emoji"):
                by_id[pub["id"]]["venue_emoji"]   = data.get("pub_emoji")
        elif isinstance(data, list):
            by_id[pub["id"]]["promotions"] = data  # legacy compat
        by_id[pub["id"]]["promotions_last_updated"] = now
        by_id[pub["id"]]["promotions_query"] = raw_query

        if data is not None:
            updated += 1
            print(f"    OK: {json.dumps(data)[:120]}")
        else:
            failed += 1
            print(f"    WARN: agent returned no JSON")

    print(f"\nDone — updated: {updated}, skipped: {skipped}, failed: {failed}")
    return list(by_id.values())


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

    if not DATA_PATH.exists():
        print(f"ERROR: {DATA_PATH} not found. Run fetch_pubs.py first.", file=sys.stderr)
        sys.exit(1)

    if args.loop:
        while True:
            print(f"\n[{datetime.now(timezone.utc).isoformat()}] Starting pass...")
            pubs = load_pubs()
            pubs = run_once(pubs, args.limit)
            save_pubs(pubs)
            print(f"Sleeping {LOOP_SLEEP_HOURS}h until next pass...")
            time.sleep(LOOP_SLEEP_HOURS * 3600)
    else:
        pubs = load_pubs()
        pubs = run_once(pubs, args.limit)
        save_pubs(pubs)


if __name__ == "__main__":
    main()
