import logging
import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from .llm_service import get_llm_response

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 1. Pydantic Models for structured and validated output

class ReasonedAnswer(BaseModel):
    synthesized_answer: str
    limitations_analysis: str
    alternative_hypotheses: List[str]
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="The model's confidence in its answer, from 0.0 to 1.0.")

class ReasoningEngineService:
    """
    A service to generate a reasoned answer using a multi-step, chain-of-thought process.
    """

    def _format_context(self, evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Formats evidence into a prompt-ready context and builds a citation index.

        Returns a dict with:
        - context_str: merged, labeled context grouped by unique source
        - citation_index: mapping of Source_n -> source metadata and pages
        """
        def _normalize_source_key(d: Dict[str, Any]) -> str:
            md = d.get('metadata', {})
            return (
                md.get('source')
                or md.get('doi')
                or (str(md.get('document_id')) if md.get('document_id') is not None else None)
                or md.get('title')
                or 'Unknown'
            )

        # Group docs by normalized source key
        grouped_docs: Dict[str, List[Dict[str, Any]]] = {}
        for doc in evidence:
            key = _normalize_source_key(doc)
            grouped_docs.setdefault(key, []).append(doc)

        context_parts: List[str] = []
        citation_index: List[Dict[str, Any]] = []

        for i, (source_key, docs) in enumerate(grouped_docs.items(), 1):
            source_id = f"Source_{i}"
            # Representative metadata
            rep_md = docs[0].get('metadata', {})
            source_file = rep_md.get('source', 'Unknown')
            doi = rep_md.get('doi')
            document_id = rep_md.get('document_id')
            title = rep_md.get('title')
            # Collect snippets and pages
            snippets: List[str] = []
            pages: List[str] = []
            for d in docs[:3]:  # limit to 3 snippets per source in context
                md = d.get('metadata', {})
                raw_page = md.get('page_number')
                page_int = None
                try:
                    if raw_page is not None:
                        page_int = int(str(raw_page).strip())
                except Exception:
                    page_int = None
                raw = (d.get('text') or d.get('content') or '')
                snippet = raw[:1000]
                if page_int is not None:
                    snippets.append(f"[Page {page_int}]\n{snippet}")
                    pages.append(page_int)
                else:
                    snippets.append(snippet)

            merged = "\n---\n".join(snippets) if snippets else 'No content available'
            context_parts.append(f"--- {source_id} ({source_file}) ---\n{merged}\n")

            citation_index.append({
                "source_id": source_id,
                "source_file": source_file,
                "source_key": source_key,
                "doi": doi,
                "document_id": document_id,
                "title": title,
                "pages": sorted(list(set(pages)))
            })

        return {
            "context_str": "\n".join(context_parts),
            "citation_index": citation_index
        }

    def _step_1_synthesize_answer(self, query: str, context_str: str) -> str:
        """First step: Synthesize a coherent answer from the evidence."""
        logging.info("Reasoning Step 1: Synthesizing initial answer...")
        prompt = f'''
        You are an expert scientific analyst. Based ONLY on the provided evidence, construct a comprehensive and neutral answer to the user's query.
        You MUST cite the sources you use for each piece of information with source ID AND page numbers when available.
        Use this format: [Source_1, Page 3] or for multiple pages [Source_1, Pages 3–4]; for multiple sources join with commas: [Source_1, Page 3; Source_2, Page 5].
        
        USER QUERY: "{query}"
        PROVIDED EVIDENCE:
        {context_str}
        
        Synthesized Answer:
        '''
        return get_llm_response(prompt, use_reasoner=False)

    def _step_2_analyze_limitations(self, query: str, context_str: str, synthesized_answer: str) -> str:
        """Second step: Analyze the limitations of the evidence and the synthesized answer."""
        logging.info("Reasoning Step 2: Analyzing limitations...")
        prompt = f'''
        You are a critical reviewer. Given the user's query, the evidence, and a synthesized answer, critically evaluate the limitations.
        Consider: Does the evidence fully answer the query? Are there gaps, biases, or a lack of diversity in the sources? What cannot be concluded?

        USER QUERY: "{query}"
        PROVIDED EVIDENCE:
        {context_str}
        SYNTHESIZED ANSWER:
        {synthesized_answer}

        Limitations Analysis:
        '''
        return get_llm_response(prompt, use_reasoner=False)

    def _step_3_propose_alternatives(self, limitations_analysis: str) -> List[str]:
        """Third step: Propose alternative hypotheses based on the limitations."""
        logging.info("Reasoning Step 3: Proposing alternatives...")
        prompt = f'''
        Based on the following limitations analysis, suggest one or two plausible alternative hypotheses or explanations.
        If the analysis indicates no room for alternatives, return an empty list.

        LIMITATIONS ANALYSIS:
        {limitations_analysis}

        Respond with a JSON object: {{"alternative_hypotheses": ["<hypothesis_1>", "<hypothesis_2>"]}}
        '''
        response_str = get_llm_response(prompt, json_mode=True, use_reasoner=False)
        return json.loads(response_str).get("alternative_hypotheses", [])

    # Temporary knowledge graph feature removed per updated requirements

    def _step_5_evaluate_confidence(self, synthesized_answer: str, limitations_analysis: str) -> float:
        """Fifth step: Evaluate the confidence in the final answer."""
        logging.info("Reasoning Step 5: Evaluating confidence score...")
        prompt = f'''
        Given the following synthesized answer and its limitations analysis, provide a confidence score between 0.0 and 1.0.
        A high score (e.g., 0.9) means the answer is well-supported and has few limitations. A low score (e.g., 0.4) means it has significant limitations.

        ANSWER:
        {synthesized_answer}

        LIMITATIONS:
        {limitations_analysis}

        Respond with a JSON object: {{"confidence_score": <float>}}
        '''
        response_str = get_llm_response(prompt, json_mode=True, use_reasoner=False)
        return json.loads(response_str).get("confidence_score", 0.5)

    def generate_reasoned_answer(self, query: str, evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generates a comprehensive, reasoned answer using a multi-step, chain-of-thought process.
        """
        if not evidence:
            return {"error": "No evidence provided to construct an answer."}

        logging.info(f"Generating reasoned answer for query: '{query}' from {len(evidence)} pieces of evidence.")
        ctx = self._format_context(evidence)
        context_str = ctx["context_str"]
        citation_index = ctx["citation_index"]

        try:
            # Execute the chain of thought
            answer = self._step_1_synthesize_answer(query, context_str)
            limitations = self._step_2_analyze_limitations(query, context_str, answer)
            alternatives = self._step_3_propose_alternatives(limitations)
            confidence = self._step_5_evaluate_confidence(answer, limitations)

            # Assemble the final validated result
            final_result = ReasonedAnswer(
                synthesized_answer=answer,
                limitations_analysis=limitations,
                alternative_hypotheses=alternatives,
                confidence_score=confidence
            )
            
            logging.info("Successfully generated full reasoned answer.")
            # Attach citation index so frontend can map Source_n to actual files and pages
            return {"result": final_result.model_dump(), "citation_index": citation_index, "reasoning_successful": True}

        except Exception as e:
            logging.error(f"A failure occurred in the reasoning chain: {e}", exc_info=True)
            return {"error": f"An error occurred during the reasoning process: {e}", "reasoning_successful": False}

# Singleton instance
reasoning_engine_service = ReasoningEngineService()
