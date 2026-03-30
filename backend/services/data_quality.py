"""
Data Quality Validation Service

Scores a patient record across four dimensions:
  - Completeness    : are expected fields present and populated?
  - Accuracy        : are values within plausible ranges?
  - Timeliness      : how recent is the data?
  - Clinical plausibility : do medications/conditions/vitals make clinical sense together?

Each dimension runs independent rule checks. Each check can:
  - Deduct points from that dimension's score
  - Append an issue to issues_detected with a severity level

After all rules run, Gemini adds a plain-English summary for the clinician.
"""
from datetime import date
from typing import Optional

from backend.models.data_quality import (
    DataQualityRequest,
    DataQualityResponse,
    QualityBreakdown,
    DetectedIssue,
)
from backend.services.ai_service import get_data_quality_analysis


#  Completeness checks 

def _check_completeness(record: DataQualityRequest) -> tuple[int, list[DetectedIssue]]:
    """
    Starts at 100 and deducts for missing fields.
    Allergy documentation is flagged as medium (absence could mean not asked,
    not that the patient has none — clinically important distinction).
    """
    score = 100
    issues = []

    if not record.demographics:
        score -= 20
        issues.append(DetectedIssue(
            field="demographics",
            issue="Demographics block entirely missing",
            severity="high",
        ))
    else:
        d = record.demographics
        if not d.name:
            score -= 5
            issues.append(DetectedIssue(field="demographics.name", issue="Patient name missing", severity="low"))
        if not d.dob:
            score -= 10
            issues.append(DetectedIssue(field="demographics.dob", issue="Date of birth missing", severity="medium"))
        if not d.gender:
            score -= 5
            issues.append(DetectedIssue(field="demographics.gender", issue="Gender not documented", severity="low"))

    if not record.medications:
        score -= 10
        issues.append(DetectedIssue(
            field="medications",
            issue="No medications documented — confirm patient is not on any medications",
            severity="medium",
        ))

    if not record.allergies:
        score -= 15
        issues.append(DetectedIssue(
            field="allergies",
            issue="No allergies documented — likely incomplete rather than confirmed NKDA",
            severity="medium",
        ))

    if not record.conditions:
        score -= 10
        issues.append(DetectedIssue(
            field="conditions",
            issue="No conditions documented",
            severity="medium",
        ))

    if not record.vital_signs:
        score -= 10
        issues.append(DetectedIssue(
            field="vital_signs",
            issue="Vital signs block missing",
            severity="medium",
        ))

    return max(score, 0), issues


#  Accuracy checks 

def _parse_blood_pressure(bp_str: str) -> Optional[tuple[int, int]]:
    """Parses '120/80' -> (120, 80). Returns None if unparseable."""
    try:
        parts = bp_str.strip().split("/")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except (ValueError, AttributeError):
        pass
    return None


def _check_accuracy(record: DataQualityRequest) -> tuple[int, list[DetectedIssue]]:
    """
    Validates that values fall within physiologically plausible ranges.
    
    """
    score = 100
    issues = []

    if record.vital_signs:
        v = record.vital_signs

        # Blood pressure
        if v.blood_pressure:
            parsed = _parse_blood_pressure(v.blood_pressure)
            if parsed is None:
                score -= 15
                issues.append(DetectedIssue(
                    field="vital_signs.blood_pressure",
                    issue=f"Blood pressure '{v.blood_pressure}' is not in expected format (systolic/diastolic)",
                    severity="medium",
                ))
            else:
                systolic, diastolic = parsed
                if not (50 <= systolic <= 300):
                    score -= 25
                    issues.append(DetectedIssue(
                        field="vital_signs.blood_pressure",
                        issue=f"Systolic BP {systolic} mmHg is outside plausible range (50-300)",
                        severity="high",
                    ))
                if not (30 <= diastolic <= 200):
                    score -= 20
                    issues.append(DetectedIssue(
                        field="vital_signs.blood_pressure",
                        issue=f"Diastolic BP {diastolic} mmHg is outside plausible range (30-200)",
                        severity="high",
                    ))
                if parsed and diastolic >= systolic:
                    score -= 20
                    issues.append(DetectedIssue(
                        field="vital_signs.blood_pressure",
                        issue=f"Diastolic BP ({diastolic}) is >= systolic ({systolic}) — physiologically impossible",
                        severity="high",
                    ))

        # Heart rate
        if v.heart_rate is not None:
            if not (20 <= v.heart_rate <= 300):
                score -= 20
                issues.append(DetectedIssue(
                    field="vital_signs.heart_rate",
                    issue=f"Heart rate {v.heart_rate} bpm is outside plausible range (20-300)",
                    severity="high",
                ))

        # Temperature (Fahrenheit range)
        if v.temperature is not None:
            if not (85 <= v.temperature <= 115):
                score -= 15
                issues.append(DetectedIssue(
                    field="vital_signs.temperature",
                    issue=f"Temperature {v.temperature}°F is outside plausible range (85-115°F)",
                    severity="medium",
                ))

        

    # Age-based sanity check
    if record.demographics and record.demographics.dob:
        age = (date.today() - record.demographics.dob).days // 365
        if age < 0 or age > 200:
            score -= 20
            issues.append(DetectedIssue(
                field="demographics.dob",
                issue=f"Calculated age {age} years is implausible",
                severity="high",
            ))

    return max(score, 0), issues


