# This file will contain our asynchronous analysis tasks.
# For example, literature review generation, metadata extraction, etc.

from ..core.celery_app import celery_app
import time

@celery_app.task
def example_task(x, y):
    """An example task that adds two numbers."""
    time.sleep(5) # Simulate a long-running task
    return x + y