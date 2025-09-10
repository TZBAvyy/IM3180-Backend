from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from fastapi import APIRouter, HTTPException
import requests
import os
from dotenv import load_dotenv

from app.models.trip_opti_models import TripOptiIn, TripOptiOut
from app.models.error_models import HTTPError


# --- Trip optimizer route ---

router = APIRouter(prefix="/trip_optimizer", tags=["trip_optimizer"])

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY","change-this") 

@router.get("/")
def test():
    return {"message": "Trip Optimizer Endpoint", "success": True}

@router.post("/test_google")
def test_google_api(request: dict):
    coords = request.get("origins")
    result = get_time_matrix(coords)
    return result

@router.post("/", responses={
    200: {"model": TripOptiOut, "description": "Successful Response"},
    400: {"model": HTTPError, "description": "Missing required parameters"},
    404: {"model": HTTPError, "description": "No solution found"}
})
def get_optimized_route(request: TripOptiIn):

    # --- Required parameters ---
    addresses = request.addresses  
    hotel_address = request.hotel_address  
    service_times = request.service_times

    # --- Optional paramters with default values ---
    start_hour = request.start_hour
    end_hour = request.end_hour
    lunch_start_hour = request.lunch_start_hour
    lunch_end_hour = request.lunch_end_hour
    dinner_start_hour = request.dinner_start_hour
    dinner_end_hour = request.dinner_end_hour

    # --- Input validation ---
    if addresses is None or hotel_address is None or service_times is None:
        raise HTTPException(status_code=400, detail="Missing required fields")
    if len(addresses) != len(service_times):
        raise HTTPException(status_code=422, detail="Length of addresses and service_times must match")
    if len(addresses) < 1:
        raise HTTPException(status_code=422, detail="At least one address is required")

    # Combine hotel and addresses for querying
    all_coords = [hotel_address] + addresses

    try:
        time_matrix = get_time_matrix(all_coords)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Distance Matrix API error: {e}")

    try:
        eateries = identify_eateries(all_coords, api_key=GOOGLE_API_KEY)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Places API error: {e}")

    if len(eateries) < 2:
        eateries = [i for i in range(1, min(3, len(all_coords)))]  # At least 2 eateries (excluding hotel)

    data = {}
    data['eatery_nodes'] = eateries
    data['time_matrix'] = time_matrix
    data['postal_codes'] = ["00000" + str(i) for i in range(len(addresses) + 1)]
    data['addresses'] = all_coords
    data['service_times'] = [0] + service_times
    data['num_vehicles'] = 1
    data['depot'] = 0
    data['start_hour'] = start_hour
    data['end_hour'] = end_hour
    data['lunch_start_hour'] = lunch_start_hour
    data['lunch_end_hour'] = lunch_end_hour
    data['dinner_start_hour'] = dinner_start_hour
    data['dinner_end_hour'] = dinner_end_hour

    result = trip_optimizer(data)
    return {"route": result}

# --- Trip optimizer algorithm ---
def trip_optimizer(data: dict, lunch_index: int = 0, dinner_index: int = 1, flip: bool = False):

    # --- Input validation ---
    if len(data['eatery_nodes']) < 2:
        print("At least two eatery nodes are required.")

    # --- Problem data ---
    data['lunch_node'] = data['eatery_nodes'][lunch_index]
    data['dinner_node'] = data['eatery_nodes'][dinner_index]

    # --- Routing model ---
    manager = pywrapcp.RoutingIndexManager(len(data['time_matrix']),
                                           data['num_vehicles'],
                                           data['depot'])
    routing = pywrapcp.RoutingModel(manager)

    # --- Transit callback (travel + service times) ---
    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        travel = data['time_matrix'][from_node][to_node]
        return travel + data['service_times'][to_node]

    transit_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # --- Add Time dimension (accumulated time along route) ---
    horizon = (data['end_hour'] - data['start_hour']) * 60
    routing.AddDimension(
        transit_callback_index,
        slack_max=0,   # no waiting
        capacity=horizon,
        fix_start_cumul_to_zero=True,
        name='Time')
    time_dimension = routing.GetDimensionOrDie('Time')

    # --- Lunch spot constraint ---
    lunch_index_node = manager.NodeToIndex(data['lunch_node'])
    time_dimension.CumulVar(lunch_index_node).SetRange(
        int((data['lunch_start_hour'] - data['start_hour']) * 60),
        int((data['lunch_end_hour'] - data['start_hour']) * 60))

     # --- Dinner spot constraint ---
    dinner_index_node = manager.NodeToIndex(data['dinner_node'])
    time_dimension.CumulVar(dinner_index_node).SetRange(
        int((data['dinner_start_hour'] - data['start_hour']) * 60),
        int((data['dinner_end_hour'] - data['start_hour']) * 60))

    # --- Solve ---
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)

    solution = routing.SolveWithParameters(search_parameters)

    # --- Print solution ---
    if solution:
        route = _format_solution(routing, manager, time_dimension, solution, data)
        return route
    else:
        if not flip:
            return trip_optimizer(data=data, lunch_index=dinner_index, dinner_index=lunch_index, flip=True)
        else:
            lunch_index, dinner_index = dinner_index, lunch_index

        if dinner_index + 1 < len(data['eatery_nodes']):
            return trip_optimizer(data=data, lunch_index=lunch_index, dinner_index=dinner_index + 1, flip=False)

        elif lunch_index + 1 < len(data['eatery_nodes']) - 1:
            return trip_optimizer(data=data, lunch_index=lunch_index + 1, dinner_index=lunch_index + 2, flip=False)
        else:
            print("No solution found!")
            raise HTTPException(status_code=404, detail="No solution found")


