"""
AI Service — Gemini integration with in-memory response caching.

Design decisions:
  - Cache key is a hash of the full prompt so identical inputs never cost a second API call.
  - Gemini is called AFTER deterministic scoring so the prompt includes our pre-analysis.
    This makes the AI's job easier and its output more consistent.
  - All Gemini calls are wrapped in try/except — if the AI fails, we return a
    graceful fallback so the endpoint still responds with deterministic results.
"""
import hashlib
import json
import logging

import google.generativeai as genai

from backend.config import settings
from backend.models.medication import PatientContext, MedicationSource

logger = logging.getLogger(__name__)

#  Gemini setup 
genai.configure(api_key=settings.gemini_api_key)
_model = genai.GenerativeModel("gemini-1.5-flash")

#  Simple in-memory cache 
# dict of { prompt_hash -> response_text }
_cache: dict[str, str] = {}


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()


async def _call_gemini(prompt: str) -> str:
    """
    Sends prompt to Gemini, returns text response.
    Checks cache first — writes to cache on success.
    Returns a fallback string if the API call fails.
    """
    cache_key = _hash_prompt(prompt)

    if cache_key in _cache:
        logger.info("Cache hit for prompt hash %s", cache_key[:8])
        return _cache[cache_key]

    try:
        response = _model.generate_content(prompt)
        text = response.text.strip()
        _cache[cache_key] = text
        return text
    except Exception as exc:
        logger.error("Gemini API error: %s", exc)
        return ""   # caller handles empty string as fallback


#  Reconciliation prompt 

def _build_reconciliation_prompt(
    patient_context: PatientContext,
    sources: list[MedicationSource],
    winner: MedicationSource,
    confidence: float,
    source_analysis: list[dict],
) -> str:
    """
    Prompt engineering approach:
      1. Give Gemini a clear role (clinical pharmacist, not a general assistant)
      2. Provide structured patient context so it can reason about clinical fit
      3. Include our pre-scored source analysis — AI should explain, not re-derive
      4. Constrain the output format strictly so we can parse it reliably
    """
    sources_text = "\n".join(
        f"  - {s.system} ({s.source_reliability} reliability, "
        f"date: {s.effective_date or 'unknown'}): {s.medication}"
        for s in sources
    )

    scoring_text = "\n".join(
        f"  - {a['system']}: composite score {a['composite_score']} "
        f"(recency={a['recency_score']}, reliability={a['reliability_score']}, "
        f"agreement={a['agreement_score']})"
        for a in source_analysis
    )

    labs_text = ""
    if patient_context.recent_labs:
        labs_text = f"Recent labs: {patient_context.recent_labs.model_dump(exclude_none=True)}"

    return f"""You are a clinical pharmacist reviewing conflicting medication records.
Your job is to explain WHY the algorithmically selected medication is correct and list actions for the care team.

PATIENT:
  Age: {patient_context.age}
  Conditions: {', '.join(patient_context.conditions) or 'None documented'}
  {labs_text}

CONFLICTING SOURCES:
{sources_text}

ALGORITHM RESULT:
  Selected medication: {winner.medication}
  Confidence score: {confidence} (0=low, 1=high)
  Source scoring breakdown:
{scoring_text}

Respond ONLY with valid JSON in this exact format (no markdown, no extra text):
{{
  "reasoning": "2-3 sentence clinical explanation of why this medication was selected, referencing the patient context",
  "recommended_actions": ["action 1", "action 2", "action 3"]
}}"""


async def get_reconciliation_reasoning(
    patient_context: PatientContext,
    sources: list[MedicationSource],
    winner: MedicationSource,
    confidence: float,
    source_analysis: list[dict],
) -> tuple[str, list[str]]:
    """
    Returns (reasoning_text, recommended_actions_list).
    Falls back to sensible defaults if Gemini is unavailable.
    """
    prompt = _build_reconciliation_prompt(
        patient_context, sources, winner, confidence, source_analysis
    )
    raw = await _call_gemini(prompt)

    if not raw:
        return _fallback_reasoning(winner, sources), _fallback_actions(sources, winner)

    try:
        # Strip any accidental markdown fences before parsing
        clean = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean)
        reasoning = parsed.get("reasoning", "")
        actions = parsed.get("recommended_actions", [])
        if reasoning and actions:
            return reasoning, actions
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Failed to parse Gemini JSON response: %s", exc)

    return _fallback_reasoning(winner, sources), _fallback_actions(sources, winner)


#  Data quality prompt 

def _build_data_quality_prompt(record: dict, issues: list[dict]) -> str:
    """
    Prompt for the data quality endpoint.
    We pass the already-detected issues to Gemini and ask for a plain-English summary.
    This avoids asking AI to re-detect things our rules already caught reliably.
    """
    issues_text = "\n".join(
        f"  - [{i['severity'].upper()}] {i['field']}: {i['issue']}"
        for i in issues
    ) or "  None detected"

    return f"""You are a health informatics specialist reviewing a patient record for data quality.

PATIENT RECORD:
{json.dumps(record, indent=2, default=str)}

ISSUES ALREADY DETECTED BY VALIDATION RULES:
{issues_text}

Write a brief (2-3 sentence) plain-English summary of the data quality problems for a clinician.
Focus on patient safety implications. Be direct and specific.
Respond with ONLY the summary text, no JSON, no headings."""


async def get_data_quality_analysis(record: dict, issues: list[dict]) -> str:
    """Returns a plain-English AI summary of data quality issues."""
    prompt = _build_data_quality_prompt(record, issues)
    raw = await _call_gemini(prompt)
    return raw or "Unable to generate AI analysis. Please review the detected issues manually."


#  Fallbacks 

def _fallback_reasoning(winner: MedicationSource, sources: list[MedicationSource]) -> str:
    return (
        f"{winner.system} was selected as the most reliable and recent source. "
        f"This record had the highest composite score across recency and source reliability. "
        f"Clinical review is recommended before making any medication changes."
    )


def _fallback_actions(sources: list[MedicationSource], winner: MedicationSource) -> list[str]:
    actions = []
    for s in sources:
        if s.system != winner.system:
            actions.append(f"Update {s.system} to reflect: {winner.medication}")
    actions.append("Verify current medication with patient at next encounter")
    return actions
