from __future__ import annotations

from functools import lru_cache
import logging
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from app.config import get_settings
from app.services.almas import ALMASSupervisor
from app.schemas.jira import (
    JiraIssueLinkRead,
    JiraIssueListRead,
    JiraIssueSyncRequest,
    JiraManualRunRequest,
    JiraWebhookResponse,
    JiraPlanRequest,
    JiraPlanResponse,
)
from app.services.jira_service import JiraApiError, JiraPipelineService
from app.services.jira_service import JiraIssueAnalysis


router = APIRouter(prefix="/jira", tags=["jira"])
service = JiraPipelineService()
logger = logging.getLogger("app.jira")


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


def _validate_webhook_token(x_jira_webhook_token: str | None) -> None:
    settings = get_settings()
    if not settings.jira_webhook_token:
        raise HTTPException(status_code=503, detail="Jira webhook token is not configured.")
    if x_jira_webhook_token != settings.jira_webhook_token:
        raise HTTPException(status_code=403, detail="Invalid Jira webhook token.")


@router.post("/webhook", response_model=JiraWebhookResponse)
def receive_jira_webhook(
    payload: dict[str, Any],
    x_jira_webhook_token: str | None = Header(default=None),
) -> JiraWebhookResponse:
    _validate_jira_enabled()
    _validate_webhook_token(x_jira_webhook_token)
    issue = payload.get("issue")
    if not isinstance(issue, dict):
        raise HTTPException(status_code=422, detail="Jira webhook payload is missing the issue object.")
    result = service.enqueue_issue(issue, source="webhook", force=False)
    return JiraWebhookResponse(**result)


@router.post("/issues/{issue_key}/run", response_model=JiraWebhookResponse)
def run_jira_issue(issue_key: str, request: JiraManualRunRequest) -> JiraWebhookResponse:
    _validate_jira_enabled()
    try:
        issue_payload = service.create_client().get_issue(issue_key)
    except JiraApiError as exc:
        logger.exception("Jira issue fetch failed for %s", issue_key)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    result = service.enqueue_issue(issue_payload, source="manual", force=request.force)
    return JiraWebhookResponse(**result)


@router.post("/issues/sync", response_model=JiraIssueListRead)
def sync_jira_issues(request: JiraIssueSyncRequest) -> JiraIssueListRead:
    _validate_jira_enabled()
    try:
        payload = service.sync_issues(jql=request.jql, max_results=request.max_results)
    except JiraApiError as exc:
        logger.exception("Jira sync failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return JiraIssueListRead(payload=payload)


@router.get("/issues", response_model=JiraIssueListRead)
def list_jira_issues() -> JiraIssueListRead:
    _validate_jira_enabled()
    payload = service.list_issue_links()
    return JiraIssueListRead(payload=payload)


@router.get("/issues/{issue_key}", response_model=JiraIssueLinkRead)
def get_jira_issue(issue_key: str) -> JiraIssueLinkRead:
    _validate_jira_enabled()
    payload = service.get_issue_link(issue_key)
    return JiraIssueLinkRead(payload=payload)


@router.post("/issues/{issue_key}/plan", response_model=JiraPlanResponse)
def plan_jira_issue(issue_key: str, request: JiraPlanRequest) -> JiraPlanResponse:
    _validate_jira_enabled()
    supervisor = _get_supervisor()
    started_at = time.perf_counter()
    logger.info(
        "Jira plan generation requested | issue_key=%s refresh_from_jira=%s",
        issue_key,
        request.refresh_from_jira,
    )
    if not request.refresh_from_jira:
        stored = service.get_issue_link(issue_key).get("analysis")
        if not isinstance(stored, dict):
            raise HTTPException(status_code=404, detail=f"No synced issue found for '{issue_key}'.")
        try:
            implementation = supervisor.preview_implementation_for_analysis(JiraIssueAnalysis(**stored))
        except ValueError as exc:
            logger.warning("Jira plan generation blocked for %s using stored analysis: %s", issue_key, exc)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            logger.exception("Jira plan generation failed for %s using stored analysis", issue_key)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    else:
        try:
            implementation = supervisor.preview_implementation(issue_key)
        except ValueError as exc:
            logger.warning("Jira plan generation blocked for %s: %s", issue_key, exc)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            logger.exception("Jira plan generation failed for %s", issue_key)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except JiraApiError as exc:
            logger.exception("Jira plan issue fetch failed for %s", issue_key)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
    logger.info(
        "Jira plan generation completed | issue_key=%s duration_ms=%s steps=%s planned_changes=%s",
        issue_key,
        elapsed_ms,
        len(implementation.implementation_steps),
        len(implementation.planned_changes),
    )
    return JiraPlanResponse(
        issue_key=issue_key.upper(),
        summary=implementation.solution_summary,
        implementation_steps=implementation.implementation_steps,
        planned_changes=[
            {
                "file_path": change.file_path,
                "rationale": change.rationale,
            }
            for change in implementation.planned_changes
        ],
        validation_steps=implementation.validation_steps,
        assumptions=implementation.assumptions,
        risks=implementation.risks,
    )