#  Timeliness checks 

def _check_timeliness(record: DataQualityRequest) -> tuple[int, list[DetectedIssue]]:
    """
    Scores based on how recently the record was updated.
    Thresholds reflect typical clinical review cycles.
    """
    score = 100
    issues = []

    if not record.last_updated:
        score -= 40
        issues.append(DetectedIssue(
            field="last_updated",
            issue="No last_updated date — cannot assess data freshness",
            severity="medium",
        ))
        return score, issues

    days_old = (date.today() - record.last_updated).days

    if days_old > 365:
        score -= 40
        issues.append(DetectedIssue(
            field="last_updated",
            issue=f"Record is {days_old // 30} months old — significant portions may be outdated",
            severity="high",
        ))
    elif days_old > 180:
        score -= 25
        issues.append(DetectedIssue(
            field="last_updated",
            issue=f"Record is {days_old // 30} months old — review recommended",
            severity="medium",
        ))
    elif days_old > 90:
        score -= 10
        issues.append(DetectedIssue(
            field="last_updated",
            issue=f"Record is {days_old} days old",
            severity="low",
        ))

    return max(score, 0), issues



def _check_clinical_plausibility(record: DataQualityRequest) -> tuple[int, list[DetectedIssue]]:
    score = 100
    issues = []

    meds_lower = [m.lower() for m in record.medications]
    conditions_lower = [c.lower() for c in record.conditions]

    # Flag duplicate medications (same drug name appearing more than once)
    seen = {}
    for med in record.medications:
        # Use just the first word (drug name) for duplicate detection
        drug_name = med.lower().split()[0] if med else ""
        if drug_name in seen:
            score -= 10
            issues.append(DetectedIssue(
                field="medications",
                issue=f"Possible duplicate medication entry: '{seen[drug_name]}' and '{med}'",
                severity="medium",
            ))
        else:
            seen[drug_name] = med

    return max(score, 0), issues


#  Score aggregation 

def _overall_score(breakdown: QualityBreakdown) -> int:
    """
    Weighted average of the four dimensions.
    Clinical plausibility weighted highest — a dangerous record should score low
    even if it's complete and fresh.
    """
    return round(
        0.25 * breakdown.completeness
        + 0.25 * breakdown.accuracy
        + 0.20 * breakdown.timeliness
        + 0.30 * breakdown.clinical_plausibility
    )


#  Main entry point 

async def validate(request: DataQualityRequest) -> DataQualityResponse:
    completeness_score, completeness_issues = _check_completeness(request)
    accuracy_score, accuracy_issues = _check_accuracy(request)
    timeliness_score, timeliness_issues = _check_timeliness(request)
    plausibility_score, plausibility_issues = _check_clinical_plausibility(request)

    all_issues = (
        completeness_issues
        + accuracy_issues
        + timeliness_issues
        + plausibility_issues
    )

    breakdown = QualityBreakdown(
        completeness=completeness_score,
        accuracy=accuracy_score,
        timeliness=timeliness_score,
        clinical_plausibility=plausibility_score,
    )

    overall = _overall_score(breakdown)

    # Pass the record and issues to Gemini for a plain-English summary
    ai_analysis = await get_data_quality_analysis(
        record=request.model_dump(mode="json"),
        issues=[i.model_dump() for i in all_issues],
    )

    return DataQualityResponse(
        overall_score=overall,
        breakdown=breakdown,
        issues_detected=all_issues,
        ai_analysis=ai_analysis,
    )
