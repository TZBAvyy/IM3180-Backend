import numpy as np
from sklearn.cluster import DBSCAN
from math import ceil
from fastapi import APIRouter, HTTPException
import os
import requests
import concurrent.futures

from app.models.cluster_models import (
    ClusterIn,
    ClusterOut,
    LocationOut,
    DayOut,
    UserPreferenceSolutionOut,
    OptimalSolutionOut,
)
from app.models.error_models import HTTPError

# --- Cluster Route ---

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

router = APIRouter(prefix="/cluster", tags=["cluster"])


@router.get("/")
def test():
    return {"message": "Cluster Endpoint", "success": True}


@router.post(
    "/",
    response_model=ClusterOut,
    responses={
        400: {
            "model": HTTPError,
            "description": "Missing required parameters",
        }
    },
)
def get_clusters_given_all_locations(data: ClusterIn) -> ClusterOut:
    # --- Input validation ---
    if not data.locations_sorted:
        raise HTTPException(status_code=400, detail="Missing required fields")

    # --- Preprocess locations: allow place_id or lat/lng ---
    processed_locations: list[dict] = []
    for loc in data.locations_sorted:
        if loc.place_id and (loc.latitude is None or loc.longitude is None):
            latlng = resolve_latlng_from_placeid(loc.place_id)
            if not latlng:
                raise HTTPException(status_code=400, detail=f"Could not resolve place_id {loc.place_id}")
            lat, lng = latlng
        elif loc.latitude is not None and loc.longitude is not None:
            lat, lng = loc.latitude, loc.longitude
        else:
            raise HTTPException(status_code=400, detail="Each location must have either place_id or lat/lng")

        processed_locations.append(
            {
                "latitude": float(lat),
                "longitude": float(lng),
                "priority": int(loc.priority),
                "stay_hours": float(loc.stay_hours),
                "place_id": loc.place_id,
            }
        )

    requested_days = max(1, data.requested_days or 1)
    max_hours_per_day = max(1, data.max_hours_per_day or 1)

    # --- Run clustering ---
    coords = np.array([(loc["latitude"], loc["longitude"]) for loc in processed_locations])
    db = DBSCAN(eps=0.0225, min_samples=1).fit(coords)
    labels = db.labels_

    for loc, label in zip(processed_locations, labels):
        loc["cluster_id"] = int(label)

    # --- Group into clusters ---
    clusters_dict = {}
    for loc in processed_locations:
        clusters_dict.setdefault(loc["cluster_id"], []).append(loc)

    # --- User Preference Solution (follow input order within requested days) ---
    day_slots: list[list[dict]] = [[] for _ in range(requested_days)]
    day_hours = [0.0 for _ in range(requested_days)]
    solution1_rejected: list[dict] = []
    current_day_idx = 0

    for loc in processed_locations:
        if current_day_idx >= requested_days:
            solution1_rejected.append(loc)
            continue

        if day_hours[current_day_idx] + loc["stay_hours"] <= max_hours_per_day + 1e-6:
            day_slots[current_day_idx].append(loc)
            day_hours[current_day_idx] += loc["stay_hours"]
            continue

        # advance to the next day until we find space or exhaust requested days
        while current_day_idx < requested_days and day_hours[current_day_idx] + loc["stay_hours"] > max_hours_per_day + 1e-6:
            current_day_idx += 1
        if current_day_idx >= requested_days:
            solution1_rejected.append(loc)
        else:
            day_slots[current_day_idx].append(loc)
            day_hours[current_day_idx] += loc["stay_hours"]

    # --- Optimal Solution (split by clusters across days/min days) ---
    total_stay_hours = sum(loc["stay_hours"] for loc in processed_locations)
    min_days_needed = ceil(total_stay_hours / max_hours_per_day)
    num_days = max(1, min_days_needed)

    day_buckets: list[list[dict]] = [[] for _ in range(num_days)]
    day_bucket_hours = [0.0 for _ in range(num_days)]
    overflow_locations: list[dict] = []

    cluster_order = sorted(
        clusters_dict.items(),
        key=lambda item: min(loc["priority"] for loc in item[1]),
    )

    for _, cluster_locs in cluster_order:
        cluster_sorted = sorted(cluster_locs, key=lambda loc: loc["priority"])
        cluster_hours = sum(loc["stay_hours"] for loc in cluster_sorted)
        remaining = [max_hours_per_day - used for used in day_bucket_hours]
        best_day = max(range(num_days), key=lambda idx: remaining[idx])

        if cluster_hours <= remaining[best_day]:
            day_buckets[best_day].extend(cluster_sorted)
            day_bucket_hours[best_day] += cluster_hours
            continue

        for loc in cluster_sorted:
            day_indices = sorted(
                range(num_days),
                key=lambda idx: max_hours_per_day - day_bucket_hours[idx],
                reverse=True,
            )
            placed = False
            for day_idx in day_indices:
                if day_bucket_hours[day_idx] + loc["stay_hours"] <= max_hours_per_day + 1e-6:
                    day_buckets[day_idx].append(loc)
                    day_bucket_hours[day_idx] += loc["stay_hours"]
                    placed = True
                    break
            if not placed:
                overflow_locations.append(loc)

    # --- Build response using Pydantic models ---
    def make_location_out(loc: dict) -> LocationOut:
        return LocationOut(
            latitude=float(loc["latitude"]),
            longitude=float(loc["longitude"]),
            priority=int(loc["priority"]),
            stay_hours=float(loc["stay_hours"]),
            cluster_id=int(loc["cluster_id"]),
            place_id=loc.get("place_id"),
        )

    user_pref_days = [
        DayOut(
            day=day_idx + 1,
            locations=[make_location_out(loc) for loc in day_locs],
        )
        for day_idx, day_locs in enumerate(day_slots)
    ]

    optimal_days = [
        DayOut(
            day=day_idx + 1,
            locations=[make_location_out(loc) for loc in day_locs],
        )
        for day_idx, day_locs in enumerate(day_buckets)
        if day_locs
    ]

    overflow_signatures = set()
    for loc in overflow_locations:
        key = (
            round(loc["latitude"], 6),
            round(loc["longitude"], 6),
            loc.get("place_id"),
            loc["priority"],
        )
        if key not in overflow_signatures:
            solution1_rejected.append(loc)
            overflow_signatures.add(key)

    rejected_unique: list[dict] = []
    rejected_seen = set()
    for loc in solution1_rejected:
        key = (
            round(loc["latitude"], 6),
            round(loc["longitude"], 6),
            loc.get("place_id"),
            loc["priority"],
        )
        if key in rejected_seen:
            continue
        rejected_seen.add(key)
        rejected_unique.append(loc)

    response = ClusterOut(
        user_preference_solution=UserPreferenceSolutionOut(
            days=user_pref_days,
            rejected=[make_location_out(loc) for loc in rejected_unique],
        ),
        optimal_solution=OptimalSolutionOut(
            days=optimal_days,
        ),
    )

    # --- Enrich with place_ids (concurrent) ---
    enriched = add_place_ids_to_clusters(response.dict(), keyword_hint=data.keyword_hint)
    return ClusterOut(**enriched)


