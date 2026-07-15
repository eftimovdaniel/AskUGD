from __future__ import annotations
import contextvars
import json
import logging
import threading
import time

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

class JsonFormatter(logging.Formatter):
    def format (self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "msg":record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)
    
def setup_logging (level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler = setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handle = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True

class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests = 0
        self.errors = 0
        self._latency_sum = 0.0

    def record (self, duration_s: float, error: bool = False) -> None:
        with self._lock:
            self.requests += 1
            self._latency_sum += duration_s
            if error: 
                self.errors +=1
    
    def snapshot(self)->dict:
        with self._lock:
            avg = self._latency_sum / self.requests if self.requests else 0.0
            return{
                "requests": self.requests,
                "errors": self.errors,
                "avg_latency_ms": round(avg * 1000, 1),
            }
metrics = Metrics()

class Timer:
    def __enter__(self) -> "Timer":
        self.start = time.perf_counter()
        return self
    def __exit__(self, *exc) -> None:
        self.duration = time.perf_counter() - self.start