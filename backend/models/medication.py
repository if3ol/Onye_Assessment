from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


#  Input models

class RecentLabs(BaseModel):
    """Flexible model — labs vary per patient so we allow any key/value pairs."""
    model_config = {"extra": "allow"}

    eGFR: Optional[float] = None
    

class PatientContext(BaseModel):
    age: int = Field(..., ge=0, le=200)
    conditions: list[str] = Field(default_factory=list)
    recent_labs: Optional[RecentLabs] = None


class MedicationSource(BaseModel):
    system: str = Field(..., min_length=1)
    medication: str = Field(..., min_length=1)

    # One of these date fields will be present depending on source type
    last_updated: Optional[date] = None
    last_filled: Optional[date] = None

    source_reliability: str = Field(
        ...,
        pattern="^(high|medium|low)$",  # enforces only valid values
    )

    @property
    def effective_date(self) -> Optional[date]:
        """Returns whichever date field is present."""
        return self.last_updated or self.last_filled


class MedicationReconcileRequest(BaseModel):
    patient_context: PatientContext
    sources: list[MedicationSource] = Field(..., min_length=2)


#  Output models 

class MedicationReconcileResponse(BaseModel):
    reconciled_medication: str
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    recommended_actions: list[str]
    clinical_safety_check: str  # "PASSED" | "FAILED" | "REVIEW_REQUIRED"
    source_analysis: list[dict]  # breakdown of how each source was weighted
