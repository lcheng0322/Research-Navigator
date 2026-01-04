import json
import re
from pathlib import Path
from typing import List, Dict, Any
import logging
from ..core.config import settings
from .vector_store_service import vector_store
from .reranker_service import reranker_service

logger = logging.getLogger(__name__)

# --- Load Retrieval Strategies from Config File ---

def _load_retrieval_strategies() -> Dict[str, List[Dict[str, Any]]]:
    """
    Loads the retrieval strategies from the JSON config file.
    This makes the retrieval logic configurable without changing the code.
    """
    config_path = Path(__file__).parent.parent / "config" / "retrieval_strategies.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Retrieval strategies config file not found at {config_path}")
    
    with open(config_path, 'r') as f:
        strategies = json.load(f)
    
    # Replace placeholder names with actual collection names from settings
    # This allows the JSON to be more readable and less tied to specific variable names
    collection_map = {
        "chunks": settings.CHUNKS_COLLECTION_NAME,
        "summaries": settings.SUMMARIES_COLLECTION_NAME,
        "chapter_summaries": settings.CHAPTER_SUMMARIES_COLLECTION_NAME
    }

    # The config file defines multipliers for n_results, we calculate the count here
    # This is a placeholder, as n_results is only known at runtime. We'll apply it later.
    processed_strategies = {}
    for intent, collections in strategies.items():
        processed_strategies[intent] = [
            {"name": collection_map[coll["collection"]], "multiplier": coll["multiplier"]}
            for coll in collections
        ]
    return processed_strategies

RETRIEVAL_STRATEGIES = _load_retrieval_strategies()

def retrieve_and_rank(query_text: str, intent: str, n_results: int) -> List[Dict[str, Any]]:
    """
    Orchestrates a multi-collection, hierarchical retrieval and re-ranking process.
    The retrieval strategy is now dynamically loaded from a configuration file.
    """
    # Step 1: Define multi-layered retrieval strategy based on intent
    strategy = RETRIEVAL_STRATEGIES.get(intent, RETRIEVAL_STRATEGIES["other"])
    
    collections_to_query = [
        {"name": s["name"], "count": n_results * s["multiplier"]}
        for s in strategy
    ]

    # Step 2: Retrieve candidates from all targeted collections and merge them
    all_candidates = []
    seen_content = set()

    # --- Reference-like content detection (heuristics) ---
    ref_title_pattern = re.compile(r'^(references?|bibliography|acknowledgements?|acknowledgments?)\b', re.IGNORECASE)
    doi_pattern = re.compile(r'https?://doi\.org/\S+|\bdoi:\s*10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', re.IGNORECASE)
    author_year_dense_pattern = re.compile(r'^[\[\(]?\d+?[\]\)]?\s*[A-Z][a-z]+,\s*[A-Z]\.(?:,\s*[A-Z]\.)?\s*\(\d{4}\)', re.MULTILINE)

    def is_reference_like(meta: Dict[str, Any], text: str) -> bool:
        title_h1 = meta.get('title_h1') or meta.get('title_h2') or meta.get('title_h3') or ''
        if isinstance(title_h1, str) and ref_title_pattern.match(title_h1.strip()):
            return True
        # High DOI/URL density and sparse prose often indicates references
        indicators = 0
        lower = text.lower() if text else ''
        indicators += 1 if doi_pattern.search(text or '') else 0
        for token in ('vol.', 'pp.', 'journal', 'proceedings', 'http://', 'https://'):
            if token in lower:
                indicators += 1
        if indicators >= 2:
            return True
        # Author-year citation line at block starts
        if author_year_dense_pattern.search(text or ''):
            return True
        return False

    for collection_info in collections_to_query:
        collection_name = collection_info["name"]
        candidate_count = collection_info["count"]
        
        logger.info("Querying collection per intent", extra={"intent": intent, "collection": collection_name, "candidate_count": candidate_count})
        
        initial_results = vector_store.query(
            collection_name=collection_name,
            query_text=query_text,
            n_results=candidate_count
        )

        if not initial_results: continue

        docs_list = initial_results.get('documents')
        metadatas_list = initial_results.get('metadatas')
        distances_list = initial_results.get('distances')

        # -- ROBUSTNESS FIX: Ensure all lists are valid and non-empty before proceeding --
        if not docs_list or not metadatas_list or not distances_list:
            logger.warning("Query returned incomplete data, skipping", extra={"collection": collection_name})
            continue
            
        if not docs_list[0] or not metadatas_list[0] or not distances_list[0]:
            logger.warning("Query returned empty lists, skipping", extra={"collection": collection_name})
            continue

        docs, metadatas, distances = docs_list[0], metadatas_list[0], distances_list[0]

        for i, doc_content in enumerate(docs):
            if doc_content not in seen_content:
                seen_content.add(doc_content)
                if i < len(metadatas) and i < len(distances):
                    meta = metadatas[i]
                    # Add summary type to metadata for better context
                    meta['summary_type'] = meta.get('summary_type', 'chunk')
                    # Normalize page number to int when possible
                    raw_page = meta.get('page_number')
                    norm_page: int | None = None
                    try:
                        if raw_page is not None:
                            norm_page = int(str(raw_page).strip())
                            meta['page_number'] = norm_page  # keep metadata aligned
                    except Exception:
                        # leave as-is if not convertible
                        pass

                    # Filter out reference-like candidates
                    if is_reference_like(meta, doc_content):
                        logger.info("Filtered reference-like candidate", extra={"source": meta.get("source"), "page": meta.get("page_number")})
                        continue
                    all_candidates.append({
                        "source": meta.get("source", "Unknown"),
                        "page_number": meta.get("page_number"),
                        "content": doc_content,
                        "text": doc_content,
                        "distance": distances[i],
                        "metadata": meta # Pass full metadata to reranker
                    })

    if not all_candidates:
        return []

    # Step 3: Group by source and cap number of snippets per source to reduce duplication
    MAX_SNIPPETS_PER_SOURCE = 3
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for cand in all_candidates:
        src = cand.get("source", "Unknown")
        by_source.setdefault(src, []).append(cand)

    limited_candidates: List[Dict[str, Any]] = []
    for src, group in by_source.items():
        # Prefer closer (smaller) distances before reranking
        sorted_group = sorted(group, key=lambda x: x.get("distance", float("inf")))
        limited_candidates.extend(sorted_group[:MAX_SNIPPETS_PER_SOURCE])

    logger.info("Re-ranking candidates", extra={"count": len(limited_candidates)})
    reranked_docs = reranker_service.rerank(query=query_text, documents=limited_candidates)

    # Step 4: Return the top N results
    final_results = reranked_docs[:n_results]
    logger.info("Returning final results", extra={"count": len(final_results)})
    return final_results