#!/usr/bin/env python3
"""
Phase 5: FastAPI server for Beer Forecast.

Endpoints:
    GET /pubs                              — list all pubs
    GET /pubs/nearby?lat=&lng=&radius_km= — pubs within radius (haversine)
    GET /pubs/{id}                         — single pub with latest promotions

Usage:
    uvicorn api.main:app --reload
"""

import json
import math
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

DATA_PATH = Path(__file__).parent.parent / "data" / "pubs.json"

app = FastAPI(title="Beer Forecast API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

SCREENSHOTS_DIR = Path(__file__).parent.parent / "data" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOTS_DIR)), name="screenshots")


def load_pubs() -> list[dict]:
    if not DATA_PATH.exists():
        raise HTTPException(status_code=503, detail="pubs.json not found. Run fetch_pubs.py first.")
    return json.loads(DATA_PATH.read_text())


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def pub_summary(pub: dict) -> dict[str, Any]:
    return {
        "id": pub["id"],
        "osm_id": pub["osm_id"],
        "name": pub["name"],
        "lat": pub["lat"],
        "lng": pub["lng"],
        "address": pub.get("address"),
        "website": pub.get("website"),
        "created_at": pub.get("created_at"),
        "venue_emoji": pub.get("venue_emoji", "🍻"),
        "promotions": pub.get("promotions") or [],
    }


def pub_detail(pub: dict) -> dict[str, Any]:
    return {
        **pub_summary(pub),
        "promotions": pub.get("promotions"),
        "promotions_last_updated": pub.get("promotions_last_updated"),
        "promotions_query": pub.get("promotions_query"),
    }


@app.get("/pubs")
def list_pubs() -> JSONResponse:
    pubs = load_pubs()
    return JSONResponse(sorted([pub_summary(p) for p in pubs], key=lambda p: p["name"]))


@app.get("/pubs/nearby")
def pubs_nearby(
    lat: float = Query(..., description="Latitude"),
    lng: float = Query(..., description="Longitude"),
    radius_km: float = Query(1.0, description="Search radius in kilometres"),
) -> JSONResponse:
    pubs = load_pubs()

    nearby = []
    for pub in pubs:
        dist = haversine_km(lat, lng, pub["lat"], pub["lng"])
        if dist <= radius_km:
            entry = pub_summary(pub)
            entry["distance_km"] = round(dist, 3)
            nearby.append(entry)

    nearby.sort(key=lambda x: x["distance_km"])
    return JSONResponse(nearby)


@app.get("/pubs/{pub_id}")
def get_pub(pub_id: int) -> JSONResponse:
    pubs = load_pubs()
    for pub in pubs:
        if pub["id"] == pub_id:
            return JSONResponse(pub_detail(pub))
    raise HTTPException(status_code=404, detail="Pub not found")
