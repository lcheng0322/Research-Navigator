import sys
from pathlib import Path

# Add the project root to the Python path to allow for absolute imports
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

import logging
from contextlib import contextmanager

from backend.database.session import SessionLocal, engine
from backend.models.base import Base
# Make sure all models are imported here so that Base.metadata knows about them
from backend.models.document import Document, DocumentMetadata
from backend.models.user import User
from backend.models.query_history import QueryHistory
from backend.services.vector_store_service import vector_store

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@contextmanager
def get_db():
    """Provide a transactional scope around a series of operations."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def initialize_database():
    """Creates all tables in the database based on SQLAlchemy models."""
    try:
        logging.info("Initializing relational database tables...")
        Base.metadata.create_all(bind=engine)
        logging.info("Successfully initialized relational database tables.")
    except Exception as e:
        logging.error(f"Error initializing relational database: {e}")

def clear_document_tables():
    """Deletes all records from Document and DocumentMetadata tables."""
    with get_db() as db:
        try:
            logging.info("Attempting to delete records from DocumentMetadata table...")
            num_metadata_deleted = db.query(DocumentMetadata).delete()
            logging.info(f"Deleted {num_metadata_deleted} records from DocumentMetadata.")

            logging.info("Attempting to delete records from Document table...")
            num_docs_deleted = db.query(Document).delete()
            logging.info(f"Deleted {num_docs_deleted} records from Document.")

            db.commit()
            logging.info("Successfully cleared document-related tables.")
        except Exception as e:
            logging.error(f"Error clearing document tables: {e}")
            db.rollback()

def reset_vector_database():
    """Deletes and recreates all specified ChromaDB collections."""
    try:
        client = vector_store.db_client
        collections_to_reset = [
            "document_chunks",
            "document_summaries",
            "document_chapter_summaries"
        ]
        
        logging.info("Attempting to reset ChromaDB collections...")
        for collection_name in collections_to_reset:
            try:
                logging.info(f"Deleting collection: {collection_name}...")
                client.delete_collection(name=collection_name)
            except Exception:
                # It might fail if the collection doesn't exist, which is fine.
                logging.warning(f"Could not delete collection '{collection_name}' (it may not exist), proceeding to create.")
            
            logging.info(f"Recreating collection: {collection_name}...")
            client.create_collection(name=collection_name)
            logging.info(f"Successfully reset collection: {collection_name}.")

        logging.info("Successfully reset vector database.")
    except Exception as e:
        logging.error(f"An unexpected error occurred while resetting ChromaDB: {e}")

if __name__ == "__main__":
    logging.info("--- Starting Full Database Reset ---")
    # 1. Ensure all tables exist
    initialize_database()
    # 2. Clear old document records to prevent inconsistency
    clear_document_tables()
    # 3. Reset the vector store to a clean state
    reset_vector_database()
    logging.info("--- Full Database Reset Complete ---")
