from typing import Dict, List, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field

class PlanItinIn(BaseModel):
    trip_preferences: Dict[str, int] = Field(default_factory=dict)
    cities: List[str] = Field(default_factory=list)

class LLMLocation(TypedDict, total=False):  # total=False allows optional keys
    name: str
    address: str
    city: str
    category: str
    photo_url: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    place_id: Optional[str]

class PlanItinOut(BaseModel):
    status: str = Field(default="done")
    categories: Dict[str, List[LLMLocation]]
