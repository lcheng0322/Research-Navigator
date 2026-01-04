import logging
from typing import List, Dict, Any
from sentence_transformers import CrossEncoder
from ..core.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RerankerService:
    """
    A service to re-rank documents based on their relevance to a query
    using a Cross-Encoder model.
    """
    def __init__(self):
        try:
            logging.info("Initializing RerankerService...")
            # Load the Cross-Encoder model from the pre-configured model name
            self.model = CrossEncoder(settings.CROSS_ENCODER_MODEL_NAME, max_length=512)
            logging.info(f"RerankerService initialized successfully with model: {settings.CROSS_ENCODER_MODEL_NAME}")
        except Exception as e:
            logging.error(f"Failed to initialize RerankerService model: {e}", exc_info=True)
            self.model = None

    def rerank(self, query: str, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Re-ranks a list of documents against a query.

        Args:
            query: The user's search query.
            documents: A list of document dictionaries, each with a "content" key.

        Returns:
            A sorted list of the same document dictionaries, with an added "rerank_score" key.
        """
        if not self.model:
            logging.warning("Reranker model is not available. Returning documents without re-ranking.")
            return documents
        
        if not documents:
            return []

        # Create pairs of [query, document_content] for the model
        # Prefer unified 'text' field when present; fall back to 'content'
        doc_contents = [(doc.get("text") or doc.get("content", "")) for doc in documents]
        model_input = [[query, doc_content] for doc_content in doc_contents]

        logging.info(f"Re-ranking {len(documents)} documents against query: '{query}'")
        
        # Compute scores
        scores = self.model.predict(model_input)

        # Add scores to the documents and sort
        for doc, score in zip(documents, scores):
            doc["rerank_score"] = float(score)
        
        sorted_documents = sorted(documents, key=lambda x: x["rerank_score"], reverse=True)
        
        logging.info("Re-ranking complete.")
        return sorted_documents

# Create a singleton instance
reranker_service = RerankerService()