from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, List
from core.anomaly import analyze_server_metrics

router = APIRouter()

class MetricsRequest(BaseModel):
    server_metrics: Dict[str, List[float]]

@router.post("/anomaly-report")
def anomaly_report(req: MetricsRequest):
    anomalies = analyze_server_metrics(req.server_metrics)
    return {"anomalies": anomalies} 