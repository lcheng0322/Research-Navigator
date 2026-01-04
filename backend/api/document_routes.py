import shutil
import hashlib
import logging
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Depends
from sqlalchemy.orm import Session, joinedload
from typing import Dict, Any, List

from ..core.config import settings
from ..database.session import get_db
from ..models.document import Document, DocumentMetadata
from ..services import document_processor
from ..services import vector_store_service
from ..services.tabular_data_service import tabular_data_service
from ..schemas.document_schemas import DocumentRead
from ..tasks.ingestion_tasks import ingest_document_task

router = APIRouter(
    prefix="/api",
    tags=["Documents"],
)

@router.get("/documents/", response_model=List[DocumentRead], summary="List all documents with metadata")
def get_all_documents(db: Session = Depends(get_db)):
    """
    Retrieves a list of all documents in the system, including their metadata.
    """
    documents = (
        db.query(Document)
        .options(joinedload(Document.metadata_entries))
        .order_by(Document.upload_timestamp.desc())
        .all()
    )
    
    results = []
    for doc in documents:
        # Build a simple key-value map for metadata
        meta_map = {meta.key: meta.value for meta in doc.metadata_entries}

        # Manually construct the dictionary to match the Pydantic schema
        # and include error_message when present for failed documents
        doc_data = {
            "id": doc.id,
            "file_name": doc.file_name,
            "file_type": doc.file_type,
            "upload_timestamp": doc.upload_timestamp,
            "status": doc.status,
            "error_message": meta_map.get("error_message"),
            "metadata": meta_map,
        }
        results.append(doc_data)
        
    return results

@router.post("/upload/", summary="Upload a file for ingestion or analysis")
async def upload_file(
    file: UploadFile = File(...),
    analyze_only: bool = Form(False),
    db: Session = Depends(get_db)
):
    """
    A unified endpoint for file uploads.

    - **Default Behavior**: Processes any file (PDF, DOCX, MD, CSV, etc.) and ingests
      its content into the knowledge base for RAG. It checks for duplicates based on
      file content hash.
    - **Analysis-Only Mode**: If `analyze_only` is set to `true` for a tabular file
      (CSV, XLS, XLSX), it performs a statistical analysis instead of ingestion.
    """
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    file_path = settings.UPLOAD_DIR / file.filename
    file_suffix = file_path.suffix.lower()
    is_tabular = file_suffix in ['.csv', '.xls', '.xlsx']

    try:
        # Read file content to calculate hash and save it
        file_content = await file.read()
        file_hash = hashlib.sha256(file_content).hexdigest()

        # --- Duplicate Check ---
        existing_document = db.query(Document).filter(Document.file_hash == file_hash).first()
        if existing_document:
            raise HTTPException(
                status_code=409, 
                detail=f"Duplicate file detected. A document with the same content ('{existing_document.file_name}') already exists."
            )

        # Save the file to the upload directory (persistent)
        with file_path.open("wb") as buffer:
            buffer.write(file_content)

        file_size = file_path.stat().st_size

        # --- Conditional Logic: Analyze or Ingest ---
        if is_tabular and analyze_only:
            # Branch for analysis-only mode for tabular data
            analysis_result = tabular_data_service.get_full_analysis(file_path)
            return analysis_result
        else:
            # Branch for knowledge base ingestion (async via Celery)
            try:
                task = ingest_document_task.delay(str(file_path), file_hash, file_size)
                return {
                    "message": f"File uploaded successfully! Processing has started.",
                    "task_id": task.id,
                    "status": "Accepted"
                }
            except Exception as e:
                logging.error(f"Failed to enqueue ingestion task: {e}")
                raise HTTPException(status_code=500, detail="Failed to start ingestion task.")

    except Exception as e:
        # Re-raise HTTPException to preserve status code and detail
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")
    finally:
        # Clean up only for analysis-only tabular branch; ingestion requires the file to remain.
        if is_tabular and analyze_only:
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception:
                    pass


