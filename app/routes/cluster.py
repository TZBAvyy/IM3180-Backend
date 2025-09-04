import numpy as np
from sklearn.cluster import DBSCAN
import folium
import itertools
from math import ceil
from fastapi import APIRouter

# --- Cluster Route ---

router = APIRouter(prefix="/cluster", tags=["cluster"])

@router.get("/")
def test():
    return {"message": "Cluster Endpoint","success": True}

@router.post('/')
def get_clusters(data: dict):
    locations_sorted = data.get('locations_sorted', [])
    requested_days = data.get('requested_days', 1)
    max_hours_per_day = data.get('max_hours_per_day', 10)

    if not locations_sorted:
        return {"error": "locations_sorted must be provided"} # TODO: see how to return 400

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

    return clusters_response

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