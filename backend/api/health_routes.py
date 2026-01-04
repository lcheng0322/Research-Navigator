from fastapi import APIRouter
from fastapi import HTTPException
from typing import Any, Dict
import sqlalchemy
from sqlalchemy import text
import json

from ..core.config import settings
from ..core.cache import redis_client

router = APIRouter(
    prefix="/api",
    tags=["Health"],
)

@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint that reports the status of core dependencies:
    - Database connectivity
    - Redis connectivity
    - ChromaDB availability (persistence path)
    - LLM client availability (DeepSeek)
    """
    status: Dict[str, Any] = {
        "status": "ok",
        "components": {
            "database": {"ok": False, "details": None},
            "redis": {"ok": False, "details": None},
            "chromadb": {"ok": False, "details": None},
            "llm": {"ok": False, "details": None},
        }
    }

    # Database check
    try:
        engine = sqlalchemy.create_engine(settings.DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status["components"]["database"]["ok"] = True
    except Exception as e:
        status["components"]["database"]["details"] = f"DB error: {e}"

    # Redis check
    try:
        pong = await redis_client.ping()
        status["components"]["redis"]["ok"] = bool(pong)
    except Exception as e:
        status["components"]["redis"]["details"] = f"Redis error: {e}"

    # ChromaDB persistence path check (lightweight)
    try:
        chroma_path = settings.CHROMA_PERSIST_DIR
        exists = chroma_path.exists()
        status["components"]["chromadb"]["ok"] = exists
        status["components"]["chromadb"]["details"] = {
            "path": str(chroma_path),
            "exists": exists,
        }
    except Exception as e:
        status["components"]["chromadb"]["details"] = f"Chroma check error: {e}"

    # LLM client availability (DeepSeek)
    try:
        from ..services.llm_service import reasoner_client, chat_client, reasoner_model_name, chat_model_name
        ok = bool(reasoner_client) and bool(chat_client)
        status["components"]["llm"]["ok"] = ok
        status["components"]["llm"]["details"] = {
            "reasoner_model": reasoner_model_name,
            "chat_model": chat_model_name,
            "configured": ok,
        }
    except Exception as e:
        status["components"]["llm"]["details"] = f"LLM check error: {e}"

    # Overall status determination
    if not all(c.get("ok") for c in status["components"].values()):
        status["status"] = "degraded"

    return status