@router.get(
    "/documents/{document_id}/metadata",
    response_model=Dict[str, Any],
    summary="Get Document Metadata",
    description="Retrieves all stored metadata for a specific document by its ID.",
    tags=["Documents"]
)
def get_document_metadata(document_id: int, db: Session = Depends(get_db)):
    """
    Retrieves all metadata associated with a given document_id.

    - **document_id**: The integer ID of the document.
    - **db**: The database session dependency.

    Returns a dictionary of the document's metadata.
    Raises HTTPException 404 if the document is not found.
    """
    # First, check if the document itself exists
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=f"Document with ID {document_id} not found.")

    # Query for all metadata entries for this document
    metadata_records = db.query(DocumentMetadata).filter(DocumentMetadata.document_id == document_id).all()

    # Format the records into a simple key-value dictionary
    response_data: Dict[str, Any] = {str(record.key): record.value for record in metadata_records}
    
    # Also include basic document info for context
    response_data["_document_id"] = document.id
    response_data["_file_name"] = document.file_name
    response_data["_status"] = document.status

    return response_data


@router.delete(
    "/documents/{document_id}",
    summary="Delete a document and all its associated data",
    status_code=200
)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db)
):
    """
    Deletes a document from the system, ensuring that its data is removed
    from both the relational database and the vector database.

    - **document_id**: The ID of the document to delete.
    """
    try:
        deleted_doc = document_processor.delete_document_and_vectors(
            db=db, 
            document_id=document_id
        )
        return {
            "message": f"Successfully deleted document '{deleted_doc.file_name}' (ID: {document_id}) and all its associated data."
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        # Catch-all for other potential errors during the process
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during deletion: {str(e)}")


@router.post("/documents/{document_id}/reprocess", summary="Reprocess a document to refresh metadata and vectors")
def reprocess_document_endpoint(document_id: int, db: Session = Depends(get_db)):
    """
    Reprocesses an existing document:
    - Validates the document exists and its source file is accessible
    - Deletes existing vectors to avoid duplication
    - Re-runs the processing pipeline to refresh metadata, chunks and summaries
    - Adds refreshed chunks and summaries back into the vector store
    """
    # Validate document exists
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=f"Document with ID {document_id} not found.")

    # 1) Delete existing vectors to avoid duplicates
    try:
        vector_store_service.delete_document_vectors(document_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear existing vectors: {str(e)}")

    # 2) Reprocess the document
    try:
        chunks, full_summary, chapter_summaries = document_processor.reprocess_document(db=db, document_id=document_id)
        if not chunks:
            # If no chunks produced, treat as failure (status is set inside service)
            raise HTTPException(status_code=500, detail="Reprocessing did not produce any content chunks.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred during reprocessing: {str(e)}")

    # 3) Add refreshed vectors
    try:
        vector_store_service.add_chunks(chunks)
        summaries = []
        if full_summary:
            summaries.append(full_summary)
        if chapter_summaries:
            summaries.extend(chapter_summaries)
        if summaries:
            try:
                vector_store_service.add_summaries(summaries)
            except Exception as e:
                # Log and continue
                import logging
                logging.error(f"Failed to add refreshed summaries to vector store: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add refreshed vectors: {str(e)}")

    return {
        "message": f"Successfully reprocessed document '{document.file_name}' (ID: {document_id}).",
        "document_id": document_id,
        "chunks_count": len(chunks),
        "summaries_count": (len(chapter_summaries) + (1 if full_summary else 0))
    }


@router.get("/documents/{document_id}/content", summary="Get processed document content chunks")
def get_document_content(document_id: int, db: Session = Depends(get_db)):
    """
    Retrieves the processed content chunks for a specific document from the vector store.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=f"Document with ID {document_id} not found.")

    try:
        chunks = vector_store_service.get_chunks_by_document_id(document_id)
        if not chunks:
            return [] # Return empty list if no content is found, which is a valid case
        return chunks
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while fetching document content: {str(e)}")
