from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


TestingPipelineStatus = Literal["created", "running", "completed", "failed", "blocked_manual_fix", "canceled"]


class TestingTaskRead(BaseModel):
    slug: str
    issue_key: str
    title: str
    description: str
    expected_touched_paths: list[str] = Field(default_factory=list)
    expected_acceptance_criteria: list[str] = Field(default_factory=list)
    expected_outcome: str
    expected_branch_name: str


class TestingRunSummaryRead(BaseModel):
    id: str
    task_slug: str
    status: str
    created_at: str
    completed_at: str | None = None
    score: float | None = None


class TestingPipelineEventRead(BaseModel):
    timestamp: str
    type: str
    task: str | None = None
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class TestingPipelineTaskResultRead(BaseModel):
    task_slug: str
    issue_key: str
    run_id: str | None = None
    status: str
    expected_outcome: str
    actual_outcome: str
    evaluator_score: float | None = None
    summary: str = ""
    branch_name: str = ""
    changed_paths: list[str] = Field(default_factory=list)
    git_commit_sha: str = ""
    pr_url: str = ""


class TestingPipelineIterationRead(BaseModel):
    iteration: int
    task_results: list[TestingPipelineTaskResultRead] = Field(default_factory=list)
    apply_result_path: str = ""
    git_commit_sha: str = ""


class TestingPipelineSummaryRead(BaseModel):
    pipeline_id: str
    status: TestingPipelineStatus
    stage: str
    target_score: float
    max_iterations: int
    current_iteration: int = 0
    branch_name: str = ""
    latest_evaluator_score: float | None = None
    latest_task_slug: str = ""
    stop_reason: str = ""
    task_slugs: list[str] = Field(default_factory=list)
    updated_at: str


class TestingPipelineRead(TestingPipelineSummaryRead):
    iterations: list[TestingPipelineIterationRead] = Field(default_factory=list)


class TestingPipelineEnvelope(BaseModel):
    payload: TestingPipelineRead


class TestingPipelineStartRequest(BaseModel):
    task_slugs: list[str] = Field(default_factory=list)
    target_score: float = 8
    max_iterations: int = 5
    review_model: str = ""
    fixer_model: str = ""
    require_manual_approval: bool = False
    skip_fixture_reset: bool = True


class TestingDeliverableFileRead(BaseModel):
    exists: bool
    filename: str


class TestingDeliverablesRead(BaseModel):
    files: dict[str, TestingDeliverableFileRead] = Field(default_factory=dict)
