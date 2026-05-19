from __future__ import annotations

import unittest

from app.config import Settings
from app.schemas.almas import DeveloperFileChange, DeveloperOutput, FileDiffPreview, PlannerOutput
from app.services.almas.github_adapter import GitHubApiAdapter


class RecordingGitHubAdapter(GitHubApiAdapter):
    def __init__(self) -> None:
        super().__init__(Settings(github_token="token", github_repo="owner/repo"))
        self.requests: list[tuple[str, str, dict | None]] = []

    def _get_ref_sha(self, branch_name: str) -> str:  # type: ignore[override]
        return "base-sha" if branch_name == "main" else "head-sha"

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:  # type: ignore[override]
        self.requests.append((method, path, payload))
        if path == "/git/refs":
            return {"ref": "refs/heads/feature/SDLC-1-seat-preference"}
        if path == "/git/commits/head-sha":
            return {"tree": {"sha": "tree-base"}}
        if path == "/git/blobs":
            return {"sha": "blob-sha"}
        if path == "/git/trees":
            return {"sha": "tree-new"}
        if path == "/git/commits":
            return {"sha": "commit-sha", "url": "https://example.test/commit/commit-sha"}
        if path.startswith("/git/refs/heads/"):
            return {"ref": path}
        if path == "/pulls":
            return {
                "number": 12,
                "url": "https://api.github.test/pr/12",
                "html_url": "https://github.test/pr/12",
                "state": "open",
                "draft": True,
            }
        if path == "/pulls/12/ready_for_review":
            return {
                "number": 12,
                "url": "https://api.github.test/pr/12",
                "html_url": "https://github.test/pr/12",
                "state": "open",
                "draft": False,
            }
        return {}


class GitHubAdapterTests(unittest.TestCase):
    def test_create_branch_and_apply_changes(self) -> None:
        adapter = RecordingGitHubAdapter()
        branch = adapter.create_branch(issue_key="SDLC-1", run_id="run-1", branch_name="feature/SDLC-1-seat-preference")
        self.assertEqual(branch.base_sha, "base-sha")

        developer_output = DeveloperOutput(
            implementation_summary="summary",
            branch_name=branch.branch_name,
            commit_message="Implement seat preference",
            changes=[
                DeveloperFileChange(
                    path="app/services/booking_service.py",
                    operation="update",
                    content="print('updated')\n",
                    change_summary="Update logic",
                    rationale="Needed",
                )
            ],
        )
        previews = [
            FileDiffPreview(
                path="app/services/booking_service.py",
                operation="update",
                before_content="print('old')\n",
                after_content="print('updated')\n",
                diff="--- a\n+++ b",
            )
        ]
        apply_result = adapter.apply_changes(
            issue_key="SDLC-1",
            run_id="run-1",
            branch_name=branch.branch_name,
            developer_output=developer_output,
            diff_previews=previews,
        )
        self.assertTrue(apply_result.success)
        self.assertEqual(apply_result.commit_sha, "commit-sha")
        self.assertEqual(apply_result.changed_paths, ["app/services/booking_service.py"])

        planner = PlannerOutput(
            solution_summary="summary",
            implementation_steps=["step"],
            planned_changes=[],
            patch_strategy="strategy",
            validation_steps=[],
            branch_name=branch.branch_name,
            pr_title="Title",
            pr_body="Body",
            risks=[],
            assumptions=[],
        )
        pull_request = adapter.open_draft_pr(
            issue_key="SDLC-1",
            run_id="run-1",
            implementation=planner,
            apply_result=apply_result,
        )
        self.assertEqual(pull_request.number, 12)
        ready = adapter.mark_pr_ready_for_review(issue_key="SDLC-1", run_id="run-1", pull_request=pull_request)
        self.assertTrue(ready.ready_for_review)


if __name__ == "__main__":
    unittest.main()
