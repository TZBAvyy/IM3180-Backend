import numpy as np
from sklearn.cluster import DBSCAN
from math import ceil
from fastapi import APIRouter, HTTPException
import os
import requests
import concurrent.futures

from app.models.cluster_models import ClusterIn, ClusterOut, LocationOut, DayOut, Solution1Out
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
    processed_locations = []
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

        processed_locations.append((lat, lng, loc.priority, loc.stay_hours))

    requested_days = data.requested_days
    max_hours_per_day = data.max_hours_per_day

    # --- Run clustering ---
    coords = np.array([(lat, lon) for lat, lon, _, _ in processed_locations])
    db = DBSCAN(eps=0.0225, min_samples=1).fit(coords)
    labels = db.labels_

    locations_data = [
        (lat, lon, priority, stay, label)
        for (lat, lon, priority, stay), label in zip(processed_locations, labels)
    ]

    # --- Group into clusters ---
    clusters_dict = {}
    for loc in locations_data:
        clusters_dict.setdefault(loc[4], []).append(loc)

    # --- Solution 1 (greedy by priority, limited hours) ---
    sorted_by_priority = sorted(locations_data, key=lambda x: x[2])
    current_day_hours = 0
    solution1_day1, solution1_rejected = [], []
    for loc in sorted_by_priority:
        if current_day_hours + loc[3] <= max_hours_per_day:
            solution1_day1.append(loc)
            current_day_hours += loc[3]
        else:
            solution1_rejected.append(loc)

    # --- Solution 2 (split by clusters across days) ---
    total_stay_hours = sum([loc[3] for loc in locations_data])
    min_days_needed = ceil(total_stay_hours / max_hours_per_day)
    num_days = max(requested_days, min_days_needed)

    cluster_ids = sorted(clusters_dict.keys())
    clusters_per_day = ceil(len(cluster_ids) / num_days)
    solution2_days = []
    for day in range(num_days):
        start_idx = day * clusters_per_day
        end_idx = start_idx + clusters_per_day
        day_cluster_ids = cluster_ids[start_idx:end_idx]
        day_locs = []
        for cid in day_cluster_ids:
            day_locs.extend(clusters_dict[cid])
        solution2_days.append(day_locs)

    # --- Build response using Pydantic models ---
    response = ClusterOut(
        solution1=Solution1Out(
            day1=[LocationOut(latitude=loc[0], longitude=loc[1], priority=loc[2], stay_hours=loc[3], cluster_id=loc[4]) for loc in solution1_day1],
            rejected=[LocationOut(latitude=loc[0], longitude=loc[1], priority=loc[2], stay_hours=loc[3], cluster_id=loc[4]) for loc in solution1_rejected],
        ),
        solution2=[
            DayOut(
                day=day_idx + 1,
                locations=[LocationOut(latitude=loc[0], longitude=loc[1], priority=loc[2], stay_hours=loc[3], cluster_id=loc[4]) for loc in day_locs],
            )
            for day_idx, day_locs in enumerate(solution2_days)
        ],
    )

    # --- Enrich with place_ids (concurrent) ---
    enriched = add_place_ids_to_clusters(response.dict(), keyword_hint=data.keyword_hint)
    return ClusterOut(**enriched)


# ---------------- Helper Functions ----------------

def _enrich_loc_with_place_id(loc: dict, keyword_hint: str | None = None) -> dict:
    """Enrich location dict with place_id and corrected lat/lng."""
    lat = float(loc["latitude"])
    lng = float(loc["longitude"])
    result = resolve_place_id(lat, lng, keyword=keyword_hint)

    if result:
        pid, new_lat, new_lng = result
        loc["place_id"] = pid
        loc["latitude"] = float(new_lat)
        loc["longitude"] = float(new_lng)
    else:
        # Even if API fails, keep original lat/lng
        loc["place_id"] = None
        loc["latitude"] = float(lat)
        loc["longitude"] = float(lng)

    return loc



def add_place_ids_to_clusters(clusters_response: dict, keyword_hint: str | None = None, max_workers: int = 12) -> dict:
    """Walk the response shape and add place_id to every location. Done concurrently."""
    targets: list[dict] = []

    for loc in clusters_response.get("solution1", {}).get("day1", []):
        targets.append(loc)
    for loc in clusters_response.get("solution1", {}).get("rejected", []):
        targets.append(loc)
    for day in clusters_response.get("solution2", []):
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
