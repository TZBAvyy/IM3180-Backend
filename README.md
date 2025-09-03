# IM3180
Repository for NTU IM3180: Design &amp; Innovation Project

## Quickstart:

### VSCode Python Extension Method
> In the search bar at the top middle of the window
1. Type "\> Python: Create Environment"
1. Click "Venv" for environment type
1. Click whatever Python version you have (should be fine >3.x)
1. Click "requirements.txt" for dependacies to install and give a bit
1. Kill and refresh terminal in VSCode, its working if your terminal looks like:   
```(.venv) C:\...```
1. Run ```fastapi dev app/main.py``` in the console

### CLI Method
1. Create a python venv  
```py -m venv venv```

1. Active the venv 
```venv\Scripts\activate``` (Windows)  
```source venv/bin/activate``` (macOS/Linux)

1. Install required dependencies into venv  
```pip install -r requirements.txt```

1. Run ```fastapi dev app/main.py``` in the console


## Documentation

### /trip_optimizer/
#### JSON Input
Example:
```
{
    "addresses":["Hall 2","Pioneer Hall","Can 1","Can 2","Hall 5","Hall 6","Crescent Hall"], 
    "hotel_address":"Hall 1", 
    "service_times":[30, 120, 120, 120, 30, 60, 45]
    "start_hour":9,
    "end_hour":21,
    "lunch_start_hour":11,
    "lunch_end_hour":13,
    "dinner_start_hour":19,
    "dinner_end_hour":21
}
```
| attribute         | isRequired? | type            | description                                                                                        |
|-------------------|-------------|-----------------|----------------------------------------------------------------------------------------------------|
| addresses         | **True**    | array[n] of str | Array of addresses to visit, <br>must be equal length to service_times                             |
| hotel_address     | **True**    | str             | Address of starting node                                                                           |
| service_times     | **True**    | array[n] of int | Array of expected time spent at each address listed in mins, <br>must be equal length to addresses |
| start_hour        | **False**   | int             | Expected time of day start (e.g 13 => 1pm start), <br>default: 9 (9am)                             |
| end_hour          | **False**   | int             | Expected time of day end, <br>default: 21 (9pm)                                                    |
| lunch_start_hour  | **False**   | int             | Expected starting time range of lunch period, <br>default: 11 (11am)                               |
| lunch_end_hour    | **False**   | int             | Expected ending time range of lunch period, <br>default: 13 (1pm)                                  |
| dinner_start_hour | **False**   | int             | Expected starting time range of dinner period, <br>default: 17 (5pm)                               |
| dinner_end_hour   | **False**   | int             | Expected ending time range of dinner period, default: 19 (7pm)                                     |


#### JSON Output
Example
```
{   
    "route":[
        {"address":"Hall 1","postal_code":"000000","arrival_time":"09:00","type":"Start"},
        {"address":"Hall 2","postal_code":"000001","arrival_time":"09:42","type":"Attraction"},
        {"address":"Hall 5","postal_code":"000005","arrival_time":"10:31","type":"Attraction"},
        {"address":"Can 1","postal_code":"000003","arrival_time":"12:56","type":"Lunch"},
        {"address":"Crescent Hall","postal_code":"000007","arrival_time":"14:00","type":"Attraction"},
        {"address":"Hall 6","postal_code":"000006","arrival_time":"15:13","type":"Attraction"},
        {"address":"Can 2","postal_code":"000004","arrival_time":"17:37","type":"Dinner"},
        {"address":"Pioneer Hall","postal_code":"000002","arrival_time":"20:04","type":"Attraction"},
        {"address":"Hall 1","postal_code":"000000","arrival_time":"20:27","type":"End"}
    ],
    "success":true,
    "error":null
} 
OR
{"route":[],"success":false,"error": "Length of addresses and service_times must match"}
```