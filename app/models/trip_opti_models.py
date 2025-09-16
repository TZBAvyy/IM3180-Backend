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
                    "Marina Bay Sands, 10 Bayfront Ave, Singapore 018956",
                    "Lau Pa Sat, 18 Raffles Quay, Singapore 048582",
                    "Satay by the Bay, 18 Marina Gardens Dr, Singapore 018953"
                ],
                "hotel_address": "Hotel Jen Tanglin Singapore, 1A Cuscaden Rd, Singapore 249716",
                "service_times": [60, 60, 60]
            }
        }

class TripAddress(TypedDict):
    address: str
    postal_code: str
    arrival_time: str  # predicted arrival time at each address
    type: str  # "Start", "Lunch", "Dinner", "Attraction", "End"

class TripOptiOut(BaseModel):
    route: list[TripAddress]

    class Config:
        json_schema_extra = {
            "example": {
                "route": [
                    {
                        "address": "Hotel Jen Tanglin Singapore, 1A Cuscaden Rd, Singapore 249716",
                        "postal_code": "249716",
                        "arrival_time": "09:00",
                        "type": "Start"
                    },
                    {
                        "address": "Lunch Break at Lau Pa Sat, 18 Raffles Quay, Singapore 048582",
                        "postal_code": "048582",
                        "arrival_time": "11:00",
                        "type": "Lunch"
                    },
                    {
                        "address": "Marina Bay Sands, 10 Bayfront Ave, Singapore 018956",
                        "postal_code": "018956",
                        "arrival_time": "12:00",
                        "type": "Attraction"
                    },
                    {
                        "address": "Dinner Break at Satay by the Bay, 18 Marina Gardens Dr, Singapore 018953",
                        "postal_code": "018953",
                        "arrival_time": "17:00",
                        "type": "Dinner"
                    },
                    {
                        "address": "Hotel Jen Tanglin Singapore, 1A Cuscaden Rd, Singapore 249716",
                        "postal_code": "249716",
                        "arrival_time": "18:30",
                        "type": "End"
                    }
                ]
            }
        }