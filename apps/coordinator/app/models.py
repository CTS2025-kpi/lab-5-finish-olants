from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, Literal, List

class TableDef(BaseModel):
    table_name: str = Field(min_length=1)
    partition_key: str = Field(min_length=1)
    sort_key: str = Field(min_length=1)

ReplicaRole = Literal["auto", "leader", "follower"]

class RegisterReplicaRequest(BaseModel):
    shard_name: str = Field(min_length=1)
    replica_url: str = Field(min_length=1)
    replica_id: Optional[str] = None
    role: ReplicaRole = "auto"

class RegisterReplicaResponse(BaseModel):
    shard_name: str
    assigned_role: Literal["leader", "follower"]
    leader_url: str

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
    shard_url: Optional[str] = None

class ExistsResponse(BaseModel):
    exists: bool
    shard_url: Optional[str] = None

class ReplicaInfo(BaseModel):
    shard_name: str
    replica_url: str
    replica_id: Optional[str] = None
    role: Literal["leader", "follower"]
    last_seen_unix: float
