from __future__ import annotations
import time
from typing import Dict, List, Optional
from .models import TableDef, ReplicaInfo

class TableRegistry:
    def __init__(self):
        self._tables: Dict[str, TableDef] = {}

    def register(self, t: TableDef) -> TableDef:
        self._tables[t.table_name] = t
        return t

    def exists(self, name: str) -> bool:
        return name in self._tables

    def get(self, name: str) -> TableDef:
        return self._tables[name]

    def list(self) -> List[TableDef]:
        return list(self._tables.values())


class ReplicaRegistry:
    def __init__(self, ttl_sec: float = 30.0):
        self.ttl_sec = ttl_sec
        self._replicas: Dict[str, Dict[str, ReplicaInfo]] = {}
        self._leader_url: Dict[str, str] = {}
        self._rr_idx: Dict[str, int] = {}

    def register(self, shard_name: str, replica_url: str, replica_id: str | None, requested_role: str):
        now = time.time()
        replica_url = replica_url.rstrip("/")

        self._replicas.setdefault(shard_name, {})
        prev = self._replicas[shard_name].get(replica_url)

        leader = self._leader_url.get(shard_name)
        if leader and not self._is_active(shard_name, leader):
            self._leader_url.pop(shard_name, None)
            leader = None

        if leader is None:
            assigned_role = "leader"
            self._leader_url[shard_name] = replica_url
        else:
            assigned_role = "follower"

        if requested_role == "leader" and leader is None:
            assigned_role = "leader"
            self._leader_url[shard_name] = replica_url

        if prev and prev.role == "leader" and self._leader_url.get(shard_name) == replica_url:
            assigned_role = "leader"

        info = ReplicaInfo(
            shard_name=shard_name,
            replica_url=replica_url,
            replica_id=replica_id,
            role=assigned_role,
            last_seen_unix=now,
        )
        self._replicas[shard_name][replica_url] = info

        # Ensure leader replica entry role is correct
        lurl = self._leader_url.get(shard_name)
        if lurl and lurl in self._replicas[shard_name]:
            leader_info = self._replicas[shard_name][lurl]
            self._replicas[shard_name][lurl] = leader_info.model_copy(update={"role": "leader"})

        return assigned_role, self._leader_url[shard_name]

    def leader_url(self, shard_name: str) -> Optional[str]:
        l = self._leader_url.get(shard_name)
        if l and self._is_active(shard_name, l):
            return l
        return None

    def active_replicas(self, shard_name: str) -> List[ReplicaInfo]:
        items = list(self._replicas.get(shard_name, {}).values())
        now = time.time()
        return [r for r in items if (now - r.last_seen_unix) <= self.ttl_sec]

    def pick_read_replica(self, shard_name: str) -> Optional[str]:
        reps = self.active_replicas(shard_name)
        if not reps:
            return None
        i = self._rr_idx.get(shard_name, 0) % len(reps)
        self._rr_idx[shard_name] = i + 1
        return reps[i].replica_url

    def list_all(self) -> List[ReplicaInfo]:
        out: List[ReplicaInfo] = []
        for shard_name in self._replicas:
            out.extend(self._replicas[shard_name].values())
        return out

    def _is_active(self, shard_name: str, url: str) -> bool:
        info = self._replicas.get(shard_name, {}).get(url)
        if not info:
            return False
        return (time.time() - info.last_seen_unix) <= self.ttl_sec
