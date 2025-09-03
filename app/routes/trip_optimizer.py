# Algorithm function for trip optimizer
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from fastapi import APIRouter

# --- Trip optimizer route ---

router = APIRouter(prefix="/trip_optimizer", tags=["trip_optimizer"])

@router.get("/")
def main_get_method():
    return {"message": "Trip Optimizer Endpoint","success": True}

# test with:
# curl -L -v "localhost:8000/trip_optimizer/" -H "Content-Type: application/json" -d @post_data_test.json
@router.post("/")
def main_post_method(request: dict):
    
    # --- Required parameters ---
    addresses = request.get("addresses", None)
    hotel_address = request.get("hotel_address", None)
    service_times = request.get("service_times", None)

    # --- Optional paramters with default values ---
    start_hour = request.get("start_hour", 9)
    end_hour = request.get("end_hour", 21)
    lunch_start_hour = request.get("lunch_start_hour", 11)
    lunch_end_hour = request.get("lunch_end_hour", 13)
    dinner_start_hour = request.get("dinner_start_hour", 17)
    dinner_end_hour = request.get("dinner_end_hour", 19)

    # --- Input validation ---
    if addresses is None or hotel_address is None or service_times is None: # If passes => all fields present
        return {"route":[],"success":False,"error": "Missing required fields"}

    if len(addresses) != len(service_times): # If passes => lengths of address and service_times match
        return {"route":[],"success":False,"error": "Length of addresses and service_times must match"}
    
    if len(addresses) < 1: # If passes => at least one address (besides hotel)
        return {"route":[],"success":False,"error": "At least two eatery nodes are required"}
    
    # TODO: Put address and hotel verification here (e.g. using GOOGLE API)
    # NEED TO RETRIEVE eatery_nodes and time_matrix FROM GOOGLE API

    # --- Format Settings for Optimizer ---
    data = {}

    # TODO: HIS BLOCK IS HARD CODED FOR TESTING, CHANGE ON GOOGLE API INTEGRATION
    data['eatery_nodes'] = [3, 4] # indexes of lunch and dinner spots in the time_matrix
    data['time_matrix'] = [ 
        [0, 12, 23, 34, 45, 21, 32, 28], # time (minutes) between each pair of nodes 
        [12, 0, 17, 29, 38, 19, 27, 24], # (e.g data['time_matrix'][i][j] is time taken to travel from node i to j)
        [23, 17, 0, 15, 27, 22, 18, 20],
        [34, 29, 15, 0, 16, 25, 21, 19],
        [45, 38, 27, 16, 0, 30, 24, 22],
        [21, 19, 22, 25, 30, 0, 14, 18],
        [32, 27, 18, 21, 24, 14, 0, 13],
        [28, 24, 20, 19, 22, 18, 13, 0]
    ]
    data["postal_codes"] = ["00000"+str(i) for i in range(len(addresses)+1)] # postal codes for each address
    # TODO: THIS BLOCK IS HARD CODED FOR TESTING, CHANGE ON GOOGLE API INTEGRATION

    data['addresses'] = [hotel_address] + addresses
    data['service_times'] = [0] + service_times  # time (minutes) spent at each node
    data['num_vehicles'] = 1
    data['depot'] = 0  # start and end at node 0
    data['start_hour'] = start_hour
    data['end_hour'] = end_hour
    data['lunch_start_hour'] = lunch_start_hour
    data['lunch_end_hour'] = lunch_end_hour
    data['dinner_start_hour'] = dinner_start_hour
    data['dinner_end_hour'] = dinner_end_hour
    
    result = trip_optimizer(data)
    return result

 
# --- Trip optimizer algorithm ---

def trip_optimizer(data: dict, lunch_index:int=0, dinner_index:int=1, flip:bool=False): 
    
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
    horizon = (data['end_hour']-data['start_hour']) * 60  # horizon is total minutes in the day 
    routing.AddDimension(
        transit_callback_index,
        slack_max=0,  # no waiting
        capacity=horizon,
        fix_start_cumul_to_zero=True,
        name='Time')
    time_dimension = routing.GetDimensionOrDie('Time')

    # --- Lunch spot constraint ---
    lunch_index = manager.NodeToIndex(data['lunch_node'])
    time_dimension.CumulVar(lunch_index).SetRange(
        int((data['lunch_start_hour']-data['start_hour'])*60), 
        int((data['lunch_end_hour']-data['start_hour'])*60)) 

     # --- Dinner spot constraint ---
    dinner_index = manager.NodeToIndex(data['dinner_node'])
    time_dimension.CumulVar(dinner_index).SetRange(
        int((data['dinner_start_hour']-data['start_hour'])*60), 
        int((data['dinner_end_hour']-data['start_hour'])*60))  

    # --- Solve ---
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)

    solution = routing.SolveWithParameters(search_parameters)

    # --- Print solution ---
    if solution:
        route = _format_solution(routing, manager, time_dimension, solution, data)
        return {"route":route,"success":True,"error":None}
    else:
        # 
        if not flip:
            trip_optimizer(data=data, lunch_index=dinner_index, dinner_index=lunch_index, flip=True)
        else:
            lunch_index, dinner_index = dinner_index, lunch_index

        if dinner_index+1 < len(data['eatery_nodes']):
            trip_optimizer(data=data, lunch_index=lunch_index, dinner_index=dinner_index + 1, flip=False)
            
        elif lunch_index+1 < len(data['eatery_nodes']) - 1:
            trip_optimizer(data=data, lunch_index=lunch_index + 1, dinner_index=lunch_index + 2, flip=False,)
        else:
            print("No solution found!")
            return {"route":[],"success":False,"error": "No solution found"}
        
def _format_solution(routing, manager, time_dimension, solution, data: dict):
    index = routing.Start(0)
    route = []
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        time_val = solution.Value(time_dimension.CumulVar(index))
        route_item = {}
        route_item["address"] = data['addresses'][node]
        route_item["postal_code"] = data['postal_codes'][node]
        route_item["arrival_time"] = f"{data['start_hour']+time_val//60:02d}:{time_val%60:02d}"

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
    final = {}
    final["address"] = data['addresses'][data['depot']]
    final["postal_code"] = "000000" # TODO: Placeholder for postal code
    final["arrival_time"] = f"{data['start_hour']+return_time//60:02d}:{return_time%60:02d}"
    final["type"] = "End"
    route.append(final)
    
    return route