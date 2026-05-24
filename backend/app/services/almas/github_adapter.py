from __future__ import annotations

import base64
import json
from abc import ABC, abstractmethod
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.config import Settings, get_settings
from app.schemas.almas import (
    DeveloperOutput,
    GitHubApplyResult,
    GitHubBranchResult,
    GitHubHandoffPackage,
    GitHubPullRequestResult,
    PlannerOutput,
)
from app.services.almas.logging import log_stage_payload


class GitHubAdapterError(RuntimeError):
    pass


class GitHubAdapter(ABC):
    @abstractmethod
    def create_branch(self, *, issue_key: str, run_id: str, branch_name: str) -> GitHubBranchResult:
        raise NotImplementedError

    @abstractmethod
    def delete_branch(self, *, branch_name: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def apply_changes(
        self,
        *,
        issue_key: str,
        run_id: str,
        branch_name: str,
        developer_output: DeveloperOutput,
        diff_previews,
    ) -> GitHubApplyResult:
        raise NotImplementedError

    @abstractmethod
    def open_draft_pr(
        self,
        *,
        issue_key: str,
        run_id: str,
        implementation: PlannerOutput,
        apply_result: GitHubApplyResult,
    ) -> GitHubPullRequestResult:
        raise NotImplementedError

    @abstractmethod
    def mark_pr_ready_for_review(self, *, issue_key: str, run_id: str, pull_request: GitHubPullRequestResult) -> GitHubPullRequestResult:
        raise NotImplementedError

    @abstractmethod
    def prepare_handoff(
        self,
        implementation: PlannerOutput,
        apply_result: GitHubApplyResult,
        pull_request: GitHubPullRequestResult,
    ) -> GitHubHandoffPackage:
        raise NotImplementedError


class GitHubApiAdapter(GitHubAdapter):
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._owner, self._repo = _split_repo(self._settings.github_repo)
        self._api_base = self._settings.github_api_base_url.rstrip("/")

    def create_branch(self, *, issue_key: str, run_id: str, branch_name: str) -> GitHubBranchResult:
        base_sha = self._get_ref_sha(self._settings.github_base_branch)
        payload = self._request(
            "POST",
            "/git/refs",
            {"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        )
        result = GitHubBranchResult(
            branch_name=branch_name,
            base_branch=self._settings.github_base_branch,
            base_sha=base_sha,
            ref=str(payload.get("ref") or f"refs/heads/{branch_name}"),
            created=True,
        )
        log_stage_payload(
            self._settings,
            run_id=run_id,
            issue_key=issue_key,
            agent="github",
            stage="branch_created",
            model="github-rest",
            payload=result,
        )
        return result

    def delete_branch(self, *, branch_name: str) -> None:
        try:
            self._request(
                "DELETE",
                f"/git/refs/heads/{branch_name}",
            )
        except GitHubAdapterError as exc:
            if "Reference does not exist" in str(exc) or "404" in str(exc):
                return
            raise

    def apply_changes(
        self,
        *,
        issue_key: str,
        run_id: str,
        branch_name: str,
        developer_output: DeveloperOutput,
        diff_previews,
    ) -> GitHubApplyResult:
        head_sha = self._get_ref_sha(branch_name)
        base_commit = self._request("GET", f"/git/commits/{quote(head_sha, safe='')}")
        base_tree_sha = str((base_commit.get("tree") or {}).get("sha") or "")
        if not base_tree_sha:
            raise GitHubAdapterError(f"Could not resolve base tree for branch '{branch_name}'.")

        tree_entries: list[dict[str, Any]] = []
        for change in developer_output.changes:
            if change.operation == "delete":
                tree_entries.append({"path": change.path, "mode": "100644", "type": "blob", "sha": None})
                continue
            blob_payload = self._request(
                "POST",
                "/git/blobs",
                {"content": change.content, "encoding": "utf-8"},
            )
            blob_sha = str(blob_payload.get("sha") or "")
            if not blob_sha:
                raise GitHubAdapterError(f"Could not create blob for '{change.path}'.")
            tree_entries.append(
                {"path": change.path, "mode": "100644", "type": "blob", "sha": blob_sha}
            )

        tree_payload = self._request(
            "POST",
            "/git/trees",
            {"base_tree": base_tree_sha, "tree": tree_entries},
        )
        tree_sha = str(tree_payload.get("sha") or "")
        if not tree_sha:
            raise GitHubAdapterError(f"Could not create tree for branch '{branch_name}'.")

        commit_payload = self._request(
            "POST",
            "/git/commits",
            {
                "message": developer_output.commit_message,
                "tree": tree_sha,
                "parents": [head_sha],
            },
        )
        commit_sha = str(commit_payload.get("sha") or "")
        if not commit_sha:
            raise GitHubAdapterError(f"Could not create commit for branch '{branch_name}'.")

        self._request(
            "PATCH",
            f"/git/refs/heads/{quote(branch_name, safe='')}",
            {"sha": commit_sha, "force": False},
        )
        result = GitHubApplyResult(
            branch_name=branch_name,
            commit_sha=commit_sha,
            commit_url=str(commit_payload.get("url") or ""),
            applied_changes=list(diff_previews),
            changed_paths=[item.path for item in diff_previews],
            success=True,
        )
        log_stage_payload(
            self._settings,
            run_id=run_id,
            issue_key=issue_key,
            agent="apply",
            stage="output",
            model="github-rest",
            payload=result,
        )
        return result

    def open_draft_pr(
        self,
        *,
        issue_key: str,
        run_id: str,
        implementation: PlannerOutput,
        apply_result: GitHubApplyResult,
    ) -> GitHubPullRequestResult:
        payload = self._request(
            "POST",
            "/pulls",
            {
                "title": implementation.pr_title,
                "head": implementation.branch_name,
                "base": self._settings.github_base_branch,
                "body": implementation.pr_body,
                "draft": True,
            },
        )
        result = GitHubPullRequestResult(
            number=payload.get("number"),
            url=str(payload.get("url") or ""),
            html_url=str(payload.get("html_url") or ""),
            state=str(payload.get("state") or "open"),
            draft=bool(payload.get("draft", True)),
            ready_for_review=not bool(payload.get("draft", True)),
        )
        log_stage_payload(
            self._settings,
            run_id=run_id,
            issue_key=issue_key,
            agent="github",
            stage="draft_pr_opened",
            model="github-rest",
            payload={"pull_request": result, "apply_result": apply_result},
        )
        return result

    def mark_pr_ready_for_review(self, *, issue_key: str, run_id: str, pull_request: GitHubPullRequestResult) -> GitHubPullRequestResult:
        if pull_request.number is None:
            raise GitHubAdapterError("Cannot mark a PR ready for review without a pull request number.")
        payload = self._request(
            "POST",
            f"/pulls/{pull_request.number}/ready_for_review",
            {},
        )
        result = GitHubPullRequestResult(
            number=payload.get("number"),
            url=str(payload.get("url") or pull_request.url),
            html_url=str(payload.get("html_url") or pull_request.html_url),
            state=str(payload.get("state") or pull_request.state or "open"),
            draft=bool(payload.get("draft", False)),
            ready_for_review=not bool(payload.get("draft", False)),
        )
        log_stage_payload(
            self._settings,
            run_id=run_id,
            issue_key=issue_key,
            agent="github",
            stage="ready_for_review",
            model="github-rest",
            payload=result,
        )
        return result

    def prepare_handoff(
        self,
        implementation: PlannerOutput,
        apply_result: GitHubApplyResult,
        pull_request: GitHubPullRequestResult,
    ) -> GitHubHandoffPackage:
        changed_files_plan = [f"{path}: committed in {apply_result.commit_sha}" for path in apply_result.changed_paths]
        return GitHubHandoffPackage(
            branch_name=implementation.branch_name,
            base_branch=self._settings.github_base_branch,
            pr_title=implementation.pr_title,
            pr_body=implementation.pr_body,
            reviewer_summary="Draft PR opened and awaiting human review.",
            changed_files_plan=changed_files_plan,
            publish_ready=True,
            pr_url=pull_request.html_url or pull_request.url,
            commit_sha=apply_result.commit_sha,
        )

    def read_text_file(self, path: str, *, ref: str | None = None) -> str:
        payload = self._request(
            "GET",
            f"/contents/{quote(path, safe='/')}?ref={quote(ref or self._settings.github_base_branch, safe='')}",
        )
        content = str(payload.get("content") or "")
        encoding = str(payload.get("encoding") or "").lower()
        if encoding == "base64":
            return base64.b64decode(content).decode("utf-8")
        return content

    def _get_ref_sha(self, branch_name: str) -> str:
        payload = self._request("GET", f"/git/ref/heads/{quote(branch_name, safe='')}")
        sha = str((payload.get("object") or {}).get("sha") or "")
        if not sha:
            raise GitHubAdapterError(f"Could not resolve ref for branch '{branch_name}'.")
        return sha

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self._api_base}/repos/{self._owner}/{self._repo}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._settings.github_token.strip()}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitHubAdapterError(f"GitHub API HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise GitHubAdapterError(f"GitHub API network error: {exc}") from exc
        return json.loads(raw) if raw.strip() else {}


class LocalGitHubAdapter(GitHubApiAdapter):
    pass


class DisabledGitHubAdapter(GitHubAdapter):
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def create_branch(self, *, issue_key: str, run_id: str, branch_name: str) -> GitHubBranchResult:
        raise GitHubAdapterError("GitHub integration is disabled. Configure GITHUB_TOKEN and GITHUB_REPO.")

    def delete_branch(self, *, branch_name: str) -> None:
        raise GitHubAdapterError("GitHub integration is disabled. Configure GITHUB_TOKEN and GITHUB_REPO.")

    def apply_changes(
        self,
        *,
        issue_key: str,
        run_id: str,
        branch_name: str,
        developer_output: DeveloperOutput,
        diff_previews,
    ) -> GitHubApplyResult:
        raise GitHubAdapterError("GitHub integration is disabled. Configure GITHUB_TOKEN and GITHUB_REPO.")

    def open_draft_pr(
        self,
        *,
        issue_key: str,
        run_id: str,
        implementation: PlannerOutput,
        apply_result: GitHubApplyResult,
    ) -> GitHubPullRequestResult:
        raise GitHubAdapterError("GitHub integration is disabled. Configure GITHUB_TOKEN and GITHUB_REPO.")

    def mark_pr_ready_for_review(self, *, issue_key: str, run_id: str, pull_request: GitHubPullRequestResult) -> GitHubPullRequestResult:
        raise GitHubAdapterError("GitHub integration is disabled. Configure GITHUB_TOKEN and GITHUB_REPO.")

    def prepare_handoff(
        self,
        implementation: PlannerOutput,
        apply_result: GitHubApplyResult,
        pull_request: GitHubPullRequestResult,
    ) -> GitHubHandoffPackage:
        return GitHubHandoffPackage(
            branch_name=implementation.branch_name,
            base_branch=self._settings.github_base_branch,
            pr_title=implementation.pr_title,
            pr_body=implementation.pr_body,
            reviewer_summary="GitHub integration disabled.",
            changed_files_plan=apply_result.changed_paths,
            publish_ready=False,
        )


def _split_repo(value: str) -> tuple[str, str]:
    owner, _, repo = value.strip().partition("/")
    if not owner or not repo:
        raise GitHubAdapterError("GITHUB_REPO must be in the form 'owner/repo'.")
    return owner, repo
