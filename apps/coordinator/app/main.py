# apps/coordinator/app/main.py
from __future__ import annotations

import os
import time
import logging
import threading
from typing import Dict, List, Optional

import requests
from fastapi import FastAPI, HTTPException, Query, Request

from .models import (
    TableDef,
    CreateRecordRequest,
    RecordResponse,
    ExistsResponse,
    RegisterReplicaRequest,
    RegisterReplicaResponse,
    ReplicaInfo,
)
from .ring import ConsistentHashRing, RingNode
from .storage import TableRegistry, ReplicaRegistry
from .obs import (
    setup_json_logging,
    get_or_create_trace_id,
    current_trace_id,
    emit_http_metrics,
    emit_gauge,
)

PORT = int(os.getenv("PORT", "8080"))
RING_REPLICAS = int(os.getenv("RING_REPLICAS", "128"))
REPLICA_TTL_SEC = float(os.getenv("REPLICA_TTL_SEC", "30"))
REQ_TIMEOUT_SEC = float(os.getenv("REQ_TIMEOUT_SEC", "2.0"))
BUILD_VERSION = os.getenv("BUILD_VERSION", "dev")

app = FastAPI(title="Sharded KV Coordinator", version="2.0.0")
setup_json_logging()
logger = logging.getLogger("coordinator")

tables = TableRegistry()
ring = ConsistentHashRing(replicas=RING_REPLICAS)
replicas = ReplicaRegistry(ttl_sec=REPLICA_TTL_SEC)

# ---- Rebalance state ----
_migration_lock = threading.Lock()
_migration_in_progress: bool = False
_old_ring: ConsistentHashRing | None = None


# -------------------- Helpers --------------------
def _require_table(table_name: str):
    if not tables.exists(table_name):
        raise HTTPException(status_code=404, detail="Table not registered. Call POST /tables first.")


def _pick_shard_name(pk_value: str) -> str:
    node = ring.get(pk_value)
    if node is None:
        raise HTTPException(status_code=503, detail="No shards registered")
    return node.url  # shard_name


def _pick_shard_name_from_ring(r: ConsistentHashRing, pk_value: str) -> str:
    node = r.get(pk_value)
    if node is None:
        raise HTTPException(status_code=503, detail="No shards registered")
    return node.url


def _leader_url(shard_name: str) -> str:
    url = replicas.leader_url(shard_name)
    if not url:
        raise HTTPException(status_code=503, detail=f"No leader available for shard {shard_name}")
    return url


def _read_url(shard_name: str) -> str:
    url = replicas.pick_read_replica(shard_name)
    if not url:
        raise HTTPException(status_code=503, detail=f"No active replicas for shard {shard_name}")
    return url


def _compute_shard_distribution_percent() -> dict[str, float]:
    # distribution of virtual nodes in the ring
    counts: dict[str, int] = {}
    total = len(ring._ring)  # OK here: ring internals used only for gauges
    if total == 0:
        return {}
    for n in ring._ring.values():
        counts[n.url] = counts.get(n.url, 0) + 1
    return {k: (v * 100.0 / total) for k, v in counts.items()}


def _emit_cluster_gauges_forever():
    while True:
        try:
            shard_nodes = ring.nodes()
            emit_gauge(name="ShardsInRing", value=float(len(shard_nodes)), dims={})

            # Active replicas + leader present per shard
            shard_names = {n.url for n in shard_nodes}
            for shard_name in sorted(shard_names):
                active = replicas.active_replicas(shard_name)
                emit_gauge(name="ActiveReplicas", value=float(len(active)), dims={"Shard": shard_name})
                emit_gauge(
                    name="LeaderPresent",
                    value=(1.0 if replicas.leader_url(shard_name) else 0.0),
                    dims={"Shard": shard_name},
                )

            # Shard stored keys (ask each leader)
            for node in shard_nodes:
                shard_name = node.url
                l = replicas.leader_url(shard_name)
                if not l:
                    continue
                try:
                    st = requests.get(
                        f"{l}/internal/stats",
                        timeout=5,
                        headers={"x-trace-id": current_trace_id()},
                    ).json()
                    emit_gauge(
                        name="ShardStoredKeys",
                        value=float(st.get("total_keys", 0)),
                        dims={"Shard": shard_name},
                    )
                except Exception:
                    pass

            # Keyspace distribution based on ring virtual nodes
            dist = _compute_shard_distribution_percent()
            for shard_name, pct in dist.items():
                emit_gauge(name="ShardKeyspacePercent", value=float(pct), dims={"Shard": shard_name})
        except Exception:
            logger.exception("Failed to emit cluster gauges")
        time.sleep(10)


