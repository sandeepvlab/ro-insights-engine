import json
import os
import time
import uuid
from datetime import datetime

LOG_DIR = "packages/observability/logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "runs.jsonl")


def new_run_id() -> str:
    return str(uuid.uuid4())


def log_event(run_id: str, ro_id: str, step: str, status: str,
              latency_ms: float = None, tokens_in: int = None,
              tokens_out: int = None, error: str = None, extra: dict = None):
    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "run_id": run_id,
        "ro_id": ro_id,
        "step": step,
        "status": status,
        "latency_ms": latency_ms,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "error": error,
        "extra": extra or {}
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(event) + "\n")


class Timer:
    """Simple context manager to measure step latency in milliseconds."""
    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = (time.time() - self.start) * 1000