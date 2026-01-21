from __future__ import annotations
import json, time, os
from typing import Any, Dict

NAMESPACE = os.getenv("METRICS_NAMESPACE", "Lab5/Metrics")
SERVICE = os.getenv("SERVICE_NAME", "coordinator")

def emit_latency(*, shard_name: str, operation: str, latency_ms: float, status_code: int):
    payload: Dict[str, Any] = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": NAMESPACE,
                "Dimensions": [["Service", "ShardName", "Operation"]],
                "Metrics": [
                    {"Name": "LatencyMs", "Unit": "Milliseconds"},
                    {"Name": "Errors", "Unit": "Count"},
                ],
            }],
        },
        "Service": SERVICE,
        "ShardName": shard_name,
        "Operation": operation,
        "LatencyMs": float(latency_ms),
        "Errors": 1.0 if status_code >= 500 else 0.0,
    }
    print(json.dumps(payload))
