from __future__ import annotations

from abc import ABC, abstractmethod

from app.config import Settings, get_settings
from app.schemas.almas import FixerOutput, GitHubHandoffPackage, PlannerOutput


class GitHubAdapter(ABC):
    @abstractmethod
    def prepare_handoff(
        self,
        implementation: PlannerOutput,
        review_report: FixerOutput,
    ) -> GitHubHandoffPackage:
        raise NotImplementedError

    @abstractmethod
    def publish_draft_pr(self, handoff: GitHubHandoffPackage) -> dict[str, str]:
        raise NotImplementedError


class LocalGitHubAdapter(GitHubAdapter):
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def prepare_handoff(
        self,
        implementation: PlannerOutput,
        review_report: FixerOutput,
    ) -> GitHubHandoffPackage:
        reviewer_summary_parts = review_report.approval_reasons or []
        if review_report.missing_checks:
            reviewer_summary_parts.append(
                "Missing checks: " + "; ".join(review_report.missing_checks)
            )
        if review_report.test_gaps:
            reviewer_summary_parts.append(
                "Test gaps: " + "; ".join(review_report.test_gaps)
            )
        reviewer_summary = "\n".join(reviewer_summary_parts).strip() or "Fixer review completed."
        changed_files_plan = [
            f"{change.file_path}: {change.change_summary}"
            for change in implementation.planned_changes
        ]
        return GitHubHandoffPackage(
            branch_name=implementation.branch_name,
            base_branch=self._settings.github_base_branch,
            pr_title=implementation.pr_title,
            pr_body=implementation.pr_body,
            reviewer_summary=reviewer_summary,
            changed_files_plan=changed_files_plan,
            publish_ready=True,
        )

    def publish_draft_pr(self, handoff: GitHubHandoffPackage) -> dict[str, str]:
        return {
            "status": "not_published",
            "message": "Local thesis mode only. Draft PR publishing is not enabled.",
            "branch_name": handoff.branch_name,
        }
