from __future__ import annotations
import hashlib, bisect
from dataclasses import dataclass
from typing import Dict, List, Optional

def _hash_to_int(s: str) -> int:
    return int(hashlib.sha256(s.encode("utf-8")).hexdigest(), 16)

@dataclass(frozen=True)
class RingNode:
    url: str

class ConsistentHashRing:
    def __init__(self, replicas: int = 128):
        if replicas <= 0:
            raise ValueError("replicas must be > 0")
        self.replicas = replicas
        self._ring: Dict[int, RingNode] = {}
        self._sorted_keys: List[int] = []

    def nodes(self) -> List[RingNode]:
        seen = {}
        for n in self._ring.values():
            seen[n.url] = n
        return sorted(seen.values(), key=lambda x: x.url)

    def add(self, node: RingNode) -> None:
        if any(n.url == node.url for n in self._ring.values()):
            self.remove(node.url)
        for i in range(self.replicas):
            k = _hash_to_int(f"{node.url}#{i}")
            self._ring[k] = node
            self._sorted_keys.append(k)
        self._sorted_keys.sort()

    def remove(self, node_url: str) -> None:
        to_remove = []
        for i in range(self.replicas):
            k = _hash_to_int(f"{node_url}#{i}")
            if k in self._ring:
                to_remove.append(k)
        for k in to_remove:
            del self._ring[k]
            idx = bisect.bisect_left(self._sorted_keys, k)
            if idx < len(self._sorted_keys) and self._sorted_keys[idx] == k:
                self._sorted_keys.pop(idx)

    def get(self, key: str) -> Optional[RingNode]:
        if not self._sorted_keys:
            return None
        h = _hash_to_int(key)
        idx = bisect.bisect(self._sorted_keys, h) % len(self._sorted_keys)
        return self._ring[self._sorted_keys[idx]]
