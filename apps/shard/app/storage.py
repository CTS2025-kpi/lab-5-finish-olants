from __future__ import annotations
from typing import Dict, Tuple, Optional, Any

class InMemoryShardStore:
    def __init__(self):
        self._tables: Dict[str, Dict[Tuple[str, str], dict]] = {}

    def put(self, table: str, pk: str, sk: str, value: dict, version: int, origin: str) -> None:
        t = self._tables.setdefault(table, {})
        cur = t.get((pk, sk))
        # if cur is None or version > cur["version"]:
        #     t[(pk, sk)] = {"value": value, "version": version, "deleted": False}
        if cur is None or (version, origin) > (cur["version"], cur.get("origin","")):
            t[(pk, sk)] = {"value": value, "version": version, "origin": origin, "deleted": False}


    # def delete(self, table: str, pk: str, sk: str, version: int) -> Optional[dict]:
    def delete(self, table: str, pk: str, sk: str, version: int, origin: str) -> Optional[dict]:
        t = self._tables.setdefault(table, {})
        cur = t.get((pk, sk))
        # if cur is None or version > cur["version"]:
        if cur is None or (version, origin) > (cur["version"], cur.get("origin","")):
            prev_val = None if cur is None else (None if cur["deleted"] else cur["value"])
            # t[(pk, sk)] = {"value": {}, "version": version, "deleted": True}
            t[(pk, sk)] = {"value": {}, "version": version, "origin": origin, "deleted": True}
            return prev_val
        # delete older than current -> ignore
        return None if cur is None else (None if cur["deleted"] else cur["value"])

    def get(self, table: str, pk: str, sk: str) -> Optional[dict]:
        cur = self._tables.get(table, {}).get((pk, sk))
        if not cur or cur["deleted"]:
            return None
        return cur["value"]

    # def get_with_version(self, table: str, pk: str, sk: str) -> tuple[Optional[dict], Optional[int]]:
    def get_with_version(self, table: str, pk: str, sk: str) -> tuple[Optional[dict], Optional[int], Optional[str]]:
        cur = self._tables.get(table, {}).get((pk, sk))
        if not cur or cur["deleted"]:
        #     return None, cur["version"] if cur else None
        # return cur["value"], cur["version"]
            return None, (cur["version"] if cur else None), (cur.get("origin") if cur else None)
        return cur["value"], cur["version"], cur.get("origin")

    def exists(self, table: str, pk: str, sk: str) -> bool:
        cur = self._tables.get(table, {}).get((pk, sk))
        return bool(cur) and not cur["deleted"]

    def iter_records(self):
        # yields (table, pk, sk, value, version, origin, deleted)
        for table, items in self._tables.items():
            for (pk, sk), cur in items.items():
                yield (table, pk, sk, cur.get("value", {}), cur.get("version"), cur.get("origin"), cur.get("deleted", False))

    def stats(self) -> dict:
        out = {}
        total = 0
        for table, items in self._tables.items():
            alive = sum(1 for v in items.values() if not v.get("deleted", False))
            out[table] = alive
            total += alive
        return {"tables": out, "total_keys": total}

