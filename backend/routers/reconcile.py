from fastapi import APIRouter, Depends

from backend.auth import require_api_key
from backend.models.medication import MedicationReconcileRequest, MedicationReconcileResponse
from backend.services import reconciliation as reconciliation_service

router = APIRouter(prefix="/api/reconcile", tags=["Reconciliation"])


@router.post(
    "/medication",
    response_model=MedicationReconcileResponse,
    summary="Reconcile conflicting medication records",
    description=(
        "Accepts medication records from multiple EHR sources and returns "
        "the most likely accurate medication with confidence score and reasoning."
    ),
)
async def reconcile_medication(
    body: MedicationReconcileRequest,
    _: str = Depends(require_api_key),  # enforces auth, value unused
) -> MedicationReconcileResponse:
    return await reconciliation_service.reconcile(body)
