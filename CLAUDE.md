# Beer Forecast

A backend service that maps London pub promotions and discounts. It fetches pubs from OpenStreetMap, runs a research agent to discover their current deals, stores results in a JSON file, and exposes a FastAPI server for a future mobile frontend.

## Architecture

```
qwen-testing (own repo)          beer-forecast (this repo)        beer-forecast-app (future)
─────────────────────────        ─────────────────────────        ──────────────────────────
research_agent.py         ──►    Python backend + FastAPI  ──►    Expo + React Native
(called as subprocess)           pubs.json data store             Map with pub pins
                                 Scheduler (weekly runs)          Promotion info cards
```

## File Structure

```
beer-forecast/
├── CLAUDE.md
├── README.md
├── requirements.txt          # fastapi, uvicorn, requests
├── data/
│   └── pubs.json             # pub + promotion data (gitignored)
├── scripts/
│   ├── fetch_pubs.py         # OSM → pubs.json fetcher
│   ├── test_agent.py         # 5-pub test harness
│   └── scheduler.py          # Periodic promotion updater
└── api/
    └── main.py               # FastAPI server
```

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Running

```bash
# Fetch pubs from OpenStreetMap
.venv/bin/python3 scripts/fetch_pubs.py

# Test agent on 5 hand-picked pubs
.venv/bin/python3 scripts/test_agent.py

# Run scheduler (processes all pubs, skips recently updated)
.venv/bin/python3 scripts/scheduler.py

# Start API server
.venv/bin/uvicorn api.main:app --reload
```

## API Endpoints

- `GET /pubs` — list all pubs
- `GET /pubs/{id}` — single pub with latest promotions
- `GET /pubs/nearby?lat=&lng=&radius_km=` — pubs within radius

## Database Schema

Each pub object in `pubs.json`:
- id, osm_id, name, lat, lng, address, website, created_at
- promotions (list of `{description, discount, days, time, source_url}`), promotions_last_updated, promotions_query

## Research Agent

Promotions are discovered by calling `research_agent.py` from the `qwen-testing` repo as a subprocess. It uses DuckDuckGo + headless Chromium + a local Qwen LLM (via Ollama) to find and extract deal information.

The agent must be running (Ollama serving qwen3:1.7b) for the scheduler and test harness to work.

## Branch Structure

- `main` — stable releases
- `dev` — active development (default working branch)
