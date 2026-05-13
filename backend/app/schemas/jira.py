from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class JiraWebhookResponse(BaseModel):
    accepted: bool
    message: str
    issue_key: str | None = None
    queued: bool = False
    duplicate: bool = False
    pipeline_id: str | None = None


class JiraManualRunRequest(BaseModel):
    force: bool = False


class JiraIssueSyncRequest(BaseModel):
    jql: str | None = None
    max_results: int = 25


class JiraIssueLinkRead(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class JiraIssueListRead(BaseModel):
    payload: list[dict[str, Any]] = Field(default_factory=list)


class JiraPlanRequest(BaseModel):
    refresh_from_jira: bool = True


class JiraPlannedChange(BaseModel):
    file_path: str
    rationale: str


class JiraPlanResponse(BaseModel):
    issue_key: str
    summary: str
    implementation_steps: list[str] = Field(default_factory=list)
    planned_changes: list[JiraPlannedChange] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
