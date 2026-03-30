from fastapi import APIRouter, Depends

from backend.auth import require_api_key
from backend.models.data_quality import DataQualityRequest, DataQualityResponse
from backend.services import data_quality as data_quality_service

router = APIRouter(prefix="/api/validate", tags=["Validation"])


@router.post(
    "/data-quality",
    response_model=DataQualityResponse,
    summary="Validate patient record data quality",
    description=(
        "Scores a patient record across four dimensions: completeness, accuracy, "
        "timeliness, and clinical plausibility. Returns detected issues with severity."
    ),
)
async def validate_data_quality(
    body: DataQualityRequest,
    _: str = Depends(require_api_key),
) -> DataQualityResponse:
    return await data_quality_service.validate(body)
