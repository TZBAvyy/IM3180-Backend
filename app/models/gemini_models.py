from pydantic import BaseModel
from typing import Optional, List
from typing_extensions import TypedDict

class PlanItinIn(BaseModel):
    user_stay_days: Optional[int] = 3
    max_hours_per_day: Optional[int] = 12

class LLMLocation(TypedDict):
    name: str
    latitude: float
    longitude: float
    suggested_visit_hours: int
    priority: int

class PlanItinOut(BaseModel):
    itinerary: dict[str, List[LLMLocation]]
