from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import jwt, JWTError
import asyncio
from celery.result import AsyncResult
from pydantic import BaseModel
from typing import Any

from ..core.celery_app import celery_app
from ..core.config import settings

router = APIRouter(
    prefix="/api/tasks",
    tags=["Tasks"],
)
ws_router = APIRouter(
    prefix="/api/tasks",
    tags=["Tasks WebSocket"],
)

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: Any | None = None

@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    Get the status and result of any background task by its ID.
    
    This endpoint can be polled to check for task completion.
    """
    task_result = AsyncResult(task_id, app=celery_app)
    
    result = None
    if task_result.successful():
        result = task_result.get()
    elif task_result.failed():
        # If the task failed, return the error information as the result
        result = {
            "error": str(task_result.info.__class__.__name__),
            "message": str(task_result.info)
        }

    return {
        "task_id": task_id,
        "status": task_result.status,
        "result": result
    }


@ws_router.websocket("/ws/{task_id}")
async def task_status_ws(websocket: WebSocket, task_id: str):
    """
    WebSocket endpoint to stream task status updates to the client.

    Authentication: expects a JWT access token via query parameter `token`.
    Example: ws://127.0.0.1:8000/api/tasks/ws/<task_id>?token=<jwt>
    """
    token = websocket.query_params.get("token")
    if not token:
        # Policy violation: no token provided
        await websocket.close(code=1008)
        return
    try:
        # Validate JWT and extract subject
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if not payload.get("sub"):
            await websocket.close(code=1008)
            return
    except JWTError:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        task_result = AsyncResult(task_id, app=celery_app)
        # Stream periodic updates until terminal state
        while True:
            status = task_result.status
            result: Any | None = None
            if task_result.successful():
                result = task_result.get()
            elif task_result.failed():
                result = {
                    "error": str(getattr(task_result.info, "__class__", type(task_result.info)).__name__),
                    "message": str(task_result.info),
                }

            await websocket.send_json({
                "task_id": task_id,
                "status": status,
                "result": result,
            })

            if status in ("SUCCESS", "FAILURE"):
                await websocket.close(code=1000)
                break

            await asyncio.sleep(2)
    except WebSocketDisconnect:
        # Client disconnected; nothing else to do
        return