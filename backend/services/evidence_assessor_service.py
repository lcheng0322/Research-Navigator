import logging
import json
from typing import List, Dict, Any, Literal
from pydantic import BaseModel, Field, ValidationError

from .llm_service import get_llm_response

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 1. Define Pydantic models for robust, structured output
class SourceQuality(BaseModel):
    source_id: str = Field(..., description="The identifier for the source, e.g., 'Source_1'.")
    relevance: int = Field(..., description="Relevance to the query (1-5).", ge=1, le=5)
    trustworthiness: int = Field(..., description="Trustworthiness of the content (1-5).", ge=1, le=5)
    timeliness: int = Field(..., description="Timeliness based on publication year (1-5).", ge=1, le=5)
    authority: int = Field(..., description="Authority of the source/venue (1-5).", ge=1, le=5)
    justification: str = Field(..., description="A brief justification for the scores.")

class EvidenceAssessment(BaseModel):
    overall_consistency_summary: str = Field(..., description="A brief summary of overall consistency.")
    consistent_points: List[str] = Field(default_factory=list, description="Key points supported by multiple sources.")
    conflicting_points: List[str] = Field(default_factory=list, description="Key conflicts between sources.")
    source_quality_assessments: List[SourceQuality] = Field(..., description="Individual quality assessment for each source.")

class EvidenceAssessorService:
    """
    A service to assess the quality and consistency of a set of evidence documents.
    """

    def assess_evidence(self, query: str, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Assesses the quality and consistency of a list of documents in relation to a query.

        Args:
            query: The original user query.
            documents: A list of document dictionaries, each containing text and metadata.

        Returns:
            A dictionary containing the full, structured assessment.
        """
        if not documents:
            return {"error": "No documents provided for assessment."}

        logging.info(f"Assessing evidence quality for {len(documents)} documents for query: '{query}'")

        # 2. Prepare the context string: GROUP by unique source and limit snippets per source
        # This prevents multiple Source_n labels for the same paper and aligns with reasoning output.
        def _normalize_source_key(d: Dict[str, Any]) -> str:
            md = d.get('metadata', {})
            # Prefer explicit source; then DOI/document_id/title as fallbacks
            return (
                d.get('source')
                or md.get('source')
                or md.get('doi')
                or (str(md.get('document_id')) if md.get('document_id') is not None else None)
                or md.get('title')
                or 'Unknown'
            )

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for d in documents:
            key = _normalize_source_key(d)
            grouped.setdefault(key, []).append(d)

        MAX_SNIPPETS_PER_SOURCE = 3
        context_parts: List[str] = []
        for i, (source_key, group_docs) in enumerate(grouped.items(), 1):
            source_id = f"Source_{i}"
            # Representative metadata for the source
            rep_md = group_docs[0].get('metadata', {})
            pub_year = rep_md.get('publication_year', 'N/A')
            source_venue = rep_md.get('journal') or rep_md.get('source') or rep_md.get('venue') or 'Unknown'
            authors = rep_md.get('authors', 'N/A')
            # Collect up to N snippets with page numbers
            snippets: List[str] = []
            for d in group_docs[:MAX_SNIPPETS_PER_SOURCE]:
                md = d.get('metadata', {})
                page = md.get('page_number')
                raw = (d.get('text') or d.get('content') or '')
                snippet = raw[:1000]
                if page is not None:
                    snippet = f"[Page {page}] {snippet}"
                snippets.append(snippet if snippet else 'No content available')

            # Build a concise, merged content block for the source
            merged_content = "\n---\n".join(snippets) if snippets else 'No content available'

            context_parts.append(
                f"""--- {source_id} ---\n- Content Snippets (merged):\n{merged_content}\n- Metadata:\n  - Publication Year: {pub_year}\n  - Source Venue: {source_venue}\n  - Authors: {authors}\n"""
            )

        context_str = "\n\n".join(context_parts)

        # 3. Update the prompt to include new assessment dimensions
        assessment_prompt = f'''
        You are a meticulous and critical research analyst. Your task is to evaluate the quality and consistency of the following set of information sources in relation to the user's query.

        USER QUERY: "{query}"

        SOURCES (with metadata):
        {context_str}

        INSTRUCTIONS:
        Your response MUST be a single, valid JSON object. Analyze the sources and provide the following:

        1.  **Source Quality Assessment**: For EACH source, provide a quality score on a scale of 1 to 5 for the following dimensions. Provide a brief justification for your scores.
            - `relevance`: How relevant is the content to the user's query?
            - `trustworthiness`: How credible and factually sound does the content appear?
            - `timeliness`: How timely is the information, considering its publication year? (5 = very recent, 1 = very old).
            - `authority`: How authoritative is the source venue (e.g., top-tier journal vs. preprint)?

        2.  **Consistency Analysis**:
            - `overall_consistency_summary`: Briefly state whether the sources are generally consistent, conflicting, or offer different perspectives.
            - `consistent_points`: List the main arguments or facts supported by multiple sources. Cite sources (e.g., [Source_1, Source_3]).
            - `conflicting_points`: List any significant contradictions between sources. Cite sources (e.g., [Source_2 vs. Source_4]). If none, use an empty list.

        JSON OUTPUT FORMAT:
        Respond with a JSON object that strictly follows this Pydantic model:
        {{ 
            "overall_consistency_summary": "<summary_string>",
            "consistent_points": ["<point_1>", "<point_2>"],
            "conflicting_points": ["<conflict_1>"],
            "source_quality_assessments": [
                {{
                    "source_id": "Source_1",
                    "relevance": <int>,
                    "trustworthiness": <int>,
                    "timeliness": <int>,
                    "authority": <int>,
                    "justification": "<text>"
                }},
                ...
            ]
        }}
        '''

        raw_response = ""
        try:
            raw_response = get_llm_response(assessment_prompt, json_mode=True, use_reasoner=False)
            
            # 4. Use Pydantic for validation
            assessment_result = EvidenceAssessment.model_validate_json(raw_response)

            # --- Post-process: Align overall consistency summary with source count ---
            try:
                src_count = len(assessment_result.source_quality_assessments or [])
                if src_count <= 1:
                    # Override summary for single-source assessments
                    assessment_result.overall_consistency_summary = (
                        "Only a single source was assessed; cross-source consistency cannot be determined."
                    )
            except Exception:
                # Non-blocking; keep original if any issue
                pass

            logging.info("Successfully assessed evidence quality and consistency.")
            return {"assessment": assessment_result.model_dump(), "assessment_successful": True}

        except (json.JSONDecodeError, ValidationError) as e:
            logging.error(f"Failed to parse or validate LLM response for evidence assessment. Error: {e}. Raw response was: {raw_response}")
            return {"error": f"Failed to parse or validate LLM response. Details: {e}", "assessment_successful": False}
        except Exception as e:
            logging.error(f"An unexpected error occurred during evidence assessment: {e}", exc_info=True)
            return {"error": f"An unexpected error occurred: {e}", "assessment_successful": False}

# Singleton instance
evidence_assessor_service = EvidenceAssessorService()
