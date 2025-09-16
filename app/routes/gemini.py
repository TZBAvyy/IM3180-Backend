from google import genai 
from fastapi import APIRouter, HTTPException
from sklearn.cluster import DBSCAN
import json
import re
import numpy as np
import os

from app.models.gemini_models import PlanItinIn, PlanItinOut
from app.models.error_models import HTTPError

# --- Load environment variables ---

API_KEY = os.getenv("GEMINI_API_KEY", "get-your-own-key")

# --- LLM Route  ---

router = APIRouter(prefix="/llm", tags=["llm"])

@router.get("/")
def test():
    return {"message": "Gemini LLM Endpoint","success": True}

@router.post("/", responses={
    200: {
        "model": PlanItinOut,
        "description": "Successful Response"
    },
    500: {
        "model": HTTPError,
        "description": "LLM Unexpected Output"
    },
    503: {
        "model": HTTPError,
        "description": "LLM Model Overloaded"
    }
})
def plan_itinerary(request: PlanItinIn):
    user_stay_days = request.user_stay_days
    max_hours_per_day = request.max_hours_per_day
    result = generate_itinerary(user_stay_days, max_hours_per_day)
    return result

# --- Core LLM + Itinerary Logic ---

def generate_itinerary(user_stay_days, max_hours_per_day):
    client = genai.Client(api_key=API_KEY)
    prompt = f"""
    Suggest tourist attractions in Singapore that a visitor can explore in {user_stay_days} days.
    Return strictly a JSON array where each entry includes:

    {{
      "name": "Gardens by the Bay",
      "latitude": 1.2827,
      "longitude": 103.865,
      "suggested_visit_hours": 2,
      "priority": 1
    }}

    Requirements:
    - Include enough attractions to fill {user_stay_days} days of sightseeing, assuming {max_hours_per_day} hours per day.
    - Latitude and longitude must be decimal numbers.
    - suggested_visit_hours must be a number (hours spent at the attraction).
    - Priority: 1 = must see, 5 = optional.
    - Return only valid JSON. Do not include extra text or comments.
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    llm_output = response.text

    # --- Robust JSON extraction ---
    try:
        start_idx = llm_output.index("[")
        end_idx = llm_output.rindex("]") + 1
        json_str = llm_output[start_idx:end_idx]
        try:
            llm_data = json.loads(json_str)
        except json.JSONDecodeError:
            json_str_fixed = re.sub(r",\s*\{[^\{\}]*$", "", json_str)
            llm_data = json.loads(json_str_fixed)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse JSON from LLM output. Error: {e}")

    # --- Convert to locations ---
    locations_sorted = [
        (d["latitude"], d["longitude"], d["suggested_visit_hours"], d["name"], d["priority"])
        for d in llm_data
    ]

    # --- Add hotel/start location ---
    hotel_lat, hotel_lon = 1.3000, 103.8300
    locations_sorted.insert(0, (hotel_lat, hotel_lon, 0, "Hotel/Start", 1))

    # --- DBSCAN clustering ---
    coords = np.array([(lat, lon) for lat, lon, _, _, _ in locations_sorted[1:]])
    db = DBSCAN(eps=0.0225, min_samples=1).fit(coords)
    labels = db.labels_

    locations_data = []
    for i, loc in enumerate(locations_sorted[1:]):
        locations_data.append({
            "latitude": loc[0],
            "longitude": loc[1],
            "suggested_visit_hours": loc[2],
            "name": loc[3],
            "priority": loc[4],
            "cluster": int(labels[i])
        })

    # --- Assign locations to days based on priority ---
    sorted_by_priority = sorted(locations_data, key=lambda x: x["priority"])
    solution_days_raw = [[] for _ in range(user_stay_days)]
    day_hours = [0 for _ in range(user_stay_days)]

    for loc in sorted_by_priority:
        for day_idx in range(user_stay_days):
            if day_hours[day_idx] + loc["suggested_visit_hours"] <= max_hours_per_day:
                solution_days_raw[day_idx].append(loc)
                day_hours[day_idx] += loc["suggested_visit_hours"]
                break

    # --- Group by cluster within each day ---
    solution_days = []
    for day_locs in solution_days_raw:
        clusters_dict = {}
        for loc in day_locs:
            clusters_dict.setdefault(loc["cluster"], []).append({
                "name": loc["name"],
                "latitude": loc["latitude"],
                "longitude": loc["longitude"],
                "priority": loc["priority"],
                "suggested_visit_hours": loc["suggested_visit_hours"]
            })

        day_clusters = []
        for cid, locs in clusters_dict.items():
            highest_priority = min([l["priority"] for l in locs])
            day_clusters.append({
                "cluster": cid,
                "highest_priority": highest_priority,
                "locations": sorted(locs, key=lambda x: x["priority"])
            })

        day_clusters_sorted = sorted(day_clusters, key=lambda x: x["highest_priority"])
        for c in day_clusters_sorted:
            c.pop("highest_priority")
        solution_days.append(day_clusters_sorted)

    return {"days": solution_days}

# --- Helper Functions ---

def convert_numpy_types(obj):
    if isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    elif isinstance(obj, np.generic):
        return obj.item()
    else:
        return obj