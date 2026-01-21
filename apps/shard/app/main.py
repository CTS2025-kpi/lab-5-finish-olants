from __future__ import annotations

import os
import threading
import time
import logging
from typing import Any, Dict, Optional, List

import requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from requests import RequestException

from .models import CreateRecordRequest, RecordResponse, ExistsResponse
from .storage import InMemoryShardStore
from .register import try_register_forever, get_role, get_leader_url, get_role
from .replication import Replicator

from pydantic import BaseModel

# ---- OBS / Metrics (EMF) ----
# Expect shard/app/obs.py to be the same style as coordinator obs.py
from .obs import (
    setup_json_logging,
    get_or_create_trace_id,
    emit_http_metrics,
    trace_id_var,
    SERVICE as OBS_SERVICE,
    CLUSTER as OBS_CLUSTER,
)

PORT = int(os.getenv("PORT", "8080"))
HTTP_TIMEOUT_SEC = float(os.getenv("HTTP_TIMEOUT_SEC", "5"))
PROXY_WRITES = os.getenv("PROXY_WRITES", "true").lower() in ("1", "true", "yes")
BUILD_VERSION = os.getenv("BUILD_VERSION", "dev")
BUILD_TIME = os.getenv("BUILD_TIME", "unknown")

# For LWW tie-break across replicas
REPLICA_ID = os.getenv("REPLICA_ID", "auto")
ORIGIN = os.getenv("ORIGIN", REPLICA_ID)

logger = logging.getLogger("shard")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="Shard Node (Replicated)", version="2.0.0")
store = InMemoryShardStore()


class KeyItem(BaseModel):
    table_name: str
    pk: str
    sk: str
    value: dict
    version: int
    origin: str


class KeysDumpResponse(BaseModel):
    items: List[KeyItem]


class BulkKeysRequest(BaseModel):
    items: List[KeyItem]


# ---------- Error handling (avoid empty 500 responses) ----------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal error: {type(exc).__name__}: {exc}"},
    )


# ---------- Replication apply ----------
def apply_event(ev: Dict[str, Any]):
    """
    Apply events from replication log (consumer).
    Must use (version, origin) ordering for LWW.
    """
    try:
        op = ev.get("op")
        table = ev["table_name"]
        pk = ev["pk"]
        sk = ev["sk"]
        version = int(ev["version"])
        origin = str(ev.get("origin") or "replication")

        if op == "PUT":
            store.put(table, pk, sk, ev.get("value", {}), version=version, origin=origin)
        elif op == "DEL":
            store.delete(table, pk, sk, version=version, origin=origin)
        else:
            logger.warning("Unknown op in event: %r", op)
    except Exception:
        logger.exception("Failed to apply event: %r", ev)
        raise


replicator = Replicator(apply_event=apply_event)


@app.on_event("startup")
def _startup():
    # Setup structured logging (human logs) + trace_id
    setup_json_logging()

    threading.Thread(target=try_register_forever, daemon=True).start()
    replicator.start_publisher_thread()
    replicator.start_consumer_thread()


# ---------- Metrics middleware ----------
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    get_or_create_trace_id(request)

    start = time.perf_counter()
    status_code = 500
    try:
        resp = await call_next(request)
        status_code = resp.status_code
        return resp
    finally:
        latency_ms = (time.perf_counter() - start) * 1000.0
        emit_http_metrics(
            route=request.url.path,
            method=request.method,
            status_code=int(status_code),
            latency_ms=float(latency_ms),
            role=get_role() or "unknown",
        )


# ---------- Basic endpoints ----------
@app.get("/health")
def health():
    return {"status": "ok", "role": get_role(), "leader_url": get_leader_url()}


@app.get("/version")
def version():
    return {
        "service": "shard",
        "build_version": BUILD_VERSION,
        "build_time": BUILD_TIME,
        "origin": ORIGIN,
    }


@app.get("/stats")
def stats():
    return store.stats()


@app.get("/internal/dump")
def internal_dump(table_name: str = Query(min_length=1)):
    # Compatibility: old code expected store.dump_table(); your store.py doesn't have it.
    # We'll build dump from iter_records().
    items = []
    for (t, pk, sk, val, ver, origin, deleted) in store.iter_records():
        if t != table_name:
            continue
        items.append(
            {
                "pk": pk,
                "sk": sk,
                "value": val,
                "version": ver,
                "origin": origin,
                "deleted": deleted,
            }
        )
    return {"table_name": table_name, "items": items}


@app.post("/internal/ingest")
def internal_ingest(payload: dict):
    # payload: {"table_name": "...", "items": [ {pk,sk,value,version,origin,deleted}, ... ] }
    table = payload["table_name"]
    for it in payload.get("items", []):
        pk = it["pk"]
        sk = it["sk"]
        ver = int(it["version"])
        origin = str(it.get("origin") or "ingest")

        if it.get("deleted"):
            store.delete(table, pk, sk, version=ver, origin=origin)
        else:
            store.put(table, pk, sk, it.get("value", {}), version=ver, origin=origin)

    return {"status": "ok", "count": len(payload.get("items", []))}


# ---------- Helpers ----------
def _leader_or_503() -> str:
    leader = get_leader_url()
    if not leader:
        raise HTTPException(
            status_code=503,
            detail="No leader known yet (replica not registered or coordinator unreachable).",
        )
    return leader.rstrip("/")


