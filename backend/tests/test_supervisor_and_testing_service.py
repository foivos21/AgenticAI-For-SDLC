from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import Settings
from app.schemas.almas import (
    AnalyzerOutput,
    DeveloperFileChange,
    DeveloperOutput,
    FileDiffPreview,
    FixerOutput,
    GitHubApplyResult,
    GitHubBranchResult,
    GitHubHandoffPackage,
    GitHubPullRequestResult,
    PlannerOutput,
    PlannerPlannedChange,
)
from app.schemas.testing import TestingPipelineStartRequest
from app.services.almas.store import ALMASRunStore
from app.services.almas.supervisor import ALMASSupervisor
from app.services.testing_service import TestingService


class FakeRepository:
    def __init__(self) -> None:
        self.files = {"app/services/booking_service.py": "print('old')\n"}

    def build_repo_context(self, issue) -> dict:
        return {"repo_summary": "backend(1)", "candidate_files": list(self.files)}

    def load_files(self, paths: list[str]) -> dict[str, str]:
        return {path: self.files.get(path, "") for path in paths}

    def read_text_file(self, path: str) -> str:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]


class FakeAgentSuite:
    def __init__(self, fixer_decisions: list[str] | None = None) -> None:
        self.repository = FakeRepository()
        self.model_names = {
            "analyzer": "analyzer-model",
            "planner": "planner-model",
            "developer": "developer-model",
            "fixer": "fixer-model",
        }
        self.fixer_decisions = fixer_decisions or ["approved"]
        self.planner_revision_requests: list[list[str]] = []
        self.developer_call_count = 0
        self.fixer_call_count = 0

    def run_analyzer(self, issue, *, run_id: str) -> AnalyzerOutput:
        return AnalyzerOutput(
            issue_key=issue.issue_key,
            problem_statement="Problem",
            goal="Goal",
            acceptance_criteria=["Criterion"],
            repo_summary="backend(1)",
            candidate_files=["app/services/booking_service.py"],
            selected_files=["app/services/booking_service.py"],
            localization_rationale=["Reason"],
            confidence=0.9,
        )

    def run_planner(self, issue, analyzer_output, *, run_id: str, branch_name: str, revision_requests=None) -> PlannerOutput:
        self.planner_revision_requests.append(list(revision_requests or []))
        return PlannerOutput(
            solution_summary="Implement seat preference",
            implementation_steps=["Update service"],
            planned_changes=[
                PlannerPlannedChange(
                    file_path="app/services/booking_service.py",
                    change_summary="Update service",
                    rationale="Needed",
                )
            ],
            patch_strategy="strategy",
            validation_steps=["Run tests"],
            branch_name=branch_name,
            pr_title="PR title",
            pr_body="PR body",
            risks=[],
            assumptions=[],
        )

    def run_developer(self, issue, analyzer_output, planner_output, *, run_id: str) -> DeveloperOutput:
        self.developer_call_count += 1
        return DeveloperOutput(
            implementation_summary="summary",
            branch_name=planner_output.branch_name,
            commit_message="Implement seat preference",
            changes=[
                DeveloperFileChange(
                    path="app/services/booking_service.py",
                    operation="update",
                    content=f"print('new-{self.developer_call_count}')\n",
                    change_summary="Update service",
                    rationale="Needed",
                )
            ],
            validation_notes=[],
            assumptions=[],
        )

    def run_fixer(self, analyzer_output, planner_output, developer_output, diff_previews, *, run_id: str, issue_key: str) -> FixerOutput:
        self.fixer_call_count += 1
        decision = self.fixer_decisions[min(self.fixer_call_count - 1, len(self.fixer_decisions) - 1)]
        return FixerOutput(
            decision=decision,
            fix_summary="Looks good" if decision == "approved" else "",
            approval_reasons=["Approved"] if decision == "approved" else [],
            rejection_reasons=["Needs another pass"] if decision == "blocked" else [],
            revision_requests=["Handle edge cases", "Add tests"] if decision == "needs_revision" else [],
        )


class FakeGitHubAdapter:
    def create_branch(self, *, issue_key: str, run_id: str, branch_name: str) -> GitHubBranchResult:
        return GitHubBranchResult(
            branch_name=branch_name,
            base_branch="main",
            base_sha="base-sha",
            ref=f"refs/heads/{branch_name}",
            created=True,
        )

    def apply_changes(self, *, issue_key: str, run_id: str, branch_name: str, developer_output: DeveloperOutput, diff_previews) -> GitHubApplyResult:
        return GitHubApplyResult(
            branch_name=branch_name,
            commit_sha="commit-sha",
            commit_url="https://example.test/commit",
            applied_changes=list(diff_previews),
            changed_paths=[item.path for item in diff_previews],
            success=True,
        )

    def open_draft_pr(self, *, issue_key: str, run_id: str, implementation: PlannerOutput, apply_result: GitHubApplyResult) -> GitHubPullRequestResult:
        return GitHubPullRequestResult(
            number=42,
            url="https://api.github.test/pr/42",
            html_url="https://github.test/pr/42",
            state="open",
            draft=True,
            ready_for_review=False,
        )

    def mark_pr_ready_for_review(self, *, issue_key: str, run_id: str, pull_request: GitHubPullRequestResult) -> GitHubPullRequestResult:
        return GitHubPullRequestResult(
            number=pull_request.number,
            url=pull_request.url,
            html_url=pull_request.html_url,
            state="open",
            draft=False,
            ready_for_review=True,
        )

    def prepare_handoff(self, implementation: PlannerOutput, apply_result: GitHubApplyResult, pull_request: GitHubPullRequestResult) -> GitHubHandoffPackage:
        return GitHubHandoffPackage(
            branch_name=implementation.branch_name,
            base_branch="main",
            pr_title=implementation.pr_title,
            pr_body=implementation.pr_body,
            reviewer_summary="Ready",
            changed_files_plan=apply_result.changed_paths,
            publish_ready=True,
            pr_url=pull_request.html_url,
            commit_sha=apply_result.commit_sha,
        )


