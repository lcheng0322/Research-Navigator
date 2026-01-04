# This file is the entry point for the Celery worker process.
# It imports the configured Celery app instance so that the `celery` command-line tool can find it.

from .core.celery_app import celery_app

# Force import of task modules to guarantee registration when worker starts.
# This is complementary to auto-discovery in celery_app and avoids stale workers
# missing newly added tasks.
from .tasks import analysis_tasks  # noqa: F401
from .tasks import ingestion_tasks  # noqa: F401

# To run the worker from the project root directory (e.g., 'Research Navigator/'),
# you would use the following command in a separate terminal:
#
# celery -A backend.worker worker --loglevel=info
#
# This command tells Celery:
# -A backend.worker: "Look for the app instance inside the 'backend/worker.py' file."
# worker: "Start a worker process."
# --loglevel=info: "Set the logging level to INFO to see task execution details."