def _proxy_to_leader(method: str, path: str, *, json_body: dict | None = None, params: dict | None = None) -> dict:
    leader = _leader_or_503()
    url = f"{leader}{path}"

    # Forward trace id if present
    headers = {}
    tid = trace_id_var.get()
    if tid:
        headers["x-trace-id"] = tid

    try:
        r = requests.request(
            method,
            url,
            json=json_body,
            params=params,
            timeout=HTTP_TIMEOUT_SEC,
            headers=headers,
        )
    except RequestException as e:
        raise HTTPException(status_code=502, detail=f"Leader proxy failed: {e}")

    if r.status_code >= 400:
        try:
            payload = r.json()
            detail = payload.get("detail", payload)
        except Exception:
            detail = r.text
        raise HTTPException(status_code=r.status_code, detail=f"Leader error: {detail}")

    try:
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Leader returned non-JSON response: {e}; body={r.text[:500]}")


def _publish_or_503(ev: dict):
    try:
        replicator.publish(ev)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Replication log publish failed: {type(e).__name__}: {e}",
        )


# ---------- API ----------
@app.post("/records", response_model=RecordResponse)
def create(req: CreateRecordRequest):
    role = get_role()

    # Followers: proxy or redirect
    if role != "leader":
        if not PROXY_WRITES:
            leader = _leader_or_503()
            raise HTTPException(
                status_code=307,
                detail="Redirect to leader",
                headers={"Location": f"{leader}/records"},
            )
        data = _proxy_to_leader("POST", "/records", json_body=req.model_dump())
        return RecordResponse(**data)

    # Leader: durable publish then local apply
    version = time.time_ns()
    ev = {
        "op": "PUT",
        "table_name": req.table_name,
        "pk": req.pk,
        "sk": req.sk,
        "value": req.value,
        "version": version,
        "origin": ORIGIN,
    }

    _publish_or_503(ev)
    store.put(req.table_name, req.pk, req.sk, req.value, version=version, origin=ORIGIN)

    return RecordResponse(table_name=req.table_name, pk=req.pk, sk=req.sk, value=req.value, version=version)


@app.get("/records", response_model=RecordResponse)
def read(
    table_name: str = Query(min_length=1),
    pk: str = Query(min_length=1),
    sk: str = Query(min_length=1),
):
    try:
        v, ver, _origin = store.get_with_version(table_name, pk, sk)
    except AttributeError:
        raise HTTPException(
            status_code=500,
            detail="Storage missing get_with_version(); update storage.py to Lab3 versioned store.",
        )
    if v is None:
        raise HTTPException(status_code=404, detail="Not found")
    return RecordResponse(table_name=table_name, pk=pk, sk=sk, value=v, version=ver)


@app.delete("/records", response_model=RecordResponse)
def delete(
    table_name: str = Query(min_length=1),
    pk: str = Query(min_length=1),
    sk: str = Query(min_length=1),
):
    role = get_role()

    if role != "leader":
        if not PROXY_WRITES:
            leader = _leader_or_503()
            raise HTTPException(
                status_code=307,
                detail="Redirect to leader",
                headers={"Location": f"{leader}/records"},
            )
        data = _proxy_to_leader("DELETE", "/records", params={"table_name": table_name, "pk": pk, "sk": sk})
        return RecordResponse(**data)

    version = time.time_ns()
    ev = {
        "op": "DEL",
        "table_name": table_name,
        "pk": pk,
        "sk": sk,
        "version": version,
        "origin": ORIGIN,
    }

    _publish_or_503(ev)
    prev = store.delete(table_name, pk, sk, version=version, origin=ORIGIN)
    if prev is None:
        raise HTTPException(status_code=404, detail="Not found")
    return RecordResponse(table_name=table_name, pk=pk, sk=sk, value=prev, version=version)


@app.get("/exists", response_model=ExistsResponse)
def exists(
    table_name: str = Query(min_length=1),
    pk: str = Query(min_length=1),
    sk: str = Query(min_length=1),
):
    return ExistsResponse(exists=store.exists(table_name, pk, sk))


@app.get("/internal/stats")
def internal_stats():
    return store.stats()


@app.get("/internal/keys", response_model=KeysDumpResponse)
def internal_keys(table_name: Optional[str] = None):
    items = []
    for (t, pk, sk, val, ver, origin, deleted) in store.iter_records():
        if deleted:
            continue
        if table_name and t != table_name:
            continue
        items.append(
            KeyItem(
                table_name=t,
                pk=pk,
                sk=sk,
                value=val,
                version=int(ver),
                origin=str(origin or ""),
            )
        )
    return {"items": items}


@app.post("/internal/migrate-put")
def internal_migrate_put(req: BulkKeysRequest):
    if get_role() != "leader":
        raise HTTPException(status_code=409, detail="Not leader")

    for it in req.items:
        ev = {
            "op": "PUT",
            "table_name": it.table_name,
            "pk": it.pk,
            "sk": it.sk,
            "value": it.value,
            "version": int(it.version),
            "origin": it.origin,
        }
        _publish_or_503(ev)
        store.put(it.table_name, it.pk, it.sk, it.value, version=int(it.version), origin=str(it.origin))

    return {"migrated": len(req.items)}


@app.post("/internal/migrate-del")
def internal_migrate_del(req: BulkKeysRequest):
    if get_role() != "leader":
        raise HTTPException(status_code=409, detail="Not leader")

    for it in req.items:
        ev = {
            "op": "DEL",
            "table_name": it.table_name,
            "pk": it.pk,
            "sk": it.sk,
            "version": int(it.version),
            "origin": it.origin,
        }
        _publish_or_503(ev)
        store.delete(it.table_name, it.pk, it.sk, version=int(it.version), origin=str(it.origin))

    return {"deleted": len(req.items)}


def main():
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=PORT,
        log_level=os.getenv("LOG_LEVEL", "debug").lower(),
    )


if __name__ == "__main__":
    main()
