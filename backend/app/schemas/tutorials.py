"""Request and response shapes for tutorial progress (0b spec 5.2)."""

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ProgressEvent(str, enum.Enum):
    seen = "seen"
    completed = "completed"


class ProgressEventRequest(BaseModel):
    event: ProgressEvent


class ProgressEntry(BaseModel):
    key: str
    seen_at: datetime
    completed_at: Optional[datetime] = None
