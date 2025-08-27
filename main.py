from ortools.constraint_solver import pywrapcp, routing_enums_pb2

def main(eatery_nodes, lunch_index=0, dinner_index=1, flip=False):
    if len(eatery_nodes) < 2:
        print("At least two eatery nodes are required.")

    # --- Problem data ---
    data = {}
    data['time_matrix'] = [  # travel times (minutes) between 8 nodes (symmetric)
        [0, 12, 23, 34, 45, 21, 32, 28],
        [12, 0, 17, 29, 38, 19, 27, 24],
        [23, 17, 0, 15, 27, 22, 18, 20],
        [34, 29, 15, 0, 16, 25, 21, 19],
        [45, 38, 27, 16, 0, 30, 24, 22],
        [21, 19, 22, 25, 30, 0, 14, 18],
        [32, 27, 18, 21, 24, 14, 0, 13],
        [28, 24, 20, 19, 22, 18, 13, 0]
    ]
    data['service_times'] = [0, 30, 2*60, 2*60, 2*60, 30, 60, 45]  # time (minutes) spent at each node
    data['num_vehicles'] = 1
    data['depot'] = 0  # start and end at node 0
    data['lunch_node'] = eatery_nodes[lunch_index]
    data['dinner_node'] = eatery_nodes[dinner_index]

    # --- Time windows ---
    start_time = 9 
    end_time = 21

    lunch_start_time = 11
    lunch_end_time = 13

    dinner_start_time = 19
    dinner_end_time = 21

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
    horizon = (end_time-start_time) * 60  # horizon is total minutes in the day 
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
        int((lunch_start_time-start_time)*60), 
        int((lunch_end_time-start_time)*60)) 

     # --- Dinner spot constraint ---
    dinner_index = manager.NodeToIndex(data['dinner_node'])
    time_dimension.CumulVar(dinner_index).SetRange(
        int((dinner_start_time-start_time)*60), 
        int((dinner_end_time-start_time)*60))  

    # --- Solve ---
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)

    solution = routing.SolveWithParameters(search_parameters)

    # --- Print solution ---
    if solution:
        print(f"Route:")
        index = routing.Start(0)
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            time_val = solution.Value(time_dimension.CumulVar(index))
            if node == data['depot']:
                print(f"Node {node} (Hotel) at time {start_time}:00")
            elif node == data['lunch_node']:
                print(f"Node {node} (Lunch) at time {start_time+time_val//60:02d}:{time_val%60:02d}")
            elif node == data['dinner_node']:
                print(f"Node {node} (Dinner) at time {start_time+time_val//60:02d}:{time_val%60:02d}")
            else:
                print(f"Node {node} at time {start_time+time_val//60:02d}:{time_val%60:02d}")
            index = solution.Value(routing.NextVar(index))
        return_time = solution.Value(time_dimension.CumulVar(index))
        print(f"Return to Node {manager.IndexToNode(index)} at time {start_time+return_time//60:02d}:{return_time%60:02d}")
    else:
        if not flip:
            main(eatery_nodes, lunch_index=dinner_index, dinner_index=lunch_index, flip=True)
        else:
            lunch_index, dinner_index = dinner_index, lunch_index

        if dinner_index+1 < len(eatery_nodes):
            main(eatery_nodes, lunch_index=lunch_index, dinner_index=dinner_index + 1, flip=False)
        elif lunch_index+1 < len(eatery_nodes) - 1:
            main(eatery_nodes, lunch_index=lunch_index + 1, dinner_index=lunch_index + 2, flip=False)
        else:
            print("No solution found!")

if __name__ == '__main__':
    main([1,3,4])
