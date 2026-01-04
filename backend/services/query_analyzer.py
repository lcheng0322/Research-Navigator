import json
import logging
from typing import List, Literal
from pydantic import BaseModel, Field, ValidationError, field_validator

from .llm_service import get_llm_response

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 1. Define Pydantic models for robust data validation
class QueryAnalysisResult(BaseModel):
    """
    A Pydantic model to structure and validate the output of the query analyzer.
    """
    intent: Literal[
        "fact_checking",
        "conceptual_explanation",
        "literature_review",
        "comparison",
        "other"
    ] = Field(..., description="The user's primary intent.")

    entities: List[str] = Field(default_factory=list, description="Key scientific entities extracted from the query.")

    rewritten_query: str = Field(..., description="A clear, concise query optimized for semantic search.")

    complexity: Literal["simple", "moderate", "complex"] = Field(
        ..., description="The estimated complexity of the query."
    )

    domain: Literal[
        "Computer Science",
        "Biology",
        "Chemistry",
        "Physics",
        "Medicine",
        "Engineering",
        "General/Interdisciplinary"
    ] = Field(..., description="The scientific domain of the query.")

    @field_validator('domain', mode='before')
    @classmethod
    def normalize_domain(cls, v: str):
        """Coerce common domain variants to the allowed categories."""
        if not isinstance(v, str):
            return v
        s = v.strip().lower()
        canonical_map = {
            "computer science": "Computer Science",
            "cs": "Computer Science",
            "biology": "Biology",
            "bio": "Biology",
            "chemistry": "Chemistry",
            "physics": "Physics",
            "medicine": "Medicine",
            "medical": "Medicine",
            "engineering": "Engineering",
            "general": "General/Interdisciplinary",
            "general/interdisciplinary": "General/Interdisciplinary",
        }
        if s in canonical_map:
            return canonical_map[s]
        # Heuristics: map specialized subdomains to their general category
        if "engineering" in s:
            return "Engineering"
        if "biology" in s:
            return "Biology"
        if "chem" in s:
            return "Chemistry"
        if "physic" in s:
            return "Physics"
        if any(k in s for k in ["medicine", "medical", "clinical"]):
            return "Medicine"
        return "General/Interdisciplinary"


def analyze_query(query: str) -> QueryAnalysisResult:
    """
    Analyzes the user's query using an LLM to determine intent, extract entities,
    assess complexity, classify domain, and generate a rewritten query.

    Args:
        query: The original user query.

    Returns:
        A Pydantic model instance containing the structured analysis.
        Returns a default model instance on failure.
    """
    prompt = f'''
    Analyze the following scientific research query and return a single, valid JSON object with the following five keys: "intent", "entities", "rewritten_query", "complexity", and "domain".

    1.  "intent": Classify the user's intent. Choose ONE from:
        - "fact_checking": User is looking for a specific fact, number, or detail.
        - "conceptual_explanation": User wants an explanation of a concept, method, or theory.
        - "literature_review": User is asking for a summary or overview of research on a topic.
        - "comparison": User wants to compare two or more things.
        - "other": Any other type of query.

    2.  "entities": Extract a list of key scientific entities (e.g., chemical compounds, methods, scientific concepts, equipment).

    3.  "rewritten_query": Rephrase the original query into a clear, concise statement optimized for semantic vector search. It should be a complete sentence or question.

    4.  "complexity": Assess the query's complexity based on its specificity and the likely depth of the required answer. Choose ONE from:
        - "simple": A straightforward factual question.
        - "moderate": Requires synthesizing information from a few sources.
        - "complex": Requires deep analysis, comparison, or synthesis across multiple complex documents.

    5.  "domain": Classify the primary scientific domain of the query. Choose ONE from:
        - "Computer Science"
        - "Biology"
        - "Chemistry"
        - "Physics"
        - "Medicine"
        - "Engineering"
        - "General/Interdisciplinary"

    IMPORTANT: The value for "domain" MUST be EXACTLY one of the strings above.
    Do not invent specialized subdomains; pick the closest general category.
    For example, use "Engineering" instead of "Environmental Engineering".

    Original Query: "{query}"

    JSON Response:
    '''

    response_str = ""
    try:
        logging.info(f"Analyzing query: '{query}'")
        response_str = get_llm_response(prompt, use_reasoner=False)
        
        # The LLM might return the JSON inside a code block, so we need to clean it.
        if "```json" in response_str:
            response_str = response_str.split("```json")[1].split("```")[0]
        
        # Prefer tolerant validation: parse JSON, normalize fields if needed, then validate
        try:
            llm_json = json.loads(response_str)
        except json.JSONDecodeError:
            # Fallback to direct pydantic JSON validation (it can sometimes handle quirks)
            analysis_result = QueryAnalysisResult.model_validate_json(response_str)
            logging.info(f"Query analysis successful: {analysis_result.model_dump_json(indent=2)}")
            return analysis_result

        analysis_result = QueryAnalysisResult.model_validate(llm_json)
        logging.info(f"Query analysis successful: {analysis_result.model_dump_json(indent=2)}")
        return analysis_result

    except (json.JSONDecodeError, ValidationError) as e:
        logging.error(f"Failed to parse or validate LLM response for query analysis. Error: {e}. Response: '{response_str}'")
        # Fallback to a default structure if parsing or validation fails
        return QueryAnalysisResult(
            intent="other",
            entities=[],
            rewritten_query=query,
            complexity="moderate",  # Default complexity
            domain="General/Interdisciplinary"  # Default domain
        )
    except Exception as e:
        logging.error(f"An unexpected error occurred during query analysis: {e}", exc_info=True)
        return QueryAnalysisResult(
            intent="other",
            entities=[],
            rewritten_query=query,
            complexity="moderate",
            domain="General/Interdisciplinary"
        )
