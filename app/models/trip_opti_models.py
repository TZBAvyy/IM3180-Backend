from pydantic import BaseModel
from typing import Optional
from typing_extensions import TypedDict

# --- Trip Optimizer Models ---

class TripOptiIn(BaseModel):

    # Required parameters
    addresses: list[str] # list of address's place IDs
    hotel_index: int # starting location place index in addresses list
    service_times: list[int]  # time (minutes) spent at each node

    # Optional parameters with defaults
    start_hour: Optional[int] = 9
    end_hour: Optional[int] = 21
    lunch_start_hour: Optional[int] = 11
    lunch_end_hour: Optional[int] = 13
    dinner_start_hour: Optional[int] = 17
    dinner_end_hour: Optional[int] = 19

    class Config:
        json_schema_extra = {
            "example": {
                "addresses": [
                    "placeID-hotel",
                    "placeID-1",
                    "placeID-lunch",
                    "placeID-3",
                    "placeID-dinner",
                ],
                "hotel_index": 0,
                "service_times": [0, 20, 60, 60, 60]
            }
        }

class TripAddress(TypedDict):
    name: str
    place_id: str
    arrival_time: str  # predicted arrival time at each address
    type: str  # "Start", "Lunch", "Dinner", "Attraction", "End"

class TripOptiOut(BaseModel):
    route: list[TripAddress]

    class Config:
        json_schema_extra = {
            "example": {
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
        }