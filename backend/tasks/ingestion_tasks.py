import logging
from pathlib import Path
from typing import Any, Dict, List

from ..core.celery_app import celery_app
from ..database.session import SessionLocal
from ..services import document_processor
from ..services import vector_store_service

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.ingest_document")
def ingest_document_task(file_path: str, file_hash: str, file_size: int) -> Dict[str, Any]:
    """
    Celery task to process a document and store its chunks and summaries in the vector store.
    Steps:
    - Open DB session
    - Run document processing pipeline
    - Add chunks and summaries to vector store
    - Return summary info
    """
    logger.info("[Ingestion] Task started", extra={"file_path": file_path, "file_size": file_size})

    db = SessionLocal()
    try:
        path_obj = Path(file_path)
        document_id, chunks, full_summary, chapter_summaries = document_processor.process_document(
            db=db,
            file_path=path_obj,
            file_size=file_size,
            file_hash=file_hash,
        )

        # Add chunks
        if chunks:
            vector_store_service.add_chunks(chunks)

        # Combine summaries and add
        summaries: List[Dict[str, Any]] = []
        if full_summary:
            summaries.append(full_summary)
        if chapter_summaries:
            summaries.extend(chapter_summaries)
        if summaries:
            try:
                vector_store_service.add_summaries(summaries)
            except Exception as e:
                logger.error("[Ingestion] Failed to add summaries", extra={"error": str(e)})

        logger.info("[Ingestion] Task completed", extra={"document_id": document_id, "chunks": len(chunks), "summaries": len(summaries)})
        return {
            "status": "success",
            "document_id": document_id,
            "chunks_count": len(chunks),
            "summaries_count": len(summaries),
        }
    except Exception as e:
        logger.error("[Ingestion] Task failed", extra={"error": str(e)})
        raise
    finally:
        db.close()