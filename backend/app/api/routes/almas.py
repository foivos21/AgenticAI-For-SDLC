from __future__ import annotations

from functools import lru_cache
import logging

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.schemas.almas import (
    ALMASApprovalRequest,
    ALMASRetryRequest,
    ALMASRunActionResponse,
    ALMASRunListRead,
    ALMASRunRead,
)
from app.services.almas import ALMASSupervisor
from app.services.jira_service import JiraApiError


router = APIRouter(prefix="/almas", tags=["almas"])
logger = logging.getLogger("app.almas")


@lru_cache
def _get_supervisor() -> ALMASSupervisor:
    return ALMASSupervisor()


def _validate_jira_enabled() -> None:
    settings = get_settings()
    if settings.jira_integration_enabled:
        return
    missing = ", ".join(settings.jira_missing_required)
    raise HTTPException(
        status_code=503,
        detail=f"Jira integration is disabled. Missing required settings: {missing}",
    )


def _log_step(stage: str, message: str) -> None:
    logger.info("[ALMAS][STEP][%s] %s", stage.upper(), message)


@router.post("/issues/{issue_key}/runs", response_model=ALMASRunActionResponse)
def start_almas_run(issue_key: str) -> ALMASRunActionResponse:
    _validate_jira_enabled()
    supervisor = _get_supervisor()
    try:
        detail = supervisor.start_run(issue_key, progress=_log_step)
    except RuntimeError as exc:
        logger.exception("ALMAS start failed for issue %s", issue_key)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except JiraApiError as exc:
        logger.exception("ALMAS Jira fetch failed for issue %s", issue_key)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    
    return ALMASRunActionResponse(
        accepted=True,
        run_id=detail.manifest.run_id,
        status=detail.manifest.status,
        message=detail.manifest.explanation or "ALMAS run started.",
        payload=detail,
    )


@router.get("/runs", response_model=ALMASRunListRead)
def list_almas_runs() -> ALMASRunListRead:
    supervisor = _get_supervisor()
    return ALMASRunListRead(payload=supervisor.list_runs())


@router.get("/runs/{run_id}", response_model=ALMASRunRead)
def get_almas_run(run_id: str) -> ALMASRunRead:
    supervisor = _get_supervisor()
    try:
        detail = supervisor.get_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"ALMAS run '{run_id}' was not found.") from exc
    return ALMASRunRead(payload=detail)


@router.post("/runs/{run_id}/approve", response_model=ALMASRunActionResponse)
def approve_almas_run(run_id: str, request: ALMASApprovalRequest) -> ALMASRunActionResponse:
    supervisor = _get_supervisor()
    try:
        detail = supervisor.approve_run(run_id, approved_by=request.approved_by, notes=request.notes)
    except RuntimeError as exc:
        logger.exception("ALMAS approval failed for run %s", run_id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"ALMAS run '{run_id}' was not found.") from exc
    except ValueError as exc:
        logger.warning("ALMAS approval rejected for run %s: %s", run_id, exc)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ALMASRunActionResponse(
        accepted=True,
        run_id=detail.manifest.run_id,
        status=detail.manifest.status,
        message=detail.manifest.explanation,
        payload=detail,
    )


@router.post("/runs/{run_id}/merge", response_model=ALMASRunActionResponse)
def merge_almas_run(run_id: str, delete_branch: bool = False) -> ALMASRunActionResponse:
    supervisor = _get_supervisor()
    try:
        result = supervisor.merge_run(run_id, delete_branch=delete_branch)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"ALMAS run '{run_id}' was not found.") from exc
    except ValueError as exc:
        logger.warning("ALMAS merge rejected for run %s: %s", run_id, exc)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.exception("ALMAS merge failed for run %s", run_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    detail = supervisor.get_run(run_id)
    return ALMASRunActionResponse(
        accepted=bool(result.get("merged")),
        run_id=run_id,
        status=detail.manifest.status,
        message=detail.manifest.explanation,
        payload=detail,
    )


@router.post("/runs/{run_id}/retry", response_model=ALMASRunActionResponse)
def retry_almas_run(run_id: str, request: ALMASRetryRequest) -> ALMASRunActionResponse:
    supervisor = _get_supervisor()
    try:
        detail = supervisor.retry_run(run_id, refresh_from_jira=request.refresh_from_jira)
    except RuntimeError as exc:
        logger.exception("ALMAS retry failed for run %s", run_id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"ALMAS run '{run_id}' was not found.") from exc
    except JiraApiError as exc:
        logger.exception("ALMAS retry Jira fetch failed for run %s", run_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ALMASRunActionResponse(
        accepted=True,
        run_id=detail.manifest.run_id,
        status=detail.manifest.status,
        message=detail.manifest.explanation,
        payload=detail,
    )


@router.get("/issues/{issue_key}/latest-run", response_model=ALMASRunRead)
def get_latest_issue_run(issue_key: str) -> ALMASRunRead:
    supervisor = _get_supervisor()
    detail = supervisor.latest_run_for_issue(issue_key)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No ALMAS run found for issue '{issue_key}'.")
    return ALMASRunRead(payload=detail)
