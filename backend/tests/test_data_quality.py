"""
Unit tests for the data quality validation service.
Run with: pytest backend/tests/test_data_quality.py -v
"""
import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from backend.models.data_quality import (
    DataQualityRequest,
    Demographics,
    VitalSigns,
)
from backend.services.data_quality import (
    _check_completeness,
    _check_accuracy,
    _check_timeliness,
    _check_clinical_plausibility,
    _parse_blood_pressure,
    _overall_score,
    validate,
    QualityBreakdown,
)


#  Fixtures 

def full_record(**overrides) -> DataQualityRequest:
    """A complete, valid patient record. Override fields to test specific cases."""
    defaults = dict(
        demographics=Demographics(name="Jane Doe", dob=date(1960, 5, 10), gender="F"),
        medications=["Metformin 500mg", "Lisinopril 10mg"],
        allergies=["Penicillin"],
        conditions=["Type 2 Diabetes", "Hypertension"],
        vital_signs=VitalSigns(blood_pressure="128/82", heart_rate=72),
        last_updated=date.today() - timedelta(days=30),
    )
    defaults.update(overrides)
    return DataQualityRequest(**defaults)


#  _parse_blood_pressure 

def test_parse_bp_valid():
    assert _parse_blood_pressure("120/80") == (120, 80)

def test_parse_bp_invalid_format():
    assert _parse_blood_pressure("120-80") is None

def test_parse_bp_empty_string():
    assert _parse_blood_pressure("") is None

def test_parse_bp_non_numeric():
    assert _parse_blood_pressure("abc/def") is None


#  Completeness 

def test_completeness_perfect_record():
    score, issues = _check_completeness(full_record())
    assert score == 100
    assert issues == []

def test_completeness_missing_allergies():
    score, issues = _check_completeness(full_record(allergies=[]))
    assert score < 100
    fields = [i.field for i in issues]
    assert "allergies" in fields

def test_completeness_missing_demographics():
    score, issues = _check_completeness(full_record(demographics=None))
    assert score <= 80
    assert any(i.field == "demographics" for i in issues)

def test_completeness_missing_medications():
    score, issues = _check_completeness(full_record(medications=[]))
    assert any(i.field == "medications" for i in issues)

def test_completeness_missing_vitals():
    score, issues = _check_completeness(full_record(vital_signs=None))
    assert any(i.field == "vital_signs" for i in issues)


#  Accuracy 

def test_accuracy_normal_vitals():
    score, issues = _check_accuracy(full_record())
    assert score == 100
    assert issues == []

def test_accuracy_implausible_bp_high():
    record = full_record(vital_signs=VitalSigns(blood_pressure="340/180", heart_rate=72))
    score, issues = _check_accuracy(record)
    assert score < 100
    assert any("blood_pressure" in i.field for i in issues)
    assert any(i.severity == "high" for i in issues)

def test_accuracy_diastolic_greater_than_systolic():
    record = full_record(vital_signs=VitalSigns(blood_pressure="80/120"))
    score, issues = _check_accuracy(record)
    assert any("impossible" in i.issue.lower() for i in issues)

def test_accuracy_implausible_heart_rate():
    record = full_record(vital_signs=VitalSigns(blood_pressure="120/80", heart_rate=5))
    score, issues = _check_accuracy(record)
    assert any("heart_rate" in i.field for i in issues)

def test_accuracy_valid_bp_no_issues():
    record = full_record(vital_signs=VitalSigns(blood_pressure="118/76", heart_rate=68))
    score, issues = _check_accuracy(record)
    assert score == 100


#  Timeliness 

def test_timeliness_recent_record():
    score, issues = _check_timeliness(full_record(last_updated=date.today() - timedelta(days=10)))
    assert score == 100
    assert issues == []

def test_timeliness_old_record_deducted():
    score, issues = _check_timeliness(full_record(last_updated=date.today() - timedelta(days=400)))
    assert score < 100
    assert any(i.severity == "high" for i in issues)

def test_timeliness_missing_date():
    score, issues = _check_timeliness(full_record(last_updated=None))
    assert score < 100
    assert any(i.field == "last_updated" for i in issues)

def test_timeliness_medium_old():
    score, issues = _check_timeliness(full_record(last_updated=date.today() - timedelta(days=200)))
    assert score < 100
    assert any(i.severity == "medium" for i in issues)


#  Clinical plausibility 

def test_plausibility_no_issues():
    score, issues = _check_clinical_plausibility(full_record())
    assert score == 100
    assert issues == []

def test_plausibility_duplicate_medication():
    record = full_record(medications=["Metformin 500mg", "Metformin 1000mg"])
    score, issues = _check_clinical_plausibility(record)
    assert any("duplicate" in i.issue.lower() for i in issues)



#  Overall score weighting 

def test_overall_score_perfect():
    breakdown = QualityBreakdown(
        completeness=100, accuracy=100, timeliness=100, clinical_plausibility=100
    )
    assert _overall_score(breakdown) == 100

def test_overall_score_zero_plausibility_drags_score_down():
    """Clinical plausibility has highest weight (30%) — a zero should hurt the most."""
    breakdown_bad_plausibility = QualityBreakdown(
        completeness=100, accuracy=100, timeliness=100, clinical_plausibility=0
    )
    breakdown_bad_timeliness = QualityBreakdown(
        completeness=100, accuracy=100, timeliness=0, clinical_plausibility=100
    )
    assert _overall_score(breakdown_bad_plausibility) < _overall_score(breakdown_bad_timeliness)


#  Integration 

@pytest.mark.asyncio
async def test_validate_returns_correct_structure():
    record = full_record(
        vital_signs=VitalSigns(blood_pressure="340/180", heart_rate=72),
        allergies=[],
        last_updated=date.today() - timedelta(days=400),
    )
    with patch(
        "backend.services.data_quality.get_data_quality_analysis",
        new=AsyncMock(return_value="AI analysis placeholder"),
    ):
        result = await validate(record)

    assert 0 <= result.overall_score <= 100
    assert len(result.issues_detected) > 0
    assert result.ai_analysis == "AI analysis placeholder"
    high_severity = [i for i in result.issues_detected if i.severity == "high"]
    assert len(high_severity) > 0
