import chromadb
from sentence_transformers import SentenceTransformer
from typing import Any, cast, List, Dict
import logging
from chromadb.types import Metadata

from ..core.config import settings

logger = logging.getLogger(__name__)

def _sanitize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitizes a metadata dictionary to ensure all values are of a type
    that ChromaDB can ingest (str, int, float, bool).
    """
    sanitized = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
        elif value is not None:
            # If the value is not a supported type but is not None, convert it to a string.
            sanitized[key] = str(value)
        # If value is None, it is implicitly dropped.
    return sanitized

class VectorStoreService:
    """
    A service to manage multiple vector database collections in ChromaDB.
    """
    def __init__(self):
        logger.info("Initializing VectorStoreService...")
        self.embedding_model = self._load_embedding_model()
        self.db_client = chromadb.PersistentClient(path=str(settings.CHROMA_PERSIST_DIR))
        
        # Get or create multiple collections for hierarchical search
        # Use the full collection names from config as keys for consistency
        self.collections = {
            settings.CHUNKS_COLLECTION_NAME: self.db_client.get_or_create_collection(name=settings.CHUNKS_COLLECTION_NAME),
            settings.SUMMARIES_COLLECTION_NAME: self.db_client.get_or_create_collection(name=settings.SUMMARIES_COLLECTION_NAME),
            settings.CHAPTER_SUMMARIES_COLLECTION_NAME: self.db_client.get_or_create_collection(name=settings.CHAPTER_SUMMARIES_COLLECTION_NAME)
        }
        logger.info("VectorStoreService initialized successfully", extra={"collections": list(self.collections.keys())})

    @staticmethod
    def _load_embedding_model():
        """Load the SentenceTransformer model, preferring local cache to avoid HF Hub HTTP probes."""
        try:
            logger.info("Loading embedding model from local cache...")
            return SentenceTransformer(settings.EMBEDDING_MODEL_NAME, local_files_only=True)
        except Exception:
            logger.info("Model not found locally, downloading from HuggingFace Hub...")
            return SentenceTransformer(settings.EMBEDDING_MODEL_NAME)

    def add_texts(self, texts: list[str], metadatas: list[dict[str, Any]] | None, collection_name: str):
        """
        Embeds texts and adds them to the specified vector store collection.
        """
        if collection_name not in self.collections:
            raise ValueError(f"Collection '{collection_name}' not found.")
        
        collection = self.collections[collection_name]

        if not texts:
            logger.info("No texts to add", extra={"collection": collection_name})
            return

        # --- ROBUSTNESS FIX: Sanitize metadata before processing ---
        sanitized_metadatas: List[Metadata] = []
        if metadatas:
            for meta in metadatas:
                sanitized_metadatas.append(_sanitize_metadata(meta))
        else:
            # If no metadata is provided, create a list of empty dicts as required by ChromaDB
            sanitized_metadatas = [{} for _ in texts]

        logger.info("Generating embeddings", extra={"collection": collection_name, "count": len(texts)})
        embeddings = self.embedding_model.encode(texts, show_progress_bar=True)
        
        start_id = collection.count()
        # Prefix IDs with collection name to ensure global uniqueness
        ids = [f"{collection_name}_{i}" for i in range(start_id, start_id + len(texts))]

        logger.info("Adding chunks to collection", extra={"collection": collection.name, "count": len(texts)})
        collection.add(
            embeddings=embeddings.tolist(),
            documents=texts,
            metadatas=sanitized_metadatas, # Use the sanitized metadata
            ids=ids
        )
        logger.info("Successfully added texts", extra={"collection": collection_name})

    def query(self, query_text: str, n_results: int, collection_name: str) -> dict[str, Any]:
        """
        Queries a specific collection, performs deduplication, and returns unique documents.
        """
        if collection_name not in self.collections:
            raise ValueError(f"Collection '{collection_name}' not found.")
        
        collection = self.collections[collection_name]
        
        logger.info("Querying collection", extra={"collection": collection_name, "query": query_text})
        query_embedding = self.embedding_model.encode(query_text).tolist()
        
        # Query for more results to have a buffer for deduplication
        query_n_results = n_results * 2
        
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=query_n_results,
            include=["documents", "metadatas", "distances"]
        )
        
        # Safely extract documents and metadatas, handling potential None values from ChromaDB query result
        documents_list = results.get('documents')
        raw_docs = documents_list[0] if documents_list else []
        
        metadatas_list = results.get('metadatas')
        raw_metadatas = metadatas_list[0] if metadatas_list else []
        
        if not raw_docs:
            logger.info("Found 0 relevant documents", extra={"collection": collection_name})
            return cast(dict[str, Any], cast(object, results))

        unique_docs = []
        unique_metadatas = []
        seen_docs = set()
        
        for doc, meta in zip(raw_docs, raw_metadatas):
            # Check for document content uniqueness
            if doc not in seen_docs:
                unique_docs.append(doc)
                unique_metadatas.append(meta)
                seen_docs.add(doc)
            
            # Stop once we have enough unique results
            if len(unique_docs) >= n_results:
                break
        
        # Reconstruct the result dictionary in the same format as ChromaDB returns it
        # to ensure compatibility with downstream processing in api/routes.py
        unique_results = {
            'ids': results.get('ids'), # Pass along original data if needed, though not used
            'distances': results.get('distances'),
            'metadatas': [unique_metadatas],
            'embeddings': None, # Embeddings are not used downstream
            'documents': [unique_docs],
            'uris': results.get('uris'),
            'data': results.get('data')
        }
        
        logger.info("Deduplication complete", extra={"unique_docs": len(unique_docs), "collection": collection_name})
        return unique_results

    def get_all_documents(self, collection_name: str) -> List[Dict[str, Any]]:
        """
        Retrieves all documents and their metadatas from a specified collection.
        This is useful for tasks that need to process the entire dataset, like topic modeling.
        """
        if collection_name not in self.collections:
            raise ValueError(f"Collection '{collection_name}' not found.")
        
        collection = self.collections[collection_name]
        
        logger.info("Fetching all documents", extra={"collection": collection_name})
        
        # .get() without IDs or a where clause retrieves all records.
        # We include metadatas as they are often needed alongside the text.
        results = collection.get(include=["documents", "metadatas"])
        
        # The result from .get() is a dictionary with keys 'ids', 'embeddings', 'documents', 'metadatas'.
        # We want to return a list of dictionaries, each representing a document.
        documents = results.get('documents', [])
        metadatas = results.get('metadatas', [])
        
        if not documents:
            return []
            
        # Combine documents and metadatas into a more usable list of dicts
        combined_results = []
        for i, doc_text in enumerate(documents):
            meta = metadatas[i] if metadatas and i < len(metadatas) else {}
            combined_results.append({
                "text": doc_text,
                "metadata": meta
            })
            
        logger.info("Fetch complete", extra={"collection": collection_name, "count": len(combined_results)})
        return combined_results

    def delete_by_document_id(self, document_id: int):
        """
        Deletes all vectors associated with a given document_id from all collections.
        Raises an exception if any deletion fails to ensure transactional integrity.
        """
        logger.info("Deleting vectors by document_id", extra={"document_id": document_id})
        # Convert document_id to string for consistent matching, as metadata values are often stored as strings.
        doc_id_str = str(document_id)

        for collection_name, collection in self.collections.items():
            try:
                # Perform deletion using a robust where filter that checks for both string and int matches
                # This handles potential inconsistencies in how the metadata was stored.
                collection.delete(where={"document_id": doc_id_str})
                
                # As a fallback, also attempt to delete with the integer ID, in case it was stored as a number.
                # This is less likely with the current sanitization but provides an extra layer of safety.
                # Note: ChromaDB's delete is idempotent, so deleting non-existent items is not an error.
                collection.delete(where={"document_id": document_id})

                logger.info("Deletion processed", extra={"document_id": document_id, "collection": collection_name})
            except Exception as e:
                # If any collection fails, log a critical error and re-raise the exception.
                # This will halt the parent process (in document_processor.py) and prevent
                # the relational DB record from being deleted, thus avoiding data inconsistency.
                logger.error("Failed to delete vectors from collection", extra={"collection": collection_name, "document_id": document_id, "error": str(e)})
                raise e

# Create a singleton instance
vector_store = VectorStoreService()

def add_chunks(chunks: List[Dict[str, Any]]):
    """
    Adds document chunks to the appropriate vector store collection.
    """
    if not chunks:
        return
    
    texts = [chunk['text'] for chunk in chunks]
    metadatas = [chunk['metadata'] for chunk in chunks]
    vector_store.add_texts(texts, metadatas, settings.CHUNKS_COLLECTION_NAME)

def add_summaries(summaries: List[Dict[str, Any]]):
    """
    Adds document summaries to the appropriate vector store collections.
    """
    if not summaries:
        return

    full_summaries_texts = [s['text'] for s in summaries if s['metadata']['summary_type'] == 'full']
    full_summaries_metadatas = [s['metadata'] for s in summaries if s['metadata']['summary_type'] == 'full']
    
    chapter_summaries_texts = [s['text'] for s in summaries if s['metadata']['summary_type'] == 'chapter']
    chapter_summaries_metadatas = [s['metadata'] for s in summaries if s['metadata']['summary_type'] == 'chapter']

    if full_summaries_texts:
        vector_store.add_texts(full_summaries_texts, full_summaries_metadatas, settings.SUMMARIES_COLLECTION_NAME)
    
    if chapter_summaries_texts:
        vector_store.add_texts(chapter_summaries_texts, chapter_summaries_metadatas, settings.CHAPTER_SUMMARIES_COLLECTION_NAME)

def delete_document_vectors(document_id: int):
    """
    Public function to delete all vectors associated with a document.
    """
    vector_store.delete_by_document_id(document_id)

def get_chunks_by_document_id(document_id: int) -> List[Dict[str, Any]]:
    """
    Retrieves all text chunks for a specific document from the vector store,
    trying both integer and string matching for the document_id.
    """
    collection = vector_store.collections[settings.CHUNKS_COLLECTION_NAME]
    
    # Try fetching with integer first
    results = collection.get(
        where={"document_id": document_id},
        include=["documents", "metadatas"]
    )
    
    # If no results, try with string, as metadata values can be inconsistent
    if not results.get('documents'):
        results = collection.get(
            where={"document_id": str(document_id)},
            include=["documents", "metadatas"]
        )

    documents = results.get('documents', [])
    metadatas = results.get('metadatas', [])
    
    if not documents:
        return []
        
    combined_results = []
    for i, doc_text in enumerate(documents):
        meta = metadatas[i] if metadatas and i < len(metadatas) else {}
        combined_results.append({
            "text": doc_text,
            "metadata": meta
        })
        
    return combined_results
