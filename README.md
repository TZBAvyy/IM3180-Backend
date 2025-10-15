# Trip Optimizer (IM3180 Project) Repository
NTU IM3180: Design &amp; Innovation Project, Group IE04, AY2025/2026  
Repository for Backend API of the Trip Optimizer Web Application

## Quickstart:

### VSCode Python Extension Method
> In the search bar at the top middle of the window
1. Type "\> Python: Create Environment"
2. Click "Venv" for environment type
3. Click whatever Python version you have (should be fine >3.x)
4. Click "requirements.txt" for dependacies to install and give it a bit
5. Kill and refresh terminal in VSCode, its working if your terminal looks like:
<pre><b>(.venv)</b> C:\...</pre>
6. Run below in the console
```
fastapi dev app/main.py
``` 

### CLI Method
1. Create a python venv  
```
python -m venv venv
```

2. Active the venv
> a. (Windows)  
```cmd
venv\Scripts\activate
```
> b. (macOS/Linux)
```bash
source venv/bin/activate
```

3. Install required dependencies into venv  
```
pip install -r requirements.txt
```

4. Run below in the console
```
fastapi dev app/main.py
``` 


## Documentation

### /trip_optimizer/
#### JSON Input
Example:
```json
{
    "addresses":[
        "ChIJYakjWbYZ2jERgSiDZRBS8OY",
        "ChIJzVHFNqkZ2jERboLN2YrltH8",
        "ChIJRYMSeKwe2jERAR2QXVU39vg",
        "ChIJ42h1onIZ2jERBbs-VGqmwrs",
        "ChIJC00vnUgZ2jERodPEc17Iv3Q",
        "ChIJgftoQGYZ2jERYN5VifWB6Ms",
        "ChIJWT0bvgsZ2jERM7sHz6m87gE"
    ], 
    "hotel_index":0, 
    "service_times":[0, 30, 120, 120, 120, 30, 60]
}
```
| attribute         | isRequired? | type            | description                                                                                        |
|-------------------|-------------|-----------------|----------------------------------------------------------------------------------------------------|
| addresses         | **True**    | array[n] of str | Array of place ids of hotel, food places and attractions, <br>must be equal length to service_times                             |
| hotel_index       | **True**    | int             | Index of  starting node in addresses                                                                           |
| service_times     | **True**    | array[n] of int | Array of expected time spent at each address listed in mins, <br>must be equal length to addresses |
| start_hour        | **False**   | int             | Expected time of day start (e.g 13 => 1pm start), <br>default: 9 (9am)                             |
| end_hour          | **False**   | int             | Expected time of day end, <br>default: 21 (9pm)                                                    |
| lunch_start_hour  | **False**   | int             | Expected starting time range of lunch period, <br>default: 11 (11am)                               |
| lunch_end_hour    | **False**   | int             | Expected ending time range of lunch period, <br>default: 13 (1pm)                                  |
| dinner_start_hour | **False**   | int             | Expected starting time range of dinner period, <br>default: 17 (5pm)                               |
| dinner_end_hour   | **False**   | int             | Expected ending time range of dinner period, default: 19 (7pm)                                     |


#### JSON Output
Example
```json
{
  "route": [
    {
      "place_id": "ChIJYakjWbYZ2jERgSiDZRBS8OY",
      "arrival_time": "09:00",
      "service_time": 0,
      "type": "Start"
    },
    {
      "place_id": "ChIJC00vnUgZ2jERodPEc17Iv3Q",
      "arrival_time": "11:22",
      "service_time": 120,
      "type": "Lunch"
    },
    {
      "place_id": "ChIJzVHFNqkZ2jERboLN2YrltH8",
      "arrival_time": "12:03",
      "service_time": 30,
      "type": "Attraction"
    },
    {
      "place_id": "ChIJRYMSeKwe2jERAR2QXVU39vg",
      "arrival_time": "14:50",
      "service_time": 120,
      "type": "Attraction"
    },
    {
      "place_id": "ChIJ42h1onIZ2jERBbs-VGqmwrs",
      "arrival_time": "17:40",
      "service_time": 120,
      "type": "Attraction"
    },
    {
      "place_id": "ChIJgftoQGYZ2jERYN5VifWB6Ms",
      "arrival_time": "18:11",
      "service_time": 30,
      "type": "Dinner"
    },
    {
      "place_id": "ChIJWT0bvgsZ2jERM7sHz6m87gE",
      "arrival_time": "19:25",
      "service_time": 60,
      "type": "Attraction"
    },
    {
      "place_id": "ChIJYakjWbYZ2jERgSiDZRBS8OY",
      "arrival_time": "19:43",
      "service_time": 0,
      "type": "End"
    }
  ]
}
```