@app.on_event("startup")
def _startup_background_metrics():
    threading.Thread(target=_emit_cluster_gauges_forever, daemon=True).start()


# -------------------- Middleware: trace + metrics --------------------
@app.middleware("http")
async def trace_and_metrics(request: Request, call_next):
    t0 = time.perf_counter()
    tid = get_or_create_trace_id(request)
    status = 500
    try:
        resp = await call_next(request)
        status = resp.status_code
        resp.headers["x-trace-id"] = tid
        return resp
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        try:
            emit_http_metrics(
                route=request.url.path,
                method=request.method,
                status_code=int(status),
                latency_ms=float(dt_ms),
            )
        except Exception:
            logger.exception("Failed to emit metrics")


# -------------------- Rebalance / migration --------------------
def _migrate_background(old_ring: ConsistentHashRing):
    """
    Move keys that changed shard ownership after ring update.

    Rule:
      - Only migrate keys where new_owner != old_owner
      - Keep old shard serving reads until migration finishes (coordinator read fallback uses _old_ring)
      - Copy first (PUT), then delete from old shard with a NEWER tombstone version so delete actually applies (LWW)
    """
    global _migration_in_progress, _old_ring
    try:
        src_shards = [n.url for n in old_ring.nodes()]

        for src_shard in src_shards:
            src_leader = replicas.leader_url(src_shard)
            if not src_leader:
                continue

            # Pull keys from SOURCE shard leader
            r = requests.get(
                f"{src_leader}/internal/keys",
                timeout=15,
                headers={"x-trace-id": current_trace_id()},
            )
            r.raise_for_status()
            items = r.json().get("items", [])

            # Group moved items by destination shard
            buckets: Dict[str, List[dict]] = {}
            for it in items:
                pk = it["pk"]

                new_node = ring.get(pk)
                if not new_node:
                    continue
                dst_shard = new_node.url

                # migrate ONLY keys that now belong elsewhere
                if dst_shard == src_shard:
                    continue

                buckets.setdefault(dst_shard, []).append(it)

            # Execute migration: PUT -> DEL
            for dst_shard, moved in buckets.items():
                dst_leader = replicas.leader_url(dst_shard)
                if not dst_leader:
                    continue

                # 1) Copy to destination (preserve version+origin for correct LWW state there)
                requests.post(
                    f"{dst_leader}/internal/migrate-put",
                    json={"items": moved},
                    timeout=30,
                    headers={"x-trace-id": current_trace_id()},
                ).raise_for_status()

                # 2) Delete on source with NEWER version so delete wins on source (LWW)
                tomb_ver = time.time_ns()
                dels: List[dict] = []
                for it in moved:
                    dels.append(
                        {
                            "table_name": it["table_name"],
                            "pk": it["pk"],
                            "sk": it["sk"],
                            "value": it.get("value", {}),
                            "version": int(tomb_ver),
                            "origin": "migration",
                        }
                    )

                requests.post(
                    f"{src_leader}/internal/migrate-del",
                    json={"items": dels},
                    timeout=30,
                    headers={"x-trace-id": current_trace_id()},
                ).raise_for_status()

    except Exception:
        logger.exception("Migration failed")
    finally:
        with _migration_lock:
            _migration_in_progress = False
            _old_ring = None


# -------------------- API --------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tables", response_model=TableDef)
def register_table(t: TableDef):
    return tables.register(t)


@app.get("/tables", response_model=list[TableDef])
def list_tables():
    return tables.list()


@app.get("/tables/{table_name}", response_model=TableDef)
def get_table(table_name: str):
    if not tables.exists(table_name):
        raise HTTPException(status_code=404, detail="Table not found")
    return tables.get(table_name)


@app.post("/register-replica", response_model=RegisterReplicaResponse)
def register_replica(req: RegisterReplicaRequest):
    # Snapshot ring membership BEFORE any change
    before_nodes = {n.url for n in ring.nodes()}

    assigned_role, leader_url = replicas.register(
        shard_name=req.shard_name,
        replica_url=req.replica_url,
        replica_id=req.replica_id,
        requested_role=req.role,
    )

    # Only add shard to ring once it has an active leader
    if replicas.leader_url(req.shard_name) is not None:
        ring.add(RingNode(url=req.shard_name))

    after_nodes = {n.url for n in ring.nodes()}

    # If shard newly added to the ring -> start rebalance
    if (req.shard_name in after_nodes) and (req.shard_name not in before_nodes):
        prev_ring = ConsistentHashRing(replicas=RING_REPLICAS)
        for s in sorted(before_nodes):
            prev_ring.add(RingNode(url=s))

        with _migration_lock:
            global _migration_in_progress, _old_ring
            if not _migration_in_progress:
                _migration_in_progress = True
                _old_ring = prev_ring
                threading.Thread(target=_migrate_background, args=(prev_ring,), daemon=True).start()

    return RegisterReplicaResponse(
        shard_name=req.shard_name,
        assigned_role=assigned_role,
        leader_url=leader_url,
    )


