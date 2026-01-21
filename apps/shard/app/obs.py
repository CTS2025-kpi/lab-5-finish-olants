# apps/shard/app/obs.py
from __future__ import annotations

import os
import time
import uuid
import contextvars
import logging
import json
from fastapi import Request

trace_id_var = contextvars.ContextVar("trace_id", default=None)

SERVICE = os.getenv("SERVICE_NAME", "shard")
CLUSTER = os.getenv("CLUSTER_NAME", "sharded-lab")
METRICS_NS = os.getenv("METRICS_NAMESPACE", "ShardedKV")
SHARD_NAME = os.getenv("SHARD_NAME", "unknown")
REPLICA_ID = os.getenv("REPLICA_ID", os.getenv("HOSTNAME", "auto"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ---------------------------------------------------------------------
# EMF logger: MUST output raw JSON lines (no jsonlogger formatting),
# otherwise CloudWatch won't extract metrics from logs.
# ---------------------------------------------------------------------
_emf_logger = logging.getLogger("emf")
_emf_logger.setLevel(LOG_LEVEL)
_emf_logger.propagate = False
if not _emf_logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(message)s"))  # raw JSON only
    _emf_logger.addHandler(_h)


def setup_json_logging():
    """
    Structured app logs with trace_id. This is separate from EMF.
    """
    from pythonjsonlogger import jsonlogger

    root = logging.getLogger()
    root.setLevel(LOG_LEVEL)

    # Remove existing handlers to avoid duplicate logs
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler()
    fmt = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s %(trace_id)s")
    handler.setFormatter(fmt)
    root.addHandler(handler)

    class TraceFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            record.trace_id = trace_id_var.get() or "-"
            return True

    root.addFilter(TraceFilter)


def get_or_create_trace_id(request: Request) -> str:
    tid = request.headers.get("x-trace-id") or request.headers.get("x-request-id")
    if not tid:
        tid = uuid.uuid4().hex
    trace_id_var.set(tid)
    return tid


def current_trace_id() -> str:
    return trace_id_var.get() or ""


# ---------------------------------------------------------------------
# EMF emit helper
# ---------------------------------------------------------------------
def _emit_emf(*, dimensions: dict, metrics: list[tuple[str, str]], values: dict, dimension_sets: list[list[str]]):
    """
    Emit ONE EMF event and publish the same metric values under multiple dimension sets.
    """
    ts = int(time.time() * 1000)

    emf = {
        "_aws": {
            "Timestamp": ts,
            "CloudWatchMetrics": [{
                "Namespace": METRICS_NS,
                "Dimensions": dimension_sets,
                "Metrics": [{"Name": n, "Unit": u} for n, u in metrics],
            }]
        },
        **dimensions,
        **values,
    }

    # IMPORTANT: This must be a plain JSON log line (top-level EMF object).
    _emf_logger.info(json.dumps(emf, separators=(",", ":"), ensure_ascii=False))


# ---------------------------------------------------------------------
# Metrics emitters
# ---------------------------------------------------------------------
def emit_http_metrics(
    *,
    route: str,
    method: str,
    status_code: int,
    latency_ms: float,
    role: str = "unknown",
    shard: str | None = None,
    replica: str | None = None,
):
    shard = shard or SHARD_NAME
    replica = replica or REPLICA_ID

    # Include ALL keys used by ANY dimension set.
    dims_all = {
        "Cluster": CLUSTER,
        "Service": SERVICE,
        "Shard": shard,
        "Replica": replica,
        "Role": role,
        "Route": route,
        "Method": method,
    }

    vals = {
        "RequestLatencyMs": float(latency_ms),
        "RequestCount": 1.0,
        "Request4xx": 1.0 if 400 <= status_code < 500 else 0.0,
        "Request5xx": 1.0 if status_code >= 500 else 0.0,
    }

    mets = [
        ("RequestLatencyMs", "Milliseconds"),
        ("RequestCount", "Count"),
        ("Request4xx", "Count"),
        ("Request5xx", "Count"),
    ]

    # Publish under:
    #  - Cluster+Service (global shard rollups, dashboards)
    #  - Cluster+Service+Shard (your autoscaling alarm dimensions)
    #  - Detailed per-route/per-method (debugging)
    dimension_sets = [
        ["Cluster", "Service"],
        ["Cluster", "Service", "Shard"],
        ["Cluster", "Service", "Shard", "Replica", "Role", "Route", "Method"],
    ]

    _emit_emf(dimensions=dims_all, metrics=mets, values=vals, dimension_sets=dimension_sets)


def emit_replication_lag(*, lag_ms: float, role: str = "unknown", shard: str | None = None, replica: str | None = None):
    shard = shard or SHARD_NAME
    replica = replica or REPLICA_ID

    dims_all = {
        "Cluster": CLUSTER,
        "Service": SERVICE,
        "Shard": shard,
        "Replica": replica,
        "Role": role,
    }

    mets = [("ReplicationLagMs", "Milliseconds")]
    vals = {"ReplicationLagMs": float(lag_ms)}

    dimension_sets = [
        ["Cluster", "Service"],                 # matches alerts.tf replication_lag (cluster-wide)
        ["Cluster", "Service", "Shard"],        # matches per-shard lag widgets/alarms
        ["Cluster", "Service", "Shard", "Replica", "Role"],  # debugging
    ]

    _emit_emf(dimensions=dims_all, metrics=mets, values=vals, dimension_sets=dimension_sets)


def emit_heartbeat(*, role: str = "unknown", shard: str | None = None, replica: str | None = None):
    shard = shard or SHARD_NAME
    replica = replica or REPLICA_ID

    dims_all = {
        "Cluster": CLUSTER,
        "Service": SERVICE,
        "Shard": shard,
        "Replica": replica,
        "Role": role,
    }

    mets = [("Heartbeat", "Count")]
    vals = {"Heartbeat": 1.0}

    dimension_sets = [
        ["Cluster", "Service"],                 # if you ever want cluster-wide heartbeat
        ["Cluster", "Service", "Shard"],        # matches your heartbeat alarms
        ["Cluster", "Service", "Shard", "Replica", "Role"],  # debugging
    ]

    _emit_emf(dimensions=dims_all, metrics=mets, values=vals, dimension_sets=dimension_sets)
