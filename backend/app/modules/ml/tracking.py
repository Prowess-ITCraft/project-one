"""Optional experiment tracking in a self-hosted MLflow (compose profile `mlflow`, port 9606).

Off unless P1_MLFLOW_TRACKING_URI is set. Uses MLflow's REST API over httpx, so no MLflow
library is installed in the app. Tracking never blocks training: a failure is logged and the
model is still saved in the database, which stays the record.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

from app.core.config import get_settings

log = structlog.get_logger(__name__)
EXPERIMENT = "project-one"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=5.0)


def _flat(prefix: str, value: Any, out: dict[str, float]) -> None:
    if isinstance(value, bool | int | float):
        out[prefix] = float(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            _flat(f"{prefix}.{k}" if prefix else str(k), v, out)


async def log_training(
    *, kind: str, number: int, training_set: int, metrics: dict[str, Any]
) -> str | None:
    """Record one training run. Returns the MLflow run id, or None when tracking is off or
    the server could not be reached."""
    base = get_settings().mlflow_tracking_uri.rstrip("/")
    if not base:
        return None
    api = f"{base}/api/2.0/mlflow"
    try:
        async with _client() as c:
            r = await c.get(
                f"{api}/experiments/get-by-name", params={"experiment_name": EXPERIMENT}
            )
            if r.status_code == 200:
                exp_id = r.json()["experiment"]["experiment_id"]
            else:
                r = await c.post(f"{api}/experiments/create", json={"name": EXPERIMENT})
                r.raise_for_status()
                exp_id = r.json()["experiment_id"]
            now = int(time.time() * 1000)
            r = await c.post(
                f"{api}/runs/create",
                json={
                    "experiment_id": exp_id,
                    "start_time": now,
                    "run_name": f"{kind}-{number}",
                    "tags": [
                        {"key": "kind", "value": kind},
                        {"key": "model_number", "value": str(number)},
                        {"key": "training_set", "value": str(training_set)},
                    ],
                },
            )
            r.raise_for_status()
            run_id = str(r.json()["run"]["info"]["run_id"])
            flat: dict[str, float] = {}
            _flat("", metrics, flat)
            await c.post(
                f"{api}/runs/log-batch",
                json={
                    "run_id": run_id,
                    "metrics": [
                        {"key": k[:250], "value": v, "timestamp": now, "step": 0}
                        for k, v in flat.items()
                    ][:900],
                    "params": [{"key": "training_set", "value": str(training_set)}],
                },
            )
            await c.post(
                f"{api}/runs/update",
                json={"run_id": run_id, "status": "FINISHED", "end_time": now},
            )
            return run_id
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("mlflow_unreachable", error=str(exc)[:200])
        return None
