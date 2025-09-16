from pydantic import BaseModel
from typing import Optional
from typing_extensions import TypedDict

# --- Trip Optimizer Models ---

class TripOptiIn(BaseModel):

    # Required parameters
    addresses: list[str] # list of address's place IDs
    hotel_address: str # starting location place ID
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
                    "placeID-1",
                    "placeID-2",
                    "placeID-3"
                ],
                "hotel_address": "placeID-hotel",
                "service_times": [60, 60, 60]
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
                    "name": "Hotel Boss",
                    "place_id": "ChIJYakjWbYZ2jERgSiDZRBS8OY",
                    "arrival_time": "09:00",
                    "type": "Start"
                    },
                    {
                    "name": "Saizeriya @ Marina Square",
                    "place_id": "ChIJC00vnUgZ2jERodPEc17Iv3Q",
                    "arrival_time": "11:17",
                    "type": "Lunch"
                    },
                    {
                    "name": "Singapore Flyer",
                    "place_id": "ChIJzVHFNqkZ2jERboLN2YrltH8",
                    "arrival_time": "11:58",
                    "type": "Attraction"
                    },
                    {
                    "name": "McDonald's Boat Quay",
                    "place_id": "ChIJWT0bvgsZ2jERM7sHz6m87gE",
                    "arrival_time": "13:18",
                    "type": "Attraction"
                    },
                    {
                    "name": "Sentosa",
                    "place_id": "ChIJRYMSeKwe2jERAR2QXVU39vg",
                    "arrival_time": "16:03",
                    "type": "Attraction"
                    },
                    {
                    "name": "Chinatown Hawker Center",
                    "place_id": "ChIJgftoQGYZ2jERYN5VifWB6Ms",
                    "arrival_time": "17:22",
                    "type": "Dinner"
                    },
                    {
                    "name": "Chinatown",
                    "place_id": "ChIJ42h1onIZ2jERBbs-VGqmwrs",
                    "arrival_time": "19:23",
                    "type": "Attraction"
                    },
                    {
                    "name": "Hotel Boss",
                    "place_id": "ChIJYakjWbYZ2jERgSiDZRBS8OY",
                    "arrival_time": "19:47",
                    "type": "End"
                    }
                ]
            }
        }