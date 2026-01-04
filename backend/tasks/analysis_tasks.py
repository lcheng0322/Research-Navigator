import logging
from ..core.celery_app import celery_app
from ..core.config import settings
from ..services.literature_review_service import literature_review_service
from ..services.research_gap_analyzer_service import perform_gap_analysis

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Removed single-step literature review generation task to align with
# the three-step frontend workflow (topic -> outline -> generate & download).

@celery_app.task(name="tasks.analyze_research_gaps")
def analyze_research_gaps_task():
    """
    Celery task to analyze research gaps in the background.
    """
    logging.info("Celery task started: Analyze research gaps.")
    try:
        # Use the existing gap analysis implementation directly.
        # We pass the default collections used across the app.
        collection_names = [
            settings.CHUNKS_COLLECTION_NAME,
            settings.SUMMARIES_COLLECTION_NAME,
        ]
        results = perform_gap_analysis(collection_names)
        logging.info("Celery task finished: Research gap analysis completed successfully.")
        return results
    except Exception as e:
        logging.error(f"Celery task failed: Error analyzing research gaps. Error: {e}", exc_info=True)
        # Re-raise the exception so Celery can mark the task as FAILED
        raise

# New task to generate literature review directly from an outline and cached context
@celery_app.task(name="tasks.generate_review_from_outline")
def generate_review_from_outline_task(outline: dict, context_docs: dict):
    """
    Celery task to generate the full literature review from a provided outline
    and previously cached context documents.
    """
    logging.info("Celery task started: Generate literature review from outline.")
    try:
        review = literature_review_service.generate_review_from_outline(outline=outline, context_docs=context_docs)
        if review.get("error"):
            raise Exception(f"Failed to generate review from outline: {review['error']}")
        logging.info("Celery task finished: Literature review generated successfully from outline.")
        return review
    except Exception as e:
        logging.error(f"Celery task failed: Error generating literature review from outline. Error: {e}", exc_info=True)
        # Re-raise the exception so Celery can mark the task as FAILED
        raise