from __future__ import annotations
import threading, time, requests
from typing import Dict, List, Optional, Tuple
from .ring import ConsistentHashRing, RingNode
from .storage import ReplicaRegistry

class Rebalancer:
    def __init__(self, *, ring: ConsistentHashRing, replicas: ReplicaRegistry):
        self.ring = ring
        self.replicas = replicas

        self._lock = threading.Lock()
        self._prev_ring: Optional[ConsistentHashRing] = None
        self._migrating = False

    def prev_ring(self) -> Optional[ConsistentHashRing]:
        with self._lock:
            return self._prev_ring

    def on_ring_changed(self):
        with self._lock:
            if self._migrating:
                return
            # snapshot previous ring
            prev = self._clone_ring(self.ring)
            self._prev_ring = prev
            self._migrating = True

        threading.Thread(target=self._migrate_background, daemon=True).start()

    def _clone_ring(self, src: ConsistentHashRing) -> ConsistentHashRing:
        clone = ConsistentHashRing(replicas=src.replicas)
        for n in src.nodes():
            clone.add(RingNode(url=n.url))
        return clone

    def _migrate_background(self):
        try:
            # migrate by scanning all shards in prev ring, moving keys that now map elsewhere
            prev = self.prev_ring()
            if prev is None:
                return

            shard_names = [n.url for n in prev.nodes()]
            # naive: migrate table-by-table is better, but coordinator doesn’t know tables list reliably.
            # We'll migrate only tables registered in coordinator later (you can pass list in).
            time.sleep(1)
        finally:
            with self._lock:
                self._migrating = False

    def migrate_table(self, table_name: str):
        prev = self.prev_ring()
        if prev is None:
            return

        for old_node in prev.nodes():
            old_shard = old_node.url
            old_leader = self.replicas.leader_url(old_shard)
            if not old_leader:
                continue

            try:
                dump = requests.get(f"{old_leader}/internal/dump", params={"table_name": table_name}, timeout=10).json()
                items = dump.get("items", [])
            except Exception:
                continue

            # group by destination shard
            by_dest: Dict[str, List[dict]] = {}
            for it in items:
                pk = it["pk"]
                new_node = self.ring.get(pk)
                if not new_node:
                    continue
                new_shard = new_node.url
                if new_shard != old_shard:
                    by_dest.setdefault(new_shard, []).append(it)

            # send batches
            for new_shard, batch in by_dest.items():
                new_leader = self.replicas.leader_url(new_shard)
                if not new_leader:
                    continue
                try:
                    requests.post(f"{new_leader}/internal/ingest",
                                  json={"table_name": table_name, "items": batch},
                                  timeout=20).raise_for_status()
                except Exception:
                    continue
