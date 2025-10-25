from typing import List

from pydantic import BaseModel, Field

from app.models.cluster_models import ClusterIn, ClusterOut


class CityClusterIn(ClusterIn):
    city: str = Field(..., description="Name of the city associated with these locations")


class MultiClusterIn(BaseModel):
    cities: List[CityClusterIn] = Field(
        ...,
        description="Collection of city-specific clustering requests",
        min_length=1,
    )


class CityClusterOut(BaseModel):
    city: str = Field(..., description="City corresponding to this cluster solution")
    solution: ClusterOut = Field(..., description="Cluster results for the given city")


class MultiClusterOut(BaseModel):
    cities: List[CityClusterOut] = Field(
        ...,
        description="Cluster solutions grouped by city",
    )
