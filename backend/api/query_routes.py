from fastapi import APIRouter, HTTPException, Form, Depends, Body
from fastapi.responses import StreamingResponse
import io
import logging
import json
import hashlib
from sqlalchemy.orm import Session
from datetime import timezone
from zoneinfo import ZoneInfo

from ..services.query_analyzer import analyze_query
from ..services.query_service import retrieve_and_rank
from ..services.evidence_assessor_service import evidence_assessor_service
from ..services.reasoning_engine_service import reasoning_engine_service
from ..services.query_export_service import query_export_service
from ..schemas.response_schemas import validate_final_response
from ..core.cache import redis_client
from ..core.config import settings
from ..core.dependencies import get_db, get_current_active_user
from ..models.user import User
from ..models.query_history import QueryHistory

router = APIRouter(
    prefix="/api",
    tags=["Query"],
)

CACHE_EXPIRATION_SECONDS = 3600  # 1 hour

@router.post("/query/", summary="Query the RAG system")
async def query_system(
    query: str = Form(...), 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_active_user)
):
    """
    Endpoint to ask a question. It retrieves relevant context and generates a response.
    This endpoint uses Redis for caching to improve performance.
    """
    # --- Caching Logic: Start ---
    # 1. Create a stable cache key based on the query content and user.
    # We use a SHA256 hash to keep the key short and consistent.
    # The key is prefixed to follow a Redis naming convention and avoid collisions.
    # Adding user_id to the hash ensures user-specific caching.
    query_hash = hashlib.sha256(f"{current_user.id}:{query}".encode('utf-8')).hexdigest()
    cache_key = f"cache:query:{query_hash}"

    # 2. Try to fetch the result from the cache.
    cached_result = await redis_client.get(cache_key)
    if cached_result:
        # If found, deserialize the JSON string and return the data directly.
        return json.loads(cached_result)
    # --- Caching Logic: End ---

    try:
        # --- Original Business Logic: Start ---
        # (This part only runs if there is a cache miss)

        # 1. Analyze the user's query to understand intent and optimize for retrieval
        query_analysis = analyze_query(query)
        rewritten_query = query_analysis.rewritten_query
        intent = query_analysis.intent

        # 2. Retrieve and rank relevant documents (chunks or summaries) based on intent
        ranked_results = retrieve_and_rank(
            query_text=rewritten_query,
            intent=intent,
            n_results=settings.RAG_QUERY_TOP_K
        )


        if not ranked_results:
            response_data = {
                "reasoned_answer": {
                    "synthesized_answer": "I could not find any relevant information in the knowledge base to answer your question.",
                    "limitations_analysis": "No documents were found to analyze.",
                    "alternative_hypotheses": []
                },
                "query_analysis": query_analysis.model_dump(),
                "assessment": None,
                "context": []
            }
            # --- Save Query History ---
            history_entry = QueryHistory(
                user_id=current_user.id,
                query_text=query,
                query_metadata={
                    "query_analysis": query_analysis.model_dump(),
                    "num_results": 0,
                },
                result_payload=response_data
            )
            db.add(history_entry)
            db.commit()
            # --- End Save Query History ---

            # Cache the "not found" response as well to avoid re-computing
            await redis_client.setex(cache_key, CACHE_EXPIRATION_SECONDS, json.dumps(response_data))
            return response_data

        # 3. Assess the consistency of the retrieved evidence
        assessment = evidence_assessor_service.assess_evidence(
            query=query,
            documents=ranked_results
        )

        # 4. Generate a reasoned answer using the new engine
        reasoned_answer = reasoning_engine_service.generate_reasoned_answer(
            query=query,
            evidence=ranked_results
        )

        # 4.1 Align context items with Source_n labels returned by the reasoning engine
        citation_index = reasoned_answer.get("citation_index") or []
        srcfile_to_id = {entry.get("source_file"): entry.get("source_id") for entry in citation_index}
        for item in ranked_results:
            # Attach source_id for UI to correlate [Source_n] with actual file
            item["source_id"] = srcfile_to_id.get(item.get("source"))

        # 5. Prepare the final response
        final_response = {
            "reasoned_answer": reasoned_answer,
            "query_analysis": query_analysis.model_dump(),
            "assessment": assessment,
            "context": ranked_results
        }

        # Normalize and validate response payload before caching
        final_response = validate_final_response(final_response)

        # --- Caching Logic: Store Result ---
        # Before returning, store the final response in the cache for future requests.
        # We use 'setex' to set the value along with an expiration time.
        await redis_client.setex(cache_key, CACHE_EXPIRATION_SECONDS, json.dumps(final_response))
        # --- Caching Logic: End ---

        # --- Save Query History ---
        history_entry = QueryHistory(
            user_id=current_user.id,
            query_text=query,
            query_metadata={
                "query_analysis": query_analysis.model_dump(),
                "num_results": len(ranked_results) if ranked_results else 0,
                "context_count": len(ranked_results) if ranked_results else 0,
            },
            result_payload=final_response
        )
        db.add(history_entry)
        db.commit()
        # --- End Save Query History ---

        return final_response
        # --- Original Business Logic: End ---

    except Exception as e:
        # Note: We are not caching errors to avoid serving stale error messages.
        raise HTTPException(status_code=500, detail=f"An error occurred during query: {e}")

