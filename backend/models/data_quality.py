from datetime import date
from typing import Optional, Any
from pydantic import BaseModel, Field


#  Input models 
# since the goal is to validate data, make fields optional
# optional user inputs for user info
class Demographics(BaseModel):
    name: Optional[str] = None
    dob: Optional[date] = None
    gender: Optional[str] = None


class VitalSigns(BaseModel):
    """Extra fields allowed — vitals vary by facility."""
    model_config = {"extra": "allow"}

    # assign comon fields
    blood_pressure: Optional[str] = None  # e.g. "120/80"
    heart_rate: Optional[float] = None
    temperature: Optional[float] = None
    

class DataQualityRequest(BaseModel):
    demographics: Optional[Demographics] = None
    medications: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    vital_signs: Optional[VitalSigns] = None
    last_updated: Optional[date] = None


# Output models 

class QualityBreakdown(BaseModel):
    completeness: int = Field(..., ge=0, le=100)
    accuracy: int = Field(..., ge=0, le=100)
    timeliness: int = Field(..., ge=0, le=100)
    clinical_plausibility: int = Field(..., ge=0, le=100)


class DetectedIssue(BaseModel):
    field: str
    issue: str
    severity: str  # "high" | "medium" | "low"


class DataQualityResponse(BaseModel):
    overall_score: int = Field(..., ge=0, le=100)
    breakdown: QualityBreakdown
    issues_detected: list[DetectedIssue]
    ai_analysis: Optional[str] = None  # human-readable summary from Gemini
