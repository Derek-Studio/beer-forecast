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
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

DB_PATH = Path(__file__).parent.parent / "data" / "pubs.db"

app = FastAPI(title="Beer Forecast API", version="0.1.0")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def pub_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "osm_id": row["osm_id"],
        "name": row["name"],
        "lat": row["lat"],
        "lng": row["lng"],
        "address": row["address"],
        "website": row["website"],
        "created_at": row["created_at"],
    }


@app.get("/pubs")
def list_pubs() -> JSONResponse:
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Database not found. Run fetch_pubs.py first.")
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, osm_id, name, lat, lng, address, website, created_at FROM pubs ORDER BY name"
    ).fetchall()
    conn.close()
    return JSONResponse([pub_row_to_dict(r) for r in rows])


@app.get("/pubs/nearby")
def pubs_nearby(
    lat: float = Query(..., description="Latitude"),
    lng: float = Query(..., description="Longitude"),
    radius_km: float = Query(1.0, description="Search radius in kilometres"),
) -> JSONResponse:
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Database not found. Run fetch_pubs.py first.")

    # Rough bounding box filter first, then precise haversine
    lat_delta = radius_km / 111.0
    lng_delta = radius_km / (111.0 * math.cos(math.radians(lat)))

    conn = get_conn()
    rows = conn.execute(
        """
        SELECT id, osm_id, name, lat, lng, address, website, created_at
        FROM pubs
        WHERE lat BETWEEN ? AND ?
          AND lng BETWEEN ? AND ?
        """,
        (lat - lat_delta, lat + lat_delta, lng - lng_delta, lng + lng_delta),
    ).fetchall()
    conn.close()

    nearby = []
    for row in rows:
        dist = haversine_km(lat, lng, row["lat"], row["lng"])
        if dist <= radius_km:
            d = pub_row_to_dict(row)
            d["distance_km"] = round(dist, 3)
            nearby.append(d)

    nearby.sort(key=lambda x: x["distance_km"])
    return JSONResponse(nearby)


@app.get("/pubs/{pub_id}")
def get_pub(pub_id: int) -> JSONResponse:
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Database not found. Run fetch_pubs.py first.")
    conn = get_conn()
    row = conn.execute(
        "SELECT id, osm_id, name, lat, lng, address, website, created_at FROM pubs WHERE id = ?",
        (pub_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Pub not found")

    promo = conn.execute(
        "SELECT data, last_updated, raw_query FROM promotions WHERE pub_id = ?",
        (pub_id,),
    ).fetchone()
    conn.close()

    result = pub_row_to_dict(row)
    if promo:
        try:
            result["promotions"] = json.loads(promo["data"]) if promo["data"] else None
        except (json.JSONDecodeError, TypeError):
            result["promotions"] = None
        result["promotions_last_updated"] = promo["last_updated"]
        result["promotions_query"] = promo["raw_query"]
    else:
        result["promotions"] = None
        result["promotions_last_updated"] = None
        result["promotions_query"] = None

    return JSONResponse(result)
