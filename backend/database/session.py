from typing import Any, Generator


from sqlalchemy.orm.session import Session


from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..core.config import settings

# Create a SQLAlchemy engine
# The 'connect_args' is needed only for SQLite to allow multi-threaded access.
engine = create_engine(
    settings.DATABASE_URL, 
    connect_args={"check_same_thread": False}
)

# Create a SessionLocal class
# This will be the actual database session class.
# autocommit=False and autoflush=False are standard settings for using SQLAlchemy with FastAPI.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Dependency to get a DB session.
# This will be used in API endpoints to get a session and ensure it's closed after the request.
def get_db() -> Generator[Session, Any, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()