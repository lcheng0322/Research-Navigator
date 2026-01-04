import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    JSON,
)
from sqlalchemy.orm import relationship

from .base import Base

class Document(Base):
    """
    Represents an uploaded document in the system.
    Each document serves as a container for its metadata and text chunks.
    """
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String, nullable=False)
    file_type = Column(String, nullable=True)
    file_path = Column(String, nullable=False, unique=True)
    file_hash = Column(String, nullable=False, unique=True, index=True)
    file_size = Column(Integer, nullable=True)
    upload_timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    status = Column(String, default="processing", index=True)

    # This creates a one-to-many relationship to DocumentMetadata.
    # The 'back_populates' argument establishes a bidirectional relationship.
    # 'cascade="all, delete-orphan"' means that when a Document is deleted,
    # all its associated metadata will also be deleted.
    metadata_entries = relationship(
        "DocumentMetadata",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self):
        return f"<Document(id={self.id}, file_name='{self.file_name}')>"

class DocumentMetadata(Base):
    """
    Stores key-value metadata for a document.
    This provides a flexible way to store various attributes like 'author',
    'publication_year', 'title', etc.
    """
    __tablename__ = "document_metadata"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    key = Column(String, nullable=False, index=True)
    value = Column(String)
    extra = Column(JSON, nullable=True)

    # This establishes the other side of the one-to-many relationship.
    document = relationship("Document", back_populates="metadata_entries")

    def __repr__(self):
        return f"<DocumentMetadata(key='{self.key}', value='{self.value}')>"