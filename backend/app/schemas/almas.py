from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ALMASRunStatus = Literal[
    "created",
    "running",
    "needs_clarification",
    "needs_review_revision",
    "needs_approval",
    "approved",
    "completed",
    "blocked",
    "failed",
]

ALMASFixerDecision = Literal["approved", "needs_revision", "blocked"]


class AnalyzerOutput(BaseModel):
    issue_key: str
    problem_statement: str
    goal: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    repo_summary: str = ""
    candidate_files: list[str] = Field(default_factory=list)
    selected_files: list[str] = Field(default_factory=list)
    selected_symbols: list[str] = Field(default_factory=list)
    localization_rationale: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    clarification_needed: bool = False
    blocked_reason: str = ""


class PlannerPlannedChange(BaseModel):
    file_path: str
    change_summary: str
    rationale: str


class PlannerOutput(BaseModel):
    solution_summary: str
    implementation_steps: list[str] = Field(default_factory=list)
    planned_changes: list[PlannerPlannedChange] = Field(default_factory=list)
    patch_strategy: str
    validation_steps: list[str] = Field(default_factory=list)
    branch_name: str
    pr_title: str
    pr_body: str
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class FixerOutput(BaseModel):
    decision: ALMASFixerDecision
    fix_summary: str = ""
    approval_reasons: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    missing_checks: list[str] = Field(default_factory=list)
    security_notes: list[str] = Field(default_factory=list)
    test_gaps: list[str] = Field(default_factory=list)
    revision_requests: list[str] = Field(default_factory=list)


class GitHubHandoffPackage(BaseModel):
    branch_name: str
    base_branch: str
    pr_title: str
    pr_body: str
    reviewer_summary: str
    changed_files_plan: list[str] = Field(default_factory=list)
    publish_ready: bool = True


class ApprovalDecision(BaseModel):
    approved: bool = True
    approved_by: str = "human"
    notes: str = ""
    approved_at: str


class ALMASRunManifest(BaseModel):
    run_id: str
    issue_key: str
    status: ALMASRunStatus
    current_stage: str
    revision_count: int = 0
    created_at: str
    updated_at: str
    explanation: str = ""
    model_names: dict[str, str] = Field(default_factory=dict)
    artifact_files: dict[str, str] = Field(default_factory=dict)
    latest_fixer_decision: str = ""


class ALMASRunSummaryRead(BaseModel):
    run_id: str
    issue_key: str
    status: ALMASRunStatus
    current_stage: str
    revision_count: int = 0
    updated_at: str
    explanation: str = ""


class ALMASRunArtifacts(BaseModel):
    jira_snapshot: dict[str, Any] | None = None
    analyzer_output: AnalyzerOutput | None = None
    planner_output: PlannerOutput | None = None
    fixer_output: FixerOutput | None = None
    approval_decision: ApprovalDecision | None = None
    github_handoff_package: GitHubHandoffPackage | None = None


class ALMASRunDetailRead(BaseModel):
    manifest: ALMASRunManifest
    artifacts: ALMASRunArtifacts


class ALMASRunListRead(BaseModel):
    payload: list[ALMASRunSummaryRead] = Field(default_factory=list)


class ALMASRunRead(BaseModel):
    payload: ALMASRunDetailRead


class ALMASRunActionResponse(BaseModel):
    accepted: bool
    run_id: str
    status: ALMASRunStatus
    message: str
    payload: ALMASRunDetailRead | None = None


class ALMASApprovalRequest(BaseModel):
    approved_by: str = "human"
    notes: str = ""


class ALMASRetryRequest(BaseModel):
    refresh_from_jira: bool = True
