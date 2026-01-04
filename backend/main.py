from typing import Any, Dict

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
import sqlalchemy
from sqlalchemy import inspect
from prometheus_fastapi_instrumentator import Instrumentator

from .api import document_routes, query_routes, analysis_routes, task_routes, user_routes, auth_routes, health_routes
from .core.logging import setup_logging
from .core.config import settings
from .core.dependencies import get_current_active_user
from .core.cache import redis_client, close_redis_connection
import logging

# The setup_directories() function is now called automatically when the config module is imported.
# No need for an explicit call here.

setup_logging()

app = FastAPI(
    title="Research Navigator API",
    description="API for the Scientific RAG System.",
    version="0.1.0",
)

# Instrument the app for Prometheus monitoring BEFORE adding other middleware
Instrumentator().instrument(app).expose(app)

# CORS (Cross-Origin Resource Sharing) configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Allow local dev origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

# Middleware to add the X-Content-Type-Options header
@app.middleware("http")
async def add_x_content_type_options(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# Include the modular API routes
app.include_router(auth_routes.router)
app.include_router(user_routes.router)
app.include_router(health_routes.router)
app.include_router(document_routes.router, dependencies=[Depends(get_current_active_user)])
app.include_router(query_routes.router, dependencies=[Depends(get_current_active_user)])
app.include_router(analysis_routes.router, dependencies=[Depends(get_current_active_user)])
app.include_router(task_routes.router, dependencies=[Depends(get_current_active_user)])
# Include WebSocket router WITHOUT HTTP auth dependency because it handles JWT manually.
app.include_router(task_routes.ws_router)



@app.on_event("startup")
def startup_event():
    """
    Diagnostic function to run on application startup.
    This will help us verify the database connection and state.
    """
    logger = logging.getLogger("uvicorn")
    logger.info("--- Running Startup Diagnostics ---")
    
    db_path = settings.DATABASE_FILE.resolve()
    logger.info(f"Application configured to use database at: {db_path}")
    
    if not db_path.exists():
        logger.warning("DIAGNOSTIC: Database file does NOT exist at the configured path.")
        return

    try:
        logger.info("DIAGNOSTIC: Connecting to the database to inspect tables...")
        engine = sqlalchemy.create_engine(settings.DATABASE_URL)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        if tables:
            logger.info(f"DIAGNOSTIC: Found tables in the database: {tables}")
        else:
            logger.warning("DIAGNOSTIC: Connected to the database, but it contains NO tables.")
    except Exception as e:
        logger.error(f"DIAGNOSTIC: An error occurred while inspecting the database: {e}")
    
    logger.info("--- Startup Diagnostics Finished ---")

# Instrumentation is now done during app initialization, before startup events


@app.on_event("startup")
async def startup_redis_event():
    """
    On startup, connect to Redis and confirm the connection.
    """
    logger = logging.getLogger("uvicorn")
    try:
        await redis_client.ping()
        logger.info("Successfully connected to Redis.")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")


@app.on_event("shutdown")
async def shutdown_redis_event():
    """
    On shutdown, gracefully close the Redis connection.
    """
    logger = logging.getLogger("uvicorn")
    logger.info("Closing Redis connection...")
    await close_redis_connection()



@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Welcome to the Research Navigator API. Visit /docs for documentation."}

# To run the app:
# uvicorn main:app --reload