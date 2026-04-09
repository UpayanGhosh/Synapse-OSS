"""Cron job API routes for dashboard consumption (DASH-02)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from sci_fi_dashboard.middleware import _require_gateway_auth

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/api/cron/jobs",
    dependencies=[Depends(_require_gateway_auth)],
)
async def list_cron_jobs(request: Request):
    """Return all registered cron jobs with their current state."""
    svc = getattr(request.app.state, "cron_service", None)
    if svc is None:
        return JSONResponse({"jobs": [], "error": "CronService not running"})
    jobs = svc.list()
    return JSONResponse({
        "jobs": jobs,
        "count": len(jobs),
    })


@router.post(
    "/api/cron/jobs/{job_id}/run",
    dependencies=[Depends(_require_gateway_auth)],
)
async def run_cron_job(job_id: str, request: Request):
    """Force-run a specific cron job immediately."""
    svc = getattr(request.app.state, "cron_service", None)
    if svc is None:
        raise HTTPException(503, "CronService not running")
    try:
        result = await svc.run(job_id, mode="force")
        return JSONResponse(result)
    except KeyError:
        raise HTTPException(404, f"Job '{job_id}' not found")
    except Exception as exc:
        logger.exception("[Cron] Force-run failed for job %s", job_id)
        raise HTTPException(500, f"Job execution failed: {exc}")