def build_issue_payload() -> dict:
    return {
        "key": "SDLC-1",
        "fields": {
            "summary": "Booking flow should honor seat preference",
            "description": "Seat preference should be kept end-to-end.",
            "labels": [],
            "priority": {"name": "Medium"},
            "reporter": {"displayName": "Tester"},
            "created": "2026-05-01T00:00:00Z",
            "updated": "2026-05-01T00:00:00Z",
        },
    }


class SupervisorAndTestingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.settings = Settings(
            openai_api_key="test-key",
            github_token="token",
            github_repo="owner/repo",
            almas_data_dir=str(Path(self.tempdir.name) / "almas"),
            almas_repository_mode="local",
        )
        self.store = ALMASRunStore(self.settings)
        self.agent_suite = FakeAgentSuite()
        self.github_adapter = FakeGitHubAdapter()
        self.supervisor = ALMASSupervisor(
            settings=self.settings,
            agent_suite=self.agent_suite,  # type: ignore[arg-type]
            store=self.store,
            github_adapter=self.github_adapter,  # type: ignore[arg-type]
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_supervisor_transitions_to_draft_pr_and_ready_for_review(self) -> None:
        detail = self.supervisor.start_run_from_issue_payload(build_issue_payload())
        self.assertEqual(detail.manifest.status, "needs_approval")
        self.assertEqual(detail.manifest.current_stage, "draft_pr_opened")
        self.assertEqual(detail.manifest.commit_sha, "commit-sha")
        self.assertEqual(detail.manifest.pr_number, 42)
        self.assertIsNotNone(detail.artifacts.developer_output)
        self.assertIsNotNone(detail.artifacts.apply_result)
        self.assertIsNotNone(detail.artifacts.github_pull_request)

        approved = self.supervisor.approve_run(detail.manifest.run_id, approved_by="tester")
        self.assertEqual(approved.manifest.status, "completed")
        self.assertEqual(approved.manifest.current_stage, "ready_for_review")
        self.assertTrue(approved.artifacts.github_pull_request.ready_for_review)

    def test_supervisor_retries_after_fixer_revision_then_succeeds(self) -> None:
        retrying_agent_suite = FakeAgentSuite(fixer_decisions=["needs_revision", "approved"])
        supervisor = ALMASSupervisor(
            settings=self.settings,
            agent_suite=retrying_agent_suite,  # type: ignore[arg-type]
            store=self.store,
            github_adapter=self.github_adapter,  # type: ignore[arg-type]
        )

        detail = supervisor.start_run_from_issue_payload(build_issue_payload())

        self.assertEqual(detail.manifest.status, "needs_approval")
        self.assertEqual(retrying_agent_suite.developer_call_count, 2)
        self.assertEqual(retrying_agent_suite.planner_revision_requests[0], [])
        self.assertEqual(retrying_agent_suite.planner_revision_requests[1], ["Handle edge cases", "Add tests"])
        self.assertEqual(detail.manifest.revision_count, 1)

    def test_supervisor_stops_when_revision_requests_repeat(self) -> None:
        looping_agent_suite = FakeAgentSuite(fixer_decisions=["needs_revision", "needs_revision"])
        supervisor = ALMASSupervisor(
            settings=self.settings,
            agent_suite=looping_agent_suite,  # type: ignore[arg-type]
            store=self.store,
            github_adapter=self.github_adapter,  # type: ignore[arg-type]
        )

        detail = supervisor.start_run_from_issue_payload(build_issue_payload())

        self.assertEqual(detail.manifest.status, "needs_review_revision")
        self.assertIn("repeated the same revision requests", detail.manifest.explanation)
        self.assertEqual(looping_agent_suite.developer_call_count, 2)

    def test_testing_service_persists_pipeline(self) -> None:
        service = TestingService(settings=self.settings, supervisor=self.supervisor)
        envelope = service.start_pipeline(
            TestingPipelineStartRequest(
                task_slugs=["sdlc_1_seat_preference"],
                target_score=8,
                max_iterations=2,
            )
        )
        self.assertEqual(envelope.payload.pipeline_id[:9], "pipeline-")
        self.assertTrue(envelope.payload.iterations)
        events = service.get_pipeline_events(envelope.payload.pipeline_id)
        self.assertTrue(any(event.type == "evaluation_complete" for event in events))
        apply_result = service.get_pipeline_apply_result(envelope.payload.pipeline_id, 1)
        self.assertEqual(apply_result.get("commit_sha"), "commit-sha")


if __name__ == "__main__":
    unittest.main()
