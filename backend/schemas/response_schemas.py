from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class CitationEntry(BaseModel):
    source_id: str
    source_file: Optional[str] = None
    source_key: Optional[str] = None
    doi: Optional[str] = None
    document_id: Optional[int] = None
    title: Optional[str] = None
    pages: List[int] = Field(default_factory=list)


class ReasonedAnswerModel(BaseModel):
    synthesized_answer: str
    limitations_analysis: str
    alternative_hypotheses: List[str] = Field(default_factory=list)
    confidence_score: float


class ReasonedAnswerWrapper(BaseModel):
    result: ReasonedAnswerModel
    citation_index: List[CitationEntry] = Field(default_factory=list)
    reasoning_successful: bool = True


class EvidenceAssessmentWrapper(BaseModel):
    assessment: Dict[str, Any]
    assessment_successful: bool = True


class FinalResponse(BaseModel):
    reasoned_answer: Dict[str, Any]
    query_analysis: Dict[str, Any]
    assessment: Dict[str, Any] | None
    context: List[Dict[str, Any]]


def validate_final_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Coerces and validates basic structure and types in the final response.

    - Ensures citation_index.pages are integers
    - Passes through original payload structure to avoid breaking contracts
    """
    ra = payload.get("reasoned_answer") or {}
    citation_index = ra.get("citation_index") or []
    for entry in citation_index:
        pages = entry.get("pages") or []
        normalized: List[int] = []
        for p in pages:
            try:
                normalized.append(int(str(p).strip()))
            except Exception:
                # skip non-convertible
                pass
        entry["pages"] = sorted(list(set(normalized)))
    return payload