@app.get("/replicas", response_model=list[ReplicaInfo])
def list_replicas():
    return replicas.list_all()


@app.post("/records", response_model=RecordResponse)
def create_record(req: CreateRecordRequest):
    _require_table(req.table_name)
    shard_name = _pick_shard_name(req.pk)
    shard = _leader_url(shard_name)

    try:
        r = requests.post(
            f"{shard}/records",
            json=req.model_dump(),
            timeout=5,
            headers={"x-trace-id": current_trace_id()},
        )
        r.raise_for_status()
        return RecordResponse(**r.json(), shard_url=shard)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Shard request failed: {e}")


@app.get("/records", response_model=RecordResponse)
def read_record(
    table_name: str = Query(min_length=1),
    pk: str = Query(min_length=1),
    sk: str = Query(min_length=1),
):
    _require_table(table_name)

    primary_shard_name = _pick_shard_name(pk)
    primary = _read_url(primary_shard_name)

    def _try(url: str):
        return requests.get(
            f"{url}/records",
            params={"table_name": table_name, "pk": pk, "sk": sk},
            timeout=5,
            headers={"x-trace-id": current_trace_id()},
        )

    try:
        r = _try(primary)

        # If not found on the new owner, during migration try old owner (serving reads until migration completes)
        if r.status_code == 404:
            with _migration_lock:
                if _migration_in_progress and _old_ring is not None:
                    old_shard_name = _pick_shard_name_from_ring(_old_ring, pk)
                    if old_shard_name != primary_shard_name:
                        fallback = _read_url(old_shard_name)
                        r2 = _try(fallback)
                        if r2.status_code != 404:
                            r2.raise_for_status()
                            return RecordResponse(**r2.json(), shard_url=fallback)

            return RecordResponse(table_name=table_name, pk=pk, sk=sk, value=None, shard_url=primary)

        r.raise_for_status()
        return RecordResponse(**r.json(), shard_url=primary)

    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Shard request failed: {e}")


@app.delete("/records", response_model=RecordResponse)
def delete_record(
    table_name: str = Query(min_length=1),
    pk: str = Query(min_length=1),
    sk: str = Query(min_length=1),
):
    _require_table(table_name)
    shard_name = _pick_shard_name(pk)
    shard = _leader_url(shard_name)

    try:
        r = requests.delete(
            f"{shard}/records",
            params={"table_name": table_name, "pk": pk, "sk": sk},
            timeout=5,
            headers={"x-trace-id": current_trace_id()},
        )
        if r.status_code == 404:
            return RecordResponse(table_name=table_name, pk=pk, sk=sk, value=None, shard_url=shard)
        r.raise_for_status()
        return RecordResponse(**r.json(), shard_url=shard)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Shard request failed: {e}")


def _exists_call(replica_url: str, table_name: str, pk: str, sk: str) -> bool:
    r = requests.get(
        f"{replica_url.rstrip('/')}/exists",
        params={"table_name": table_name, "pk": pk, "sk": sk},
        timeout=REQ_TIMEOUT_SEC,
        headers={"x-trace-id": current_trace_id()},
    )
    r.raise_for_status()
    data = r.json()
    if "exists" not in data:
        raise ValueError(f"Bad response: {data}")
    return bool(data["exists"])


@app.get("/exists", response_model=ExistsResponse)
def exists(
    table_name: str = Query(min_length=1),
    pk: str = Query(min_length=1),
    sk: str = Query(min_length=1),
):
    _require_table(table_name)

    shard_name = _pick_shard_name(pk)

    leader = replicas.leader_url(shard_name)
    if not leader:
        raise HTTPException(status_code=503, detail=f"No leader available for shard {shard_name}")

    # 1) Ask leader first (NO fallback on leader errors)
    try:
        leader_exists = _exists_call(leader, table_name, pk, sk)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"/exists failed on leader: {e}")

    if leader_exists:
        return ExistsResponse(exists=True)

    # 2) Fallback ONLY if leader explicitly said "not exists"
    for rep in replicas.active_replicas(shard_name):
        if rep.replica_url == leader:
            continue
        try:
            if _exists_call(rep.replica_url, table_name, pk, sk):
                return ExistsResponse(exists=True)
        except Exception:
            continue

    return ExistsResponse(exists=False)


@app.get("/version")
def version():
    return {"version": BUILD_VERSION}


def main():
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, log_level=os.getenv("LOG_LEVEL", "debug").lower())


if __name__ == "__main__":
    main()
