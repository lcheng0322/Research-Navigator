from pydantic import BaseModel, Field
from datetime import datetime
from typing import Dict, Any

class DocumentRead(BaseModel):
    id: int
    file_name: str
    file_type: str | None = None
    upload_timestamp: datetime
    status: str
    error_message: str | None = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True
