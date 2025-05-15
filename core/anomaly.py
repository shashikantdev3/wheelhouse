import statistics
from typing import List, Dict

# Example: Detect if a metric is an outlier (z-score > threshold)
def detect_anomalies(metrics: List[float], threshold: float = 2.5) -> List[int]:
    if len(metrics) < 2:
        return []
    mean = statistics.mean(metrics)
    stdev = statistics.stdev(metrics)
    if stdev == 0:
        return []
    anomalies = [i for i, x in enumerate(metrics) if abs((x - mean) / stdev) > threshold]
    return anomalies

# Example: Analyze a batch of server metrics
def analyze_server_metrics(server_metrics: Dict[str, List[float]]) -> Dict[str, List[int]]:
    # server_metrics: {"cpu": [...], "mem": [...], ...}
    return {metric: detect_anomalies(values) for metric, values in server_metrics.items()}

# Hook for ML-based anomaly detection (to be extended)
def ml_detect_anomalies(metrics: List[float]) -> List[int]:
    # Placeholder for ML model
    return [] 