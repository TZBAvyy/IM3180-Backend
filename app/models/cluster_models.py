from pydantic import BaseModel, Field, model_validator
from typing import Optional, List


# ----------------------------
# Input Models
# ----------------------------

class LocationIn(BaseModel):
    place_id: Optional[str] = Field(
        None, description="Google Place ID if available. If given, latitude/longitude can be omitted."
    )
    latitude: Optional[float] = Field(
        None, description="Latitude of the location. Required if place_id is not provided."
    )
    longitude: Optional[float] = Field(
        None, description="Longitude of the location. Required if place_id is not provided."
    )
    priority: int = Field(..., description="Priority score of this location")
    stay_hours: float = Field(..., description="Planned stay duration at this location (hours)")

    @model_validator(mode="after")
    def check_coordinates_or_placeid(self):
        """Ensure at least one of (place_id) OR (latitude+longitude) is provided."""
        if not self.place_id and (self.latitude is None or self.longitude is None):
            raise ValueError(
                "Each location must provide either place_id or both latitude and longitude"
            )
        return self


class ClusterIn(BaseModel):
    locations_sorted: List[LocationIn]
    requested_days: Optional[int] = Field(3, description="Number of days requested for trip")
    max_hours_per_day: Optional[int] = Field(12, description="Maximum hours available per day")
    keyword_hint: Optional[str] = Field(None, description="Optional user-provided hint to bias place_id lookup")

    model_config = {
        "json_schema_extra": {
            "example": {
                "locations_sorted": [
                    {"latitude": 1.290270, "longitude": 103.851959, "priority": 1, "stay_hours": 2},
                    {"place_id": "ChIJd7zN_thp2jERcf0cKlU5n9A", "priority": 2, "stay_hours": 3},
                    {"latitude": 1.283333, "longitude": 103.833333, "priority": 3, "stay_hours": 4},
                ],
                "requested_days": 2,
                "max_hours_per_day": 8
            }
        }
    }


# ----------------------------
# Output Models
# ----------------------------

class LocationOut(BaseModel):
    latitude: float = Field(..., description="Latitude of the location")
    longitude: float = Field(..., description="Longitude of the location")
    priority: int = Field(..., description="Priority score of this location")
    stay_hours: float = Field(..., description="Planned stay duration at this location (hours)")
    cluster_id: int = Field(..., description="Cluster ID assigned by DBSCAN")
    place_id: Optional[str] = Field(None, description="Resolved Google Place ID (if available)")


class DayOut(BaseModel):
    day: int = Field(..., description="Day number")
    locations: List[LocationOut]


class UserPreferenceSolutionOut(BaseModel):
    days: List[DayOut]
    rejected: List[LocationOut]


class OptimalSolutionOut(BaseModel):
    days: List[DayOut]


class ClusterOut(BaseModel):
    user_preference_solution: UserPreferenceSolutionOut
    optimal_solution: OptimalSolutionOut

    model_config = {
        "json_schema_extra": {
            "example": {
                "user_preference_solution": {
                    "days": [
                        {
                            "day": 1,
                            "locations": [
                                {
                                    "latitude": 1.290270,
                                    "longitude": 103.851959,
                                    "priority": 1,
                                    "stay_hours": 2,
                                    "cluster_id": 0,
                                    "place_id": "ChIJd7zN_thp2jERcf0cKlU5n9A"
                                }
                            ],
                        }
                    ],
                    "rejected": []
                },
                "optimal_solution": {
                    "days": [
                        {
                            "day": 1,
                            "locations": [
                                {
                                    "latitude": 1.352083,
                                    "longitude": 103.819836,
                                    "priority": 2,
                                    "stay_hours": 3,
                                    "cluster_id": 1,
                                    "place_id": "ChIJ..."
                                }
                            ]
                        }
                    ]
                }
            }
        }
    }
