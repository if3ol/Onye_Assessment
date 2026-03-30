"""
Medication Reconciliation Service

Algorithm:
  1. Score every source on three axes: recency, reliability, agreement
  2. Identify the winning medication candidate
  3. Compute a composite confidence score
  4. Pass the pre-analysis to Gemini for clinical reasoning
  5. Return the combined result
"""
from datetime import date
from collections import Counter

from backend.models.medication import (
    MedicationReconcileRequest,
    MedicationReconcileResponse,
    MedicationSource,
)
from backend.services.ai_service import get_reconciliation_reasoning


#  Weights 
RELIABILITY_WEIGHTS = {"high": 1.0, "medium": 0.6, "low": 0.3}
MAX_RECENCY_DAYS = 365


#  Helpers 

def _normalise_medication(name: str) -> str:
    """Lowercase + collapse whitespace. 'Metformin 500mg  Daily' -> 'metformin 500mg daily'"""
    return " ".join(name.lower().split())


def _recency_score(source: MedicationSource) -> float:
    """
    0.0-1.0. Missing date -> 0.3 penalty. Linear decay over MAX_RECENCY_DAYS.
    Floor of 0.1 — old data still has some signal value.
    """
    effective_date = source.effective_date
    if effective_date is None:
        return 0.3
    days_old = (date.today() - effective_date).days
    if days_old <= 0:
        return 1.0
    if days_old >= MAX_RECENCY_DAYS:
        return 0.1
    return 1.0 - (0.9 * days_old / MAX_RECENCY_DAYS)


def _reliability_score(source: MedicationSource) -> float:
    return RELIABILITY_WEIGHTS.get(source.source_reliability, 0.3)


def _agreement_score(source: MedicationSource, all_sources: list) -> float:
    """Fraction of OTHER sources that agree with this medication."""
    this_med = _normalise_medication(source.medication)
    agreeing = sum(1 for s in all_sources if _normalise_medication(s.medication) == this_med)
    return (agreeing - 1) / max(len(all_sources) - 1, 1)


def score_source(source: MedicationSource, all_sources: list) -> float:
    """
    Composite score: recency 40%, reliability 40%, agreement 20%.
    Recency and reliability are the primary signals; agreement breaks ties.
    """
    return (
        0.40 * _recency_score(source)
        + 0.40 * _reliability_score(source)
        + 0.20 * _agreement_score(source, all_sources)
    )


def _build_source_analysis(sources: list, scores: list) -> list:
    analysis = []
    for source, score in zip(sources, scores):
        analysis.append({
            "system": source.system,
            "medication": source.medication,
            "effective_date": str(source.effective_date) if source.effective_date else "unknown",
            "source_reliability": source.source_reliability,
            "composite_score": round(score, 3),
            "recency_score": round(_recency_score(source), 3),
            "reliability_score": round(_reliability_score(source), 3),
            "agreement_score": round(_agreement_score(source, sources), 3),
        })
    return sorted(analysis, key=lambda x: x["composite_score"], reverse=True)


def _compute_confidence(winner_score: float, all_scores: list, winner_med: str, all_sources: list) -> float:
    """
    Confidence = blend of winner's raw score, margin over runner-up, and source agreement ratio.
    Clamped to 0.99 — never claim 100% confidence in automated reconciliation.
    """
    sorted_scores = sorted(all_scores, reverse=True)
    runner_up = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
    margin = winner_score - runner_up
    agreement_ratio = sum(
        1 for s in all_sources
        if _normalise_medication(s.medication) == _normalise_medication(winner_med)
    ) / len(all_sources)

    raw = (0.5 * winner_score) + (0.3 * margin) + (0.2 * agreement_ratio)
    return min(round(raw, 2), 0.99)


def _clinical_safety_check(winner_med: str, all_sources: list) -> str:
    """
    Flags high-risk medications or total disagreement for mandatory human review.
    A production system would query a drug database (e.g. RxNorm, OpenFDA).
    """
    normalised = _normalise_medication(winner_med)
    unique_meds = {_normalise_medication(s.medication) for s in all_sources}

    if len(unique_meds) == len(all_sources):
        return "REVIEW_REQUIRED"
    return "PASSED"


#  Main entry point 

async def reconcile(request: MedicationReconcileRequest) -> MedicationReconcileResponse:
    sources = request.sources

    scores = [score_source(s, sources) for s in sources]
    best_idx = scores.index(max(scores))
    winner = sources[best_idx]

    confidence = _compute_confidence(
        winner_score=scores[best_idx],
        all_scores=scores,
        winner_med=winner.medication,
        all_sources=sources,
    )

    source_analysis = _build_source_analysis(sources, scores)
    safety = _clinical_safety_check(winner.medication, sources)

    reasoning, recommended_actions = await get_reconciliation_reasoning(
        patient_context=request.patient_context,
        sources=sources,
        winner=winner,
        confidence=confidence,
        source_analysis=source_analysis,
    )

    return MedicationReconcileResponse(
        reconciled_medication=winner.medication,
        confidence_score=confidence,
        reasoning=reasoning,
        recommended_actions=recommended_actions,
        clinical_safety_check=safety,
        source_analysis=source_analysis,
    )
