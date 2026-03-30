"""
Unit tests for the reconciliation service.
These test the deterministic logic only — no AI calls are made.
Run with: pytest backend/tests/test_reconciliation.py -v
"""
import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from backend.models.medication import MedicationSource, PatientContext, MedicationReconcileRequest
from backend.services.reconciliation import (
    _normalise_medication,
    _recency_score,
    _reliability_score,
    _agreement_score,
    score_source,
    _compute_confidence,
    _clinical_safety_check,
    reconcile,
)


#  Fixtures 

def make_source(
    system="Test System",
    medication="Metformin 500mg",
    days_ago=30,
    reliability="high",
) -> MedicationSource:
    return MedicationSource(
        system=system,
        medication=medication,
        last_updated=date.today() - timedelta(days=days_ago),
        source_reliability=reliability,
    )


def make_request(sources: list[MedicationSource]) -> MedicationReconcileRequest:
    return MedicationReconcileRequest(
        patient_context=PatientContext(age=65, conditions=["Type 2 Diabetes"]),
        sources=sources,
    )


#  _normalise_medication 

def test_normalise_strips_case_and_whitespace():
    assert _normalise_medication("  Metformin  500mg ") == "metformin 500mg"


def test_normalise_collapses_internal_spaces():
    assert _normalise_medication("Aspirin  81mg  Daily") == "aspirin 81mg daily"


#  _recency_score 

def test_recency_today_is_1():
    source = make_source(days_ago=0)
    assert _recency_score(source) == 1.0


def test_recency_missing_date_is_penalised():
    source = MedicationSource(
        system="X", medication="Drug A", source_reliability="high"
    )
    assert _recency_score(source) == 0.3


def test_recency_very_old_hits_floor():
    source = make_source(days_ago=400)
    assert _recency_score(source) == 0.1


def test_recency_decays_linearly():
    recent = make_source(days_ago=10)
    older = make_source(days_ago=200)
    assert _recency_score(recent) > _recency_score(older)


#  _reliability_score 

def test_reliability_high():
    source = make_source(reliability="high")
    assert _reliability_score(source) == 1.0


def test_reliability_medium():
    source = make_source(reliability="medium")
    assert _reliability_score(source) == 0.6


def test_reliability_low():
    source = make_source(reliability="low")
    assert _reliability_score(source) == 0.3


#  _agreement_score 

def test_agreement_all_agree():
    sources = [
        make_source(system="A", medication="Metformin 500mg"),
        make_source(system="B", medication="Metformin 500mg"),
        make_source(system="C", medication="Metformin 500mg"),
    ]
    assert _agreement_score(sources[0], sources) == 1.0


def test_agreement_no_others_agree():
    sources = [
        make_source(system="A", medication="Metformin 500mg"),
        make_source(system="B", medication="Metformin 1000mg"),
        make_source(system="C", medication="Metformin 250mg"),
    ]
    assert _agreement_score(sources[0], sources) == 0.0


def test_agreement_partial():
    sources = [
        make_source(system="A", medication="Metformin 500mg"),
        make_source(system="B", medication="Metformin 500mg"),
        make_source(system="C", medication="Metformin 1000mg"),
    ]
    score = _agreement_score(sources[0], sources)
    assert 0.0 < score < 1.0


#  _clinical_safety_check 

def test_safety_passes_normal_case():
    sources = [
        make_source(system="A", medication="Metformin 500mg"),
        make_source(system="B", medication="Metformin 500mg"),
    ]
    assert _clinical_safety_check("Metformin 500mg", sources) == "PASSED"



def test_safety_flags_total_disagreement():
    sources = [
        make_source(system="A", medication="Drug A"),
        make_source(system="B", medication="Drug B"),
        make_source(system="C", medication="Drug C"),
    ]
    assert _clinical_safety_check("Drug A", sources) == "REVIEW_REQUIRED"


#  Integration: reconcile picks most recent high-reliability source 

@pytest.mark.asyncio
async def test_reconcile_picks_winner_correctly():
    sources = [
        make_source(system="Old Hospital", medication="Metformin 1000mg", days_ago=300, reliability="high"),
        make_source(system="Recent Clinic", medication="Metformin 500mg", days_ago=10, reliability="high"),
        make_source(system="Pharmacy", medication="Metformin 1000mg", days_ago=5, reliability="medium"),
    ]
    request = make_request(sources)

    # Mock AI call so test doesn't hit the network
    with patch(
        "backend.services.reconciliation.get_reconciliation_reasoning",
        new=AsyncMock(return_value=("Test reasoning", ["Action 1"])),
    ):
        result = await reconcile(request)

    # Recent Clinic is most recent + high reliability, should win
    assert "500mg" in result.reconciled_medication
    assert 0.0 <= result.confidence_score <= 1.0
    assert result.reasoning == "Test reasoning"
    assert result.clinical_safety_check in ("PASSED", "REVIEW_REQUIRED")
