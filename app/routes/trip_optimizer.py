from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from fastapi import APIRouter, HTTPException
import requests
import os

from app.models.trip_opti_models import TripOptiIn, TripOptiOut
from app.models.error_models import HTTPError


# --- Trip optimizer route ---

router = APIRouter(prefix="/trip_optimizer", tags=["trip_optimizer"])

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY","change-this") 

@router.get("/")
def test():
    return {"message": "Trip Optimizer Endpoint", "success": True}

@router.post("/", responses={
    200: {"model": TripOptiOut, "description": "Successful Response"},
    400: {"model": HTTPError, "description": "Missing required parameters"},
    404: {"model": HTTPError, "description": "No solution found"},
    500: {"model": HTTPError, "description": "Google API error"}
})
def get_optimized_route(request: TripOptiIn):

    # --- Required parameters ---
    addresses = request.addresses  
    hotel_index = request.hotel_index  
    service_times = request.service_times

    # --- Optional paramters with default values ---
    start_hour = request.start_hour
    end_hour = request.end_hour
    lunch_start_hour = request.lunch_start_hour
    lunch_end_hour = request.lunch_end_hour
    dinner_start_hour = request.dinner_start_hour
    dinner_end_hour = request.dinner_end_hour
    time_taken_to_free_space = request.time_taken_to_free_space
    service_time_at_free_space = request.service_time_at_free_space

    # --- Google API call for Time Matrix ---
    try:
        time_matrix = get_time_matrix(addresses)
        hotel_address = addresses.pop(hotel_index)
        eateries = identify_eateries(addresses)
        addresses.insert(0, hotel_address)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google Maps Routes API error: {e}")

    # --- Input validation ---
    len_of_addresses = len(addresses)
    if addresses is None or hotel_index is None or service_times is None:
        raise HTTPException(status_code=400, detail="Missing required fields")
    if len_of_addresses != len(service_times):
        raise HTTPException(status_code=422, detail="Length of addresses and service_times must match")
    if len_of_addresses < 1:
        raise HTTPException(status_code=422, detail="At least one address is required")
    if service_times[hotel_index] != 0:
        raise HTTPException(status_code=422, detail="Service time at hotel must be zero")
    
    # --- Lunch Node Check ---
    # Only if trip does not start after lunch hours
    if lunch_end_hour > start_hour:
        lunch_index = 0
    else:
        lunch_index = -1

    # --- Dinner Node Check ---
    # Only if service time alone can reach dinner time AND trip doesnt end before dinner start
    MIN_TIME_TAKEN = sum(service_times)
    TIME_TILL_DINNER = (dinner_start_hour-start_hour)*60
    if ((MIN_TIME_TAKEN + 10*len_of_addresses >= TIME_TILL_DINNER) 
        & (end_hour > dinner_start_hour)):
        dinner_index = 0
    else:
        dinner_index = -1

    # --- Insert Free Spot for Food ---
    while len(eateries) < (2+lunch_index+dinner_index):
        eateries.append(len_of_addresses)
        addresses.append("Free")
        time_matrix_row_for_space = []
        for _row in range(len_of_addresses):
            time_matrix[_row].append(time_taken_to_free_space)
            time_matrix_row_for_space.append(time_taken_to_free_space)
        time_matrix.append(time_matrix_row_for_space+[0])
        service_times.append(service_time_at_free_space)
        len_of_addresses = len_of_addresses+1

    # --- Prepare data for trip optimizer ---
    data = {}
    data['eatery_nodes'] = eateries
    data['time_matrix'] = time_matrix
    data['placeIDs'] = addresses
    data['service_times'] = service_times
    data['num_vehicles'] = 1
    data['depot'] = hotel_index
    data['start_hour'] = start_hour
    data['end_hour'] = end_hour
    data['lunch_start_hour'] = lunch_start_hour
    data['lunch_end_hour'] = lunch_end_hour
    data['dinner_start_hour'] = dinner_start_hour
    data['dinner_end_hour'] = dinner_end_hour

    result = trip_optimizer(data=data, lunch_index=lunch_index, dinner_index=dinner_index)
    return {"route": result}

