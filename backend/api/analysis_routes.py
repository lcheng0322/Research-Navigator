import os
import uuid
import logging
from pathlib import Path
from typing import Any, cast, Dict, List, Optional
from fastapi import APIRouter, Form, status, UploadFile, File, HTTPException, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json
import io
import pandas as pd
from celery.result import AsyncResult

from ..tasks.analysis_tasks import (
    analyze_research_gaps_task,
    generate_review_from_outline_task,
)
from ..services.tabular_data_service import tabular_data_service
from ..services.experiment_designer_service import experiment_designer_service
from ..services.research_gap_analyzer_service import research_gap_analyzer_service
from ..schemas.experiment_schemas import (
    ExperimentDesignRequest, 
    ExperimentDesign, 
    CreateSessionResponse
)
from ..services.literature_review_service import literature_review_service, ReviewOutline
from ..core.cache import redis_client
from fastapi import HTTPException

router = APIRouter(
    prefix="/api",
    tags=["Analysis"],
)

CACHE_EXPIRATION_SECONDS = 3600  # 1 hour
TEMP_FILE_DIR = "temp_files"

class TaskCreationResponse(BaseModel):
    task_id: str
    status: str
    message: str

class OutlineCreationResponse(BaseModel):
    outline: Dict[str, Any]
    context_id: str

# --- Helper for file handling ---
async def save_upload_file(upload_file: UploadFile) -> Path:
    os.makedirs(TEMP_FILE_DIR, exist_ok=True)
    if not upload_file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")
    file_ext = os.path.splitext(upload_file.filename)[1]
    if file_ext not in ['.csv', '.xlsx']:
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a .csv or .xlsx file.")
    
    temp_file_path = Path(TEMP_FILE_DIR) / f"{uuid.uuid4()}{file_ext}"
    with open(temp_file_path, "wb") as buffer:
        buffer.write(await upload_file.read())
    return temp_file_path

# --- Literature Review ---
@router.post("/generate/literature-review/outline", response_model=OutlineCreationResponse)
async def generate_outline_endpoint(topic: str = Form(...)):
    result = literature_review_service.generate_outline(topic)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    
    context_id = str(uuid.uuid4())
    await redis_client.setex(f"context:{context_id}", CACHE_EXPIRATION_SECONDS, json.dumps(result["context_docs"]))
    
    return {
        "outline": result["outline"],
        "context_id": context_id
    }

@router.post("/generate/literature-review/from-outline", response_model=TaskCreationResponse)
async def generate_from_outline_endpoint(outline: Dict[str, Any] = Body(...), context_id: str = Body(...)):
    cached_context = await redis_client.get(f"context:{context_id}")
    if not cached_context:
        raise HTTPException(status_code=404, detail="Context ID not found or expired.")
    
    context_docs = json.loads(cached_context)
    
    task = generate_review_from_outline_task.delay(outline, context_docs)
    return {
        "task_id": task.id,
        "status": "Accepted",
        "message": "Literature review generation task has been started."
    }

@router.get("/generate/literature-review/download/{task_id}")
async def download_review_docx(task_id: str):
    task_result = AsyncResult(task_id)
    if not task_result.ready():
        raise HTTPException(status_code=404, detail="Task not found or not completed.")
    if task_result.failed():
        raise HTTPException(status_code=500, detail="Task failed to generate the review.")

    review_data = task_result.result
    doc = literature_review_service.export_review_to_docx(review_data)
    
    file_stream = io.BytesIO()
    doc.save(file_stream)
    file_stream.seek(0)
    
    return StreamingResponse(file_stream, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document', headers={'Content-Disposition': f'attachment; filename=literature_review_{task_id}.docx'})

# --- Gap Analysis ---
@router.post("/analyze/research-gaps/", summary="Start a research gap analysis task", status_code=status.HTTP_202_ACCEPTED, response_model=TaskCreationResponse)
async def start_research_gap_analysis():
    task = cast(AsyncResult, getattr(analyze_research_gaps_task, 'delay')())
    return {
        "task_id": task.id,
        "status": "Accepted",
        "message": "Research gap analysis task has been started."
    }

@router.get("/analyze/research-gaps/download/{task_id}")
async def download_gap_analysis_docx(task_id: str):
    task_result = AsyncResult(task_id)
    if not task_result.ready():
        raise HTTPException(status_code=404, detail="Task not found or not completed.")
    if task_result.failed():
        raise HTTPException(status_code=500, detail="Task failed to perform gap analysis.")

    analysis_data = task_result.result
    try:
        doc = research_gap_analyzer_service.export_gap_analysis_to_docx(analysis_data)
        file_stream = io.BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)
        return StreamingResponse(
            file_stream,
            media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            headers={'Content-Disposition': f'attachment; filename=gap_analysis_{task_id}.docx'}
        )
    except Exception as e:
        logging.error(f"Error exporting gap analysis for task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export the research gap analysis.")

