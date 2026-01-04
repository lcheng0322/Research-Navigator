import pkgutil
import logging
from pathlib import Path
from celery import Celery
from .config import settings

# --- Task Auto-Discovery Mechanism ---
def find_task_modules():
    """
    Automatically discovers and returns a list of all task modules
    within the 'backend.tasks' package.
    This allows for adding new task files without changing configuration.
    """
    # Path to the 'tasks' package directory
    tasks_package_path = Path(__file__).parent.parent / "tasks"
    # The import name of the package
    tasks_package_name = "backend.tasks"
    
    # Discover and return all module names in the format 'backend.tasks.module_name'
    discovered = [
        f"{tasks_package_name}.{name}"
        for _, name, _ in pkgutil.iter_modules([str(tasks_package_path)])
        if name != "__init__"  # Exclude the __init__.py file itself
    ]
    logging.info(f"Discovered Celery task modules: {discovered}")
    return discovered

# --- Celery Application Initialization ---
# Initialize the Celery application
_task_modules = find_task_modules()
celery_app = Celery(
    "research_navigator",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    # Use our auto-discovery function to dynamically include all task modules.
    include=_task_modules,
)

# Optional configuration to make tracking tasks easier
celery_app.conf.update(
    task_track_started=True,
    # Explicitly import task modules at worker startup to ensure registration
    imports=_task_modules,
)