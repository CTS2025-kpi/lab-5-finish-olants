from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional

class CreateRecordRequest(BaseModel):
    table_name: str = Field(min_length=1)
    pk: str = Field(min_length=1)
    sk: str = Field(min_length=1)
    value: Dict[str, Any] = Field(default_factory=dict)

class RecordResponse(BaseModel):
    table_name: str
    pk: str
    sk: str
    value: Optional[Dict[str, Any]] = None
    version: Optional[int] = None
    origin: Optional[str] = None

class ExistsResponse(BaseModel):
    exists: bool
