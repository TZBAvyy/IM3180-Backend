from typing import Dict, List, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field, field_validator

class PlanItinIn(BaseModel):
    trip_preferences: Dict[str, int] = Field(default_factory=dict)
    city: str = Field(..., description="Target city for itinerary planning.")

    @field_validator("trip_preferences")
    @classmethod
    def validate_trip_preferences(cls, value: Dict[str, int]) -> Dict[str, int]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("trip_preferences must be a dictionary of category weights.")

        cleaned: Dict[str, int] = {}
        total = 0

        for category, raw_weight in value.items():
            if not isinstance(category, str) or not category.strip():
                raise ValueError("Preference categories must be non-empty strings.")
            try:
                weight = int(raw_weight)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid weight for category '{category}'; must be an integer.")
            if weight < 0:
                raise ValueError(f"Weight for category '{category}' cannot be negative.")
            cleaned_category = category.strip()
            cleaned[cleaned_category] = weight
            total += weight

        if cleaned and total != 100:
            raise ValueError("Sum of trip preference weights must equal 100.")

        return cleaned

    @field_validator("city")
    @classmethod
    def validate_city(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("City must be a non-empty string.")
        return value.strip()

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
