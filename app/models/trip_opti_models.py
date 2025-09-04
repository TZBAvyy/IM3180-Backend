from pydantic import BaseModel, EmailStr
from typing import Optional
from typing_extensions import TypedDict

# --- Trip Optimizer Models ---

class TripOptiIn(BaseModel):

    # Required parameters
    addresses: list[str]
    hotel_address: str
    service_times: list[int]  # time (minutes) spent at each node

    # Optional parameters with defaults
    start_hour: Optional[int] = 9
    end_hour: Optional[int] = 21
    lunch_start_hour: Optional[int] = 11
    lunch_end_hour: Optional[int] = 13
    dinner_start_hour: Optional[int] = 17
    dinner_end_hour: Optional[int] = 19

class TripAddress(TypedDict):
    address: str
    postal_code: str
    arrival_time: str  # predicted arrival time at each address
    type: str  # "Start", "Lunch", "Dinner", "Attraction", "End"

class TripOptiOut(BaseModel):
    route: list[TripAddress]