# --- Tabular Data Analysis ---
@router.post("/analyze/tabular-data/initiate")
async def initiate_tabular_analysis(file: UploadFile = File(...)):
    temp_file_path = await save_upload_file(file)
    try:
        analysis_results = tabular_data_service.get_full_analysis(temp_file_path)
        # Store file path in cache for subsequent calls
        file_id = str(uuid.uuid4())
        await redis_client.setex(f"tabular_file:{file_id}", CACHE_EXPIRATION_SECONDS, str(temp_file_path))
        analysis_results['file_id'] = file_id
        return analysis_results
    except Exception as e:
        logging.error(f"Error during initial tabular data analysis: {e}")
        raise HTTPException(status_code=500, detail=f"An error occurred during analysis: {str(e)}")

async def _load_cached_df(file_id: str) -> pd.DataFrame:
    """Load cached tabular file into a DataFrame with proper type handling (CSV/XLS/XLSX)."""
    file_path_str = await redis_client.get(f"tabular_file:{file_id}")
    if not file_path_str:
        raise HTTPException(status_code=404, detail="File ID not found or expired.")

    file_path = Path(file_path_str)
    suffix = file_path.suffix.lower()
    try:
        if suffix == ".csv":
            return pd.read_csv(file_path)
        elif suffix in [".xls", ".xlsx"]:
            return pd.read_excel(file_path)
        else:
            # Fallback to service loader for any future supported types
            return tabular_data_service._get_dataframe(file_path)
    except Exception as e:
        logging.error(f"Failed to load cached file {file_path} for regression/visualization: {e}")
        raise HTTPException(status_code=500, detail="Failed to read cached tabular file.")

@router.post("/analyze/tabular-data/regression")
async def perform_regression(file_id: str = Form(...), analysis_type: str = Form(...), dependent_var: str = Form(...), independent_vars: List[str] = Form(...)):
    df = await _load_cached_df(file_id)

    if analysis_type == 'linear':
        if len(independent_vars) != 1:
            raise HTTPException(status_code=400, detail="Linear regression requires exactly one independent variable.")
        return tabular_data_service.perform_linear_regression(df, independent_vars[0], dependent_var)
    elif analysis_type == 'logistic':
        return tabular_data_service.perform_logistic_regression(df, independent_vars, dependent_var)
    else:
        raise HTTPException(status_code=400, detail="Invalid analysis type.")

@router.post("/analyze/tabular-data/visualize")
async def generate_visualization(file_id: str = Form(...), vis_type: str = Form(...), x_col: str = Form(...), y_col: Optional[str] = Form(None)):
    df = await _load_cached_df(file_id)

    return tabular_data_service.generate_visualizations(df, vis_type, x_col, y_col)

# --- Experiment Designer ---
@router.post("/experiments", response_model=CreateSessionResponse, summary="Create a New Experiment Design Session", status_code=status.HTTP_201_CREATED)
async def create_experiment_session(request: ExperimentDesignRequest):
    try:
        session_response = experiment_designer_service.create_session(request)
        return session_response
    except Exception as e:
        logging.error(f"Error creating experiment design session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start experiment design session.")

@router.post("/experiments/{session_id}/design", response_model=ExperimentDesign, summary="Generate the Full Experimental Design")
async def generate_full_experimental_design(session_id: str):
    try:
        design_proposal = experiment_designer_service.generate_full_design(session_id)
        return design_proposal
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error generating full experimental design for session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate the full experimental design.")

@router.post("/experiments/{session_id}/refine", response_model=ExperimentDesign, summary="Review and Refine an Experimental Design")
async def refine_experimental_design(session_id: str):
    try:
        refined_design = experiment_designer_service.review_and_refine_design(session_id)
        return refined_design
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error refining experimental design for session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to refine the experimental design.")

@router.get("/experiments/{session_id}/download")
async def download_experiment_design_docx(session_id: str):
    try:
        design = experiment_designer_service.get_final_design(session_id)
        doc = experiment_designer_service.export_design_to_docx(design)
        file_stream = io.BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)
        return StreamingResponse(
            file_stream,
            media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            headers={'Content-Disposition': f'attachment; filename=experiment_design_{session_id}.docx'}
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error exporting experiment design for session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export the experimental design.")
