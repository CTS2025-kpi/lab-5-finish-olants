import os, time, uuid, contextvars, logging, json
from fastapi import Request

trace_id_var = contextvars.ContextVar("trace_id", default=None)

SERVICE = os.getenv("SERVICE_NAME", "coordinator")
CLUSTER = os.getenv("CLUSTER_NAME", "sharded-lab")
METRICS_NS = os.getenv("METRICS_NAMESPACE", "ShardedKV")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Dedicated logger that prints ONLY raw EMF JSON (top-level) to stdout
_emf_logger = logging.getLogger("emf")
_emf_logger.setLevel(LOG_LEVEL)
_emf_logger.propagate = False
if not _emf_logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(message)s"))
    _emf_logger.addHandler(h)

def setup_json_logging():
    """
    Normal structured logs (for humans + trace_id), separate from EMF logger above.
    """
    from pythonjsonlogger import jsonlogger  # keep this for normal logs

    root = logging.getLogger()
    root.setLevel(LOG_LEVEL)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler()
    fmt = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(trace_id)s"
    )
    handler.setFormatter(fmt)
    root.addHandler(handler)

    class TraceFilter(logging.Filter):
        def filter(self, record):
            record.trace_id = trace_id_var.get() or "-"
            return True

    root.addFilter(TraceFilter())

def get_or_create_trace_id(request: Request) -> str:
    tid = request.headers.get("x-trace-id") or request.headers.get("x-request-id")
    if not tid:
        tid = uuid.uuid4().hex
    trace_id_var.set(tid)
    return tid

def current_trace_id() -> str:
    return trace_id_var.get() or ""

def _emit_emf(dimensions: dict, metrics: list[tuple[str, str]], values: dict):
    """
    Emit ONE EMF event as a single JSON line (top-level _aws object).
    """
    ts = int(time.time() * 1000)
    dim_keys = list(dimensions.keys())

    emf = {
        "_aws": {
            "Timestamp": ts,
            "CloudWatchMetrics": [{
                "Namespace": METRICS_NS,
                "Dimensions": [dim_keys],
                "Metrics": [{"Name": n, "Unit": u} for n, u in metrics],
            }]
        },
        **dimensions,
        **values,
    }
    _emf_logger.info(json.dumps(emf, separators=(",", ":"), ensure_ascii=False))

def emit_http_metrics(*, route: str, method: str, status_code: int, latency_ms: float):
    dims = {
        "Cluster": CLUSTER,
        "Service": SERVICE,
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
    _emit_emf(dims, mets, vals)

def emit_gauge(*, name: str, value: float, dims: dict):
    dimensions = {"Cluster": CLUSTER, "Service": SERVICE, **(dims or {})}
    _emit_emf(dimensions, [(name, "Count")], {name: float(value)})
