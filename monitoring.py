"""
Performance monitoring and metrics collection for Edgar-Text API.
"""

import time
import psutil
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Any
from dataclasses import dataclass
from logging_config import get_logger

logger = get_logger("edgar_text.monitoring")


@dataclass
class MetricPoint:
    """A single metric data point."""
    timestamp: datetime
    value: float
    labels: Dict[str, str] = None


class MetricsCollector:
    """Collects and stores application metrics."""

    def __init__(self, retention_hours: int = 24):
        self.retention_hours = retention_hours
        self.metrics: Dict[str, deque] = defaultdict(lambda: deque())
        self.counters: Dict[str, float] = defaultdict(float)
        self.gauges: Dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()

    def record_counter(self, name: str, value: float = 1.0, labels: Dict[str, str] = None) -> None:
        """Record a counter metric."""
        with self._lock:
            key = self._make_key(name, labels)
            self.counters[key] += value
            self._add_metric_point(name, value, labels)

    def record_gauge(self, name: str, value: float, labels: Dict[str, str] = None) -> None:
        """Record a gauge metric."""
        with self._lock:
            key = self._make_key(name, labels)
            self.gauges[key] = value
            self._add_metric_point(name, value, labels)

    def record_histogram(self, name: str, value: float, labels: Dict[str, str] = None) -> None:
        """Record a histogram metric (duration, size, etc.)."""
        with self._lock:
            self._add_metric_point(name, value, labels)

    def get_metrics(self, name: str = None) -> Dict[str, List[MetricPoint]]:
        """Get stored metrics, optionally filtered by name."""
        with self._lock:
            if name:
                return {name: list(self.metrics.get(name, []))}
            return {k: list(v) for k, v in self.metrics.items()}

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of current metrics."""
        with self._lock:
            now = datetime.utcnow()
            summary = {
                "timestamp": now.isoformat(),
                "counters": dict(self.counters),
                "gauges": dict(self.gauges),
                "system": self._get_system_metrics(),
            }

            # Add recent metric summaries
            for name, points in self.metrics.items():
                if points:
                    recent_points = [p for p in points if now - p.timestamp < timedelta(minutes=5)]
                    if recent_points:
                        values = [p.value for p in recent_points]
                        summary[f"{name}_recent"] = {
                            "count": len(values),
                            "avg": sum(values) / len(values),
                            "min": min(values),
                            "max": max(values),
                        }

            return summary

    def _make_key(self, name: str, labels: Dict[str, str] = None) -> str:
        """Create a unique key for a metric."""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}:{label_str}"

    def _add_metric_point(self, name: str, value: float, labels: Dict[str, str] = None) -> None:
        """Add a metric point to the time series."""
        point = MetricPoint(
            timestamp=datetime.utcnow(),
            value=value,
            labels=labels or {}
        )
        self.metrics[name].append(point)
        self._cleanup_old_metrics(name)

    def _cleanup_old_metrics(self, name: str) -> None:
        """Remove old metric points outside retention window."""
        cutoff = datetime.utcnow() - timedelta(hours=self.retention_hours)
        while self.metrics[name] and self.metrics[name][0].timestamp < cutoff:
            self.metrics[name].popleft()

    def _get_system_metrics(self) -> Dict[str, float]:
        """Get current system metrics."""
        try:
            return {
                "cpu_percent": psutil.cpu_percent(),
                "memory_percent": psutil.virtual_memory().percent,
                "memory_used_mb": psutil.virtual_memory().used / 1024 / 1024,
                "disk_percent": psutil.disk_usage("/").percent,
            }
        except Exception as e:
            logger.warning(f"Failed to collect system metrics: {e}")
            return {}


# Global metrics collector instance
metrics = MetricsCollector()


class PerformanceMonitor:
    """Context manager for monitoring operation performance."""

    def __init__(self, operation_name: str, labels: Dict[str, str] = None):
        self.operation_name = operation_name
        self.labels = labels or {}
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        metrics.record_counter(f"{self.operation_name}_started", labels=self.labels)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        metrics.record_histogram(f"{self.operation_name}_duration", duration, labels=self.labels)

        if exc_type is None:
            metrics.record_counter(f"{self.operation_name}_success", labels=self.labels)
        else:
            error_labels = {**self.labels, "error_type": exc_type.__name__}
            metrics.record_counter(f"{self.operation_name}_error", labels=error_labels)

        logger.info(
            f"Operation completed",
            extra={
                "operation": self.operation_name,
                "duration_seconds": round(duration, 3),
                "success": exc_type is None,
                "labels": self.labels,
            }
        )


def monitor_system_resources():
    """Background thread function to monitor system resources."""
    while True:
        try:
            system_metrics = metrics._get_system_metrics()
            for metric_name, value in system_metrics.items():
                metrics.record_gauge(f"system_{metric_name}", value)

            time.sleep(30)  # Update every 30 seconds
        except Exception as e:
            logger.error(f"Error in system monitoring: {e}")
            time.sleep(60)  # Wait longer if there's an error


def start_background_monitoring():
    """Start background monitoring thread."""
    monitor_thread = threading.Thread(target=monitor_system_resources, daemon=True)
    monitor_thread.start()
    logger.info("Background system monitoring started")