from pydantic import BaseModel, Field
from typing import Optional, Union, List
from typing_extensions import TypedDict


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


class ClusterIn(BaseModel):
    locations_sorted: List[LocationIn]
    requested_days: Optional[int] = 3
    max_hours_per_day: Optional[int] = 12
    keyword_hint: Optional[str] = None  # optional user-provided hint to bias place_id lookup

    class Config:
        json_schema_extra = {
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


class Location(TypedDict):
    latitude: float
    longitude: float
    priority: int
    stay_hours: float
    cluster_id: int
    place_id: Optional[str]


class ClusterOut(BaseModel):
    solution1: dict
    solution2: list

    class Config:
        json_schema_extra = {
            "example": {
                "solution1": {
                    "day1": [
                        {"latitude": 1.290270, "longitude": 103.851959, "priority": 1,
                         "stay_hours": 2, "cluster_id": 0, "place_id": "ChIJd7zN_thp2jERcf0cKlU5n9A"}
                    ],
                    "rejected": []
                },
                "solution2": [
                    {
                        "day": 1,
                        "locations": [
                            {"latitude": 1.352083, "longitude": 103.819836, "priority": 2,
                             "stay_hours": 3, "cluster_id": 1, "place_id": "ChIJ..."}
                        ]
                    }
                ]
            }
        }