def _format_solution(routing, manager, time_dimension, solution, data: dict):
    index = routing.Start(0)
    route = []
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        time_val = solution.Value(time_dimension.CumulVar(index))
        route_item = {}
        route_item["address"] = data['addresses'][node]
        route_item["postal_code"] = data['postal_codes'][node]
        route_item["arrival_time"] = f"{data['start_hour'] + time_val // 60:02d}:{time_val % 60:02d}"

        if node == data['depot']:
            route_item["type"] = "Start"
        elif node == data['lunch_node']:
            route_item["type"] = "Lunch"
        elif node == data['dinner_node']:
            route_item["type"] = "Dinner"
        else:
            route_item["type"] = "Attraction"

        route.append(route_item)
        index = solution.Value(routing.NextVar(index))

    return_time = solution.Value(time_dimension.CumulVar(index))
    final = {
        "address": data['addresses'][data['depot']],
        "postal_code": "000000",  # Placeholder for postal code
        "arrival_time": f"{data['start_hour'] + return_time // 60:02d}:{return_time % 60:02d}",
        "type": "End"
    }
    route.append(final)

    return route

def get_time_matrix(coords: list[dict[str, float]]) -> list[list]:
    """
    Given list of coordinate strings [{latitude:xx.xx, longitude:xx.xx}], 
    returns 2D time matrix of durations in minutes.
    """
    N = len(coords)
    origins = coords
    destinations = origins
    url = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': GOOGLE_API_KEY,
        'X-Goog-FieldMask': 'originIndex,destinationIndex,duration,distanceMeters,status,condition'
    }
    params = {
        "origins": origins,
        "destinations": destinations,
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE"
    }
    response = requests.post(url=url,headers=headers,json=params)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code,detail=response.text)
    data = response.json()

    time_matrix = [[0 for _ in range(N)] for _ in range(N)] # Create 2d NxN array
    
    for entry in data:
        time_matrix[entry['originIndex']][entry['destinationIndex']] = int(entry['duration'][:-1])

    return time_matrix


def identify_eateries(coords, api_key=GOOGLE_API_KEY):
    """
    Identify eateries (restaurant, cafe, food, etc.) among coords using Google Places Nearby Search API.
    Returns list of indexes corresponding to eatery coordinates.
    """
    eatery_types = {"restaurant", "cafe", "food", "bakery", "meal_takeaway", "meal_delivery"}
    eatery_indexes = []

    for idx, coord in enumerate(coords):
        lat, lng = coord.split(",")
        url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        params = {
            "location": f"{lat},{lng}",
            "radius": 100,  # meters
            "key": api_key,
            "type": "restaurant"  # general eatery type for narrowing search
        }
        response = requests.get(url, params=params)
        if response.status_code != 200:
            raise Exception(f"Places API error at index {idx}: {response.status_code} {response.text}")
        data = response.json()
        if data.get("status") == "OK":
            for place in data.get("results", []):
                place_types = set(place.get("types", []))
                if eatery_types.intersection(place_types):
                    eatery_indexes.append(idx)
                    break  # no need to check more places here
    return eatery_indexes