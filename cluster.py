import numpy as np
from sklearn.cluster import DBSCAN
import folium
import itertools
from math import ceil
from flask import Flask, request, jsonify
import json
import re
from google import genai

app = Flask(__name__)

# --- Initialize Gemini client ---
API_KEY = ""
client = genai.Client(api_key=API_KEY)

# --- Utility to convert numpy types to Python native ---
def convert_numpy_types(obj):
    if isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    elif isinstance(obj, np.generic):
        return obj.item()
    else:
        return obj

# --- Endpoint 1: Generate itinerary using LLM ---
def generate_itinerary(user_stay_days, max_hours_per_day):
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
        return {"error": "Failed to parse JSON from LLM output", "details": str(e)}

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

    return {"solution": "solution1", "days": solution_days}

@app.route("/plan_itinerary_llm", methods=["POST"])
def plan_itinerary():
    data = request.json
    user_stay_days = data.get("user_stay_days", 1)
    max_hours_per_day = data.get("max_hours_per_day", 8)
    result = generate_itinerary(user_stay_days, max_hours_per_day)
    return jsonify(result)


# --- Endpoint 2: Cluster provided locations and generate maps ---
@app.route('/get_clusters', methods=['POST'])
def get_clusters():
    data = request.get_json()
    locations_sorted = data.get('locations_sorted', [])
    requested_days = data.get('requested_days', 1)
    max_hours_per_day = data.get('max_hours_per_day', 10)

    if not locations_sorted:
        return jsonify({"error": "locations_sorted must be provided"}), 400

    coords = np.array([(lat, lon) for lat, lon, _, _ in locations_sorted[1:]])
    db = DBSCAN(eps=0.0225, min_samples=1).fit(coords)
    labels = db.labels_

    locations_data = []
    for i, loc in enumerate(locations_sorted[1:]):
        locations_data.append(tuple(loc) + (labels[i],))

    clusters_dict = {}
    for loc in locations_data:
        clusters_dict.setdefault(loc[4], []).append(loc)

    # Solution 1: fit into day1
    sorted_by_priority = sorted(locations_data, key=lambda x: x[2])
    current_day_hours = 0
    solution1_day1 = []
    solution1_rejected = []
    for loc in sorted_by_priority:
        if current_day_hours + loc[3] <= max_hours_per_day:
            solution1_day1.append(loc)
            current_day_hours += loc[3]
        else:
            solution1_rejected.append(loc)

    # Solution 2: split clusters across requested days
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

    # Prepare response
    clusters_response = {
        'solution1': {
            'day1': [{'latitude': loc[0], 'longitude': loc[1], 'priority': loc[2],
                      'stay_hours': loc[3], 'cluster_id': loc[4]} for loc in solution1_day1],
            'rejected': [{'latitude': loc[0], 'longitude': loc[1], 'priority': loc[2],
                          'stay_hours': loc[3], 'cluster_id': loc[4]} for loc in solution1_rejected]
        },
        'solution2': [{'day': day_idx+1,
                       'locations': [{'latitude': loc[0], 'longitude': loc[1], 'priority': loc[2],
                                      'stay_hours': loc[3], 'cluster_id': loc[4]} for loc in day_locs]}
                      for day_idx, day_locs in enumerate(solution2_days)]
    }

    # Convert numpy types
    clusters_response = convert_numpy_types(clusters_response)

    # Visualization (optional: generates map HTML files)
    colors = itertools.cycle(["red", "blue", "green", "purple", "orange", "darkred",
                              "lightblue", "lightgreen", "cadetblue", "pink"])
    for day_idx, day_locs in enumerate(solution2_days):
        m_day = folium.Map(location=(1.3521, 103.8198), zoom_start=12)
        for loc in day_locs:
            lat, lon, prio, stay, cluster_id = loc
            folium.CircleMarker(
                location=(lat, lon),
                radius=7,
                color=next(colors),
                fill=True,
                fill_opacity=0.7,
                popup=f"Priority {prio}, Stay {stay}h, Cluster {cluster_id}"
            ).add_to(m_day)
        html_file = f"day_{day_idx + 1}.html"
        m_day.save(html_file)
        # Optional: open automatically
        # import webbrowser
        # webbrowser.open(f'file:///{html_file}')

    return jsonify(clusters_response)


if __name__ == '__main__':
    app.run(debug=True, port=5000)
