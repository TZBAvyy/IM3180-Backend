from pydantic import BaseModel
from typing import Optional
from typing_extensions import TypedDict

class ClusterIn(BaseModel):
    locations_sorted: list[list[float]]  # Each location: [latitude, longitude, priority, stay_hours]
    requested_days: Optional[int] = 3
    max_hours_per_day: Optional[int] = 12

    class Config:
        json_schema_extra = {
            "example": {
                "locations_sorted": [
                    [1.290270, 103.851959, 1, 2],  # [latitude, longitude, priority, stay_hours]
                    [1.352083, 103.819836, 2, 3],
                    [1.283333, 103.833333, 3, 4],
                    [1.300000, 103.800000, 2, 5],
                    [1.310000, 103.820000, 1, 2]
                ]
            }
        }

class Location(TypedDict):
    latitude: float
    longitude: float
    priority: int
    stay_hours: int
    cluster_id: int

class ClusterOut(BaseModel):
    solution1: dict[list[Location], list[Location]]  # 'day1' and 'rejected'
    solution2: list[dict[int, list[Location]]]  # List of days with locations

    class Config:
        json_schema_extra = {
            "example": {
                "solution1": {
                    "day1": [
                        {"latitude": 1.290270, "longitude": 103.851959, "priority": 1, "stay_hours": 2, "cluster_id": 0},
                        {"latitude": 1.310000, "longitude": 103.820000, "priority": 1, "stay_hours": 2, "cluster_id": 0}
                    ],
                    "rejected": [
                        {"latitude": 1.352083, "longitude": 103.819836, "priority": 2, "stay_hours": 3, "cluster_id": 1},
                        {"latitude": 1.283333, "longitude": 103.833333, "priority": 3, "stay_hours": 4, "cluster_id": 1},
                        {"latitude": 1.300000, "longitude": 103.800000, "priority": 2, "stay_hours": 5, "cluster_id": 2}
                    ]
                },
                "solution2": [
                    {
                        "day": 1,
                        "locations": [
                            {"latitude": 1.290270, "longitude": 103.851959, "priority": 1, "stay_hours": 2, "cluster_id": 0},
                            {"latitude": 1.310000, "longitude": 103.820000, "priority": 1, "stay_hours": 2, "cluster_id": 0}
                        ]
                    },
                    {
                        "day": 2,
                        "locations": [
                            {"latitude": 1.352083, "longitude": 103.819836, "priority": 2, "stay_hours": 3, "cluster_id": 1},
                            {"latitude": 1.283333, "longitude": 103.833333, "priority": 3, "stay_hours": 4, "cluster_id": 1}
                        ]
                    },
                    {
                        "day": 3,
                        "locations": [
                            {"latitude": 1.300000, "longitude": 103.800000, "priority": 2, "stay_hours": 5, "cluster_id": 2}
                        ]
                    }
                ]
            }
        }