# --- Trip optimizer algorithm ---
def trip_optimizer(data: dict, lunch_index: int = 0, dinner_index: int = 0, flip: bool = False):
    print(data)

    # Check for lunch/dinner
    if (lunch_index != -1):
        data['lunch_node'] = data['eatery_nodes'][lunch_index]
        if (dinner_index == 0):
            dinner_index += 1
    else:
        data['lunch_node'] = -1

    if (dinner_index != -1):
        data['dinner_node'] = data['eatery_nodes'][dinner_index]
    else:
        data['dinner_node'] = -1

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

    # --- Penalties: Allow to drop nodes ---
    penalty = 1000
    for node in range(1, len(data["time_matrix"])):
        if node not in data['eatery_nodes']:
            routing.AddDisjunction([manager.NodeToIndex(node)], penalty)

    # --- Lunch spot constraint ---
    if (data['lunch_node'] != -1):
        lunch_index_node = manager.NodeToIndex(data['lunch_node'])
        time_dimension.CumulVar(lunch_index_node).SetRange(
            int((data['lunch_start_hour'] - data['start_hour']) * 60),
            int((data['lunch_end_hour'] - data['start_hour']) * 60))

    # --- Dinner spot constraint ---
    if (data['dinner_node'] != -1):
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
        if (lunch_index==-1 or dinner_index==-1):
            raise HTTPException(status_code=404, detail="No solution found")

        # If both lunch & dinner exits & cannot find solution, flip lunch & dinner places first
        if not flip:
            return trip_optimizer(data=data, lunch_index=dinner_index, dinner_index=lunch_index, flip=True)
        else:
            # Revert back to normal if flipping doesn't work
            lunch_index, dinner_index = dinner_index, lunch_index

        # Set dinner node to next element in 'eatery_nodes' if exists
        if dinner_index + 1 < len(data['eatery_nodes']):
            return trip_optimizer(data=data, lunch_index=lunch_index, dinner_index=dinner_index + 1, flip=False)

        # Set lunch node next if still no solution
        elif lunch_index + 1 < len(data['eatery_nodes']) - 1:
            return trip_optimizer(data=data, lunch_index=lunch_index + 1, dinner_index=lunch_index + 2, flip=False)
        else:
            raise HTTPException(status_code=404, detail="No solution found")


def _format_solution(routing, manager, time_dimension, solution, data: dict):
    index = routing.Start(0)
    route = []
    route_index = 0
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        time_val = solution.Value(time_dimension.CumulVar(index))
        route_item = {}
        route_item['route_index'] = route_index
        route_item["place_id"] = data['placeIDs'][node]
        route_item["arrival_time"] = f"{data['start_hour'] + time_val // 60:02d}:{time_val % 60:02d}"
        route_item["service_time"] = data["service_times"][node]

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
        route_index += 1

    return_time = solution.Value(time_dimension.CumulVar(index))
    final = {
        "route_index": route_index,
        "place_id": data['placeIDs'][data['depot']],
        "arrival_time": f"{data['start_hour'] + return_time // 60:02d}:{return_time % 60:02d}",
        "service_time":data["service_times"][data['depot']],
        "type": "End"
    }
    route.append(final)

    return route

def get_time_matrix(places: list[str]) -> list[list]:
    """
    Given list of place ids (GoogleMaps IDs), returns 2D time matrix of durations in minutes.
    """
    N = len(places)
    origins = [{"waypoint":{"placeId":place_id}} for place_id in places]
    destinations = origins
    url = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': GOOGLE_API_KEY,
        'X-Goog-FieldMask': 'originIndex,destinationIndex,duration,condition,status'
    }
    params = {
        "origins": origins,
        "destinations": destinations,
        "travelMode": "TRANSIT",
    }
    response = requests.post(url=url,headers=headers,json=params)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code,detail=response.text)
    data = response.json()

    time_matrix = [[0 for _ in range(N)] for _ in range(N)] # Initialize 2d NxN array

    for entry in data:
        if len(entry['status']) != 0:
            raise HTTPException(status_code=500, detail=f"Distance Matrix API error: {entry['status']}")
        
        elif entry['originIndex'] == entry['destinationIndex']:
            entry['duration'] = 0  # Zero duration for same origin and destination

        elif entry['condition'] == "ROUTE_NOT_FOUND":
            raise HTTPException(status_code=500, detail="No route found between some locations")
        
        else:
            time_matrix[entry['originIndex']][entry['destinationIndex']] = int(entry['duration'][:-1])//60      

    return time_matrix


def identify_eateries(places: list[str]) -> list[int]:
    """
    Identify eateries (restaurant, cafe, food, etc.) among coords using Google Places Nearby Search API.
    Returns list of indexes corresponding to eatery coordinates.
    """
    EATERY_TYPES = ["restaurant", "diner", "food_court"]
    eatery_indexes = []

    N = len(places)

    for i in range(N):
        url = f"https://places.googleapis.com/v1/places/{places[i]}"
        headers = {
            'Content-Type': 'application/json',
            'X-Goog-Api-Key': GOOGLE_API_KEY,
            'X-Goog-FieldMask': 'id,types'
        }
        response = requests.get(url=url,headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code,detail=response.text)
        data = response.json()

        for place_type in data['types']:
            if place_type in EATERY_TYPES:
                eatery_indexes.append(i+1)
                break

    return eatery_indexes