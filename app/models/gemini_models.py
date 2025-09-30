from typing import Dict, List, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field

class PlanItinIn(BaseModel):
    trip_preferences: Dict[str, int] = Field(default_factory=dict)

class LLMLocation(TypedDict, total=False):  # total=False allows optional keys
    name: str
    address: str
    category: str
    photo_url: Optional[str]  

class PlanItinOut(BaseModel):
    categories: Dict[str, List[LLMLocation]]
