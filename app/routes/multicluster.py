from fastapi import APIRouter, HTTPException

from app.models.multicluster_models import MultiClusterIn, MultiClusterOut, CityClusterOut
from app.models.error_models import HTTPError
from app.routes.cluster import get_clusters_given_all_locations

router = APIRouter(prefix="/multicluster", tags=["multicluster"])


@router.get("/")
def test():
    return {"message": "Multi-cluster Endpoint", "success": True}


@router.post(
    "/",
    response_model=MultiClusterOut,
    responses={
        400: {
            "description": "Missing required parameters",
            "model": HTTPError,
        }
    },
)
def get_multicity_clusters(data: MultiClusterIn) -> MultiClusterOut:
    if not data.cities:
        raise HTTPException(status_code=400, detail="At least one city must be provided")

    city_solutions: list[CityClusterOut] = []

    for city_request in data.cities:
        try:
            city_cluster = get_clusters_given_all_locations(city_request)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            raise HTTPException(
                status_code=exc.status_code,
                detail=f"City '{city_request.city}': {detail}",
            )
        city_solutions.append(CityClusterOut(city=city_request.city, solution=city_cluster))

    return MultiClusterOut(cities=city_solutions)