# ---------------- Helper Functions ----------------

def _enrich_loc_with_place_id(loc: dict, keyword_hint: str | None = None) -> dict:
    """Enrich location dict with place_id and corrected lat/lng."""
    lat = float(loc["latitude"])
    lng = float(loc["longitude"])
    if loc.get("place_id"):
        loc["latitude"] = lat
        loc["longitude"] = lng
        return loc
    result = resolve_place_id(lat, lng, keyword=keyword_hint)

    if result:
        pid, new_lat, new_lng = result
        loc["place_id"] = pid
        loc["latitude"] = float(new_lat)
        loc["longitude"] = float(new_lng)
    else:
        loc["place_id"] = None
        loc["latitude"] = float(lat)
        loc["longitude"] = float(lng)

    return loc



def add_place_ids_to_clusters(clusters_response: dict, keyword_hint: str | None = None, max_workers: int = 12) -> dict:
    """Walk the response shape and add place_id to every location. Done concurrently."""
    targets: list[dict] = []

    user_pref = clusters_response.get("user_preference_solution", {})
    for day in user_pref.get("days", []):
        for loc in day.get("locations", []):
            targets.append(loc)
    for loc in user_pref.get("rejected", []):
        targets.append(loc)
    optimal = clusters_response.get("optimal_solution", {})
    for day in optimal.get("days", []):
        for loc in day.get("locations", []):
            targets.append(loc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_enrich_loc_with_place_id, loc, keyword_hint) for loc in targets]
        for f in concurrent.futures.as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print(f"[PlaceID Enrich Error] {e}")

    return clusters_response


# ---------------- Google API Helpers ----------------

def _google_places_nearby_place_id(lat: float, lng: float, keyword: str | None = None, radius: int = 120, timeout: float = 5.0) -> tuple[str, float, float] | None:
    if not GOOGLE_API_KEY:
        return None
    params = {
        "location": f"{lat},{lng}",
        "radius": radius,
        "type": "point_of_interest",
        "key": GOOGLE_API_KEY,
    }
    if keyword:
        params["keyword"] = keyword

    try:
        resp = requests.get("https://maps.googleapis.com/maps/api/place/nearbysearch/json", params=params, timeout=timeout)
        data = resp.json()
        if data.get("status") == "OK" and data.get("results"):
            top = data["results"][0]
            pid = top.get("place_id")
            loc = top.get("geometry", {}).get("location", {})
            return pid, loc.get("lat", lat), loc.get("lng", lng)
    except Exception as e:
        print(f"[Google Places Nearby Error] {e}")
    return None


def _google_reverse_geocode_place_id(lat: float, lng: float, timeout: float = 5.0) -> tuple[str, float, float] | None:
    if not GOOGLE_API_KEY:
        return None
    try:
        resp = requests.get("https://maps.googleapis.com/maps/api/geocode/json", params={"latlng": f"{lat},{lng}", "key": GOOGLE_API_KEY}, timeout=timeout)
        data = resp.json()
        if data.get("status") == "OK" and data.get("results"):
            top = data["results"][0]
            pid = top.get("place_id")
            loc = top.get("geometry", {}).get("location", {})
            return pid, loc.get("lat", lat), loc.get("lng", lng)
    except Exception as e:
        print(f"[Google Reverse Geocode Error] {e}")
    return None


def resolve_latlng_from_placeid(place_id: str, timeout: float = 5.0) -> tuple[float, float] | None:
    if not GOOGLE_API_KEY:
        return None
    try:
        resp = requests.get("https://maps.googleapis.com/maps/api/place/details/json", params={"place_id": place_id, "fields": "geometry", "key": GOOGLE_API_KEY}, timeout=timeout)
        data = resp.json()
        if data.get("status") == "OK" and "result" in data:
            loc = data["result"]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception as e:
        print(f"[Resolve PlaceID Error] {e}")
    return None


def resolve_place_id(lat: float, lng: float, keyword: str | None = None) -> tuple[str, float, float] | None:
    result = _google_places_nearby_place_id(lat, lng, keyword=keyword)
    if result:
        return result
    return _google_reverse_geocode_place_id(lat, lng)
