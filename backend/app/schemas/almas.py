from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TargetedSymbol(BaseModel):
    file_path: str
    symbol_name: str
    symbol_type: str  # "function", "class", "method", etc.
    reason: str
    line_start: int | None = None
    line_end: int | None = None
    related_symbols: list[str] = Field(default_factory=list)


class AgentTimingInfo(BaseModel):
    agent_name: str
    start_time: float
    end_time: float
    duration_seconds: float
    status: str  # "success", "error", "partial"


ALMASRunStatus = Literal[
    "created",
    "running",
    "needs_clarification",
    "needs_review_revision",
    "needs_approval",
    "approved",
    "branch_created",
    "code_generated",
    "code_applied",
    "draft_pr_opened",
    "completed",
    "blocked",
    "failed",
]

ALMASFixerDecision = Literal["approved", "needs_revision", "blocked"]
DeveloperChangeOperation = Literal["create", "update", "delete"]


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
    targeted_symbols: list[TargetedSymbol] = Field(default_factory=list)
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


class DeveloperFileChange(BaseModel):
    path: str
    operation: DeveloperChangeOperation
    content: str = ""
    change_summary: str = ""
    rationale: str = ""


class DeveloperOutput(BaseModel):
    implementation_summary: str
    branch_name: str
    commit_message: str
    changes: list[DeveloperFileChange] = Field(default_factory=list)
    validation_notes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class FileDiffPreview(BaseModel):
    path: str
    operation: DeveloperChangeOperation
    before_content: str = ""
    after_content: str = ""
    diff: str = ""


class FixerOutput(BaseModel):
    decision: ALMASFixerDecision
    fix_summary: str = ""
    approval_reasons: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    missing_checks: list[str] = Field(default_factory=list)
    security_notes: list[str] = Field(default_factory=list)
    test_gaps: list[str] = Field(default_factory=list)
    revision_requests: list[str] = Field(default_factory=list)


class GitHubBranchResult(BaseModel):
    branch_name: str
    base_branch: str
    base_sha: str
    ref: str
    created: bool = True


class GitHubApplyResult(BaseModel):
    branch_name: str
    commit_sha: str = ""
    commit_url: str = ""
    applied_changes: list[FileDiffPreview] = Field(default_factory=list)
    changed_paths: list[str] = Field(default_factory=list)
    success: bool = False


class GitHubPullRequestResult(BaseModel):
    number: int | None = None
    url: str = ""
    html_url: str = ""
    state: str = ""
    draft: bool = True
    ready_for_review: bool = False


class GitHubHandoffPackage(BaseModel):
    branch_name: str
    base_branch: str
    pr_title: str
    pr_body: str
    reviewer_summary: str
    changed_files_plan: list[str] = Field(default_factory=list)
    publish_ready: bool = True
    pr_url: str = ""
    commit_sha: str = ""


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
    branch_name: str = ""
    commit_sha: str = ""
    pr_number: int | None = None
    pr_url: str = ""
    timing_history: list[AgentTimingInfo] = Field(default_factory=list)


class ALMASRunSummaryRead(BaseModel):
    run_id: str
    issue_key: str
    status: ALMASRunStatus
    current_stage: str
    revision_count: int = 0
    updated_at: str
    explanation: str = ""
    branch_name: str = ""
    commit_sha: str = ""
    pr_number: int | None = None
    pr_url: str = ""


class ALMASRunArtifacts(BaseModel):
    jira_snapshot: dict[str, Any] | None = None
    analyzer_output: AnalyzerOutput | None = None
    planner_output: PlannerOutput | None = None
    developer_output: DeveloperOutput | None = None
    fixer_output: FixerOutput | None = None
    approval_decision: ApprovalDecision | None = None
    github_branch: GitHubBranchResult | None = None
    apply_result: GitHubApplyResult | None = None
    github_pull_request: GitHubPullRequestResult | None = None
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