@router.get("/query/history", summary="Get user's query history")
async def get_query_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Retrieves the query history for the currently authenticated user.
    """
    history = db.query(QueryHistory).filter(QueryHistory.user_id == current_user.id).order_by(QueryHistory.created_at.desc()).all()

    def _to_shanghai_iso(dt):
        if not dt:
            return None
        # Ensure timezone-aware; assume UTC if naive
        if dt.tzinfo is None:
            try:
                dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        try:
            return dt.astimezone(ZoneInfo('Asia/Shanghai')).isoformat()
        except Exception:
            # Fallback to ISO or string
            try:
                return dt.isoformat()
            except Exception:
                return str(dt)

    # Serialize entries with created_at converted to Asia/Shanghai (UTC+8)
    serialized = [
        {
            "id": h.id,
            "user_id": h.user_id,
            "query_text": h.query_text,
            "created_at": _to_shanghai_iso(h.created_at),
            "query_metadata": h.query_metadata,
            "result_payload": h.result_payload,
        }
        for h in history
    ]

    return serialized

@router.delete("/query/history/{history_id}", summary="Delete a specific query history entry")
async def delete_query_history_entry(
    history_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Deletes a specific entry from the user's query history.
    """
    history_entry = db.query(QueryHistory).filter(
        QueryHistory.id == history_id, 
        QueryHistory.user_id == current_user.id
    ).first()

    if not history_entry:
        raise HTTPException(status_code=404, detail="History entry not found or you do not have permission to delete it.")

    db.delete(history_entry)
    db.commit()
    return {"status": "success", "message": "History entry deleted successfully."}


@router.post("/query/download", summary="Download Smart Q&A result as DOCX")
async def download_query_result_docx(
    payload: dict = Body(..., description="JSON containing 'query_text' and 'result_payload' fields")
):
    """
    Accepts the current query result payload and returns a generated DOCX file for download.
    This avoids requiring a history ID and supports immediate export of the latest result.
    """
    try:
        query_text = payload.get("query_text") or payload.get("query") or ""
        result_payload = payload.get("result_payload") or payload
        if not result_payload:
            raise HTTPException(status_code=400, detail="Missing result payload for export.")

        doc = query_export_service.export_query_result_to_docx(result_payload, query_text)
        file_stream = io.BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)
        return StreamingResponse(
            file_stream,
            media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            headers={'Content-Disposition': 'attachment; filename=smart_qa_result.docx'}
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error exporting Smart Q&A result: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export Smart Q&A result.")
