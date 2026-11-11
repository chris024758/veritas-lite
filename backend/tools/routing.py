"""check_route: Nominatim geocoding + OSRM routing. Both free and keyless."""
import math
import os
import threading
import time

import requests

import db

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{a};{b}"
HEADERS = {"User-Agent": os.getenv("NOMINATIM_USER_AGENT", "VERITAS-Lite-demo/0.1")}
TIMEOUT_SECONDS = 15
NOMINATIM_INTERVAL_SECONDS = 1.1

# OSRM's public server only offers free-flow driving times. This is the stated urban
# two-wheeler assumption applied to OSRM's real distance to get actual_minutes.
AVG_SPEED_KMH = float(os.getenv("ROUTE_AVG_SPEED_KMH", "20"))
# Longer trips are mostly highway, where the urban speed is wrong: use OSRM's time as is.
URBAN_MAX_KM = 30.0

# A place given without a city must resolve to a settlement or region. Otherwise a vague
# reference like "the shop" matches some literal shop on another continent.
AREA_CLASSES = {"place", "boundary"}

# A claim is out of tolerance when actual exceeds claimed by more than this.
MIN_TOLERANCE_MINUTES = 3.0
TOLERANCE_FRACTION = 0.2

_nominatim_lock = threading.Lock()
_last_nominatim_call = 0.0


def _nominatim(query: str) -> dict | None:
    global _last_nominatim_call
    with _nominatim_lock:
        wait = NOMINATIM_INTERVAL_SECONDS - (time.monotonic() - _last_nominatim_call)
        if wait > 0:
            time.sleep(wait)
        _last_nominatim_call = time.monotonic()
        response = requests.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1},
            headers=HEADERS,
            timeout=TIMEOUT_SECONDS,
        )
    response.raise_for_status()
    results = response.json()
    if not results:
        return None
    top = results[0]
    if "," not in query and top.get("class") not in AREA_CLASSES:
        return None
    return {"lat": float(top["lat"]), "lon": float(top["lon"]), "display_name": top["display_name"]}


def geocode(place: str) -> dict | None:
    """Tries the full place, then drops leading comma segments ("Shop, Road, City" ->
    "Road, City"), which a named business OSM doesn't know needs. Never goes below two
    segments, so a failed lookup can't silently become a whole-city centre point."""
    segments = [s.strip() for s in place.split(",") if s.strip()]
    for start in range(max(1, len(segments) - 1)):
        query = ", ".join(segments[start:])
        cached = db.cache_get(f"geocode:{query.lower()}")
        if cached:
            return {**cached, "matched_query": query}
        result = _nominatim(query)
        if result:
            db.cache_set(f"geocode:{query.lower()}", result)
            return {**result, "matched_query": query}
    return None


def _haversine_km(a: dict, b: dict) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _route(a: dict, b: dict) -> dict:
    """Distance and raw duration: cache, then live OSRM, then straight-line fallback."""
    key = f"route:{a['lon']},{a['lat']};{b['lon']},{b['lat']}"
    cached = db.cache_get(key)
    if cached:
        return {**cached, "source": "osrm_cached"}
    try:
        response = requests.get(
            OSRM_URL.format(a=f"{a['lon']},{a['lat']}", b=f"{b['lon']},{b['lat']}"),
            params={"overview": "false"},
            headers=HEADERS,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        route = response.json()["routes"][0]
        result = {"distance_km": route["distance"] / 1000, "osrm_minutes": route["duration"] / 60}
        db.cache_set(key, result)
        return {**result, "source": "osrm"}
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return {"distance_km": _haversine_km(a, b), "osrm_minutes": None, "source": "straight_line_fallback"}


def check_route(origin: str, destination: str, claimed_minutes: float | None = None) -> dict:
    try:
        start = geocode(origin)
        end = geocode(destination)
    except requests.RequestException as exc:
        return {"error": f"geocoding service failed: {exc}"}
    missing = [p for p, g in ((origin, start), (destination, end)) if g is None]
    if missing:
        return {"error": f"could not geocode: {missing}. Use a more specific place name."}

    route = _route(start, end)
    urban = route["distance_km"] <= URBAN_MAX_KM or route["osrm_minutes"] is None
    actual = route["distance_km"] / AVG_SPEED_KMH * 60 if urban else route["osrm_minutes"]
    result = {
        "origin": origin,
        "origin_matched": start["matched_query"],
        "destination": destination,
        "destination_matched": end["matched_query"],
        "distance_km": round(route["distance_km"], 1),
        "osrm_minutes": round(route["osrm_minutes"], 1) if route["osrm_minutes"] is not None else None,
        "assumed_speed_kmh": AVG_SPEED_KMH if urban else None,
        "actual_minutes": round(actual, 1),
        "source": route["source"],
    }
    if claimed_minutes is not None:
        gap = actual - claimed_minutes
        result["claimed_minutes"] = claimed_minutes
        result["gap_minutes"] = round(gap, 1)
        result["exceeds_tolerance"] = gap > max(MIN_TOLERANCE_MINUTES, TOLERANCE_FRACTION * actual)
    return result
