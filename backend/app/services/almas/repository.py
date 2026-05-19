from __future__ import annotations

import base64
import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.config import Settings, get_settings
from app.services.jira_service import JiraIssueAnalysis


EXCLUDED_PATH_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
}

TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".css",
    ".html",
    ".md",
    ".json",
    ".toml",
    ".yml",
    ".yaml",
    ".txt",
    ".sh",
}


class RepositoryError(RuntimeError):
    pass


class RepositoryReader(ABC):
    @abstractmethod
    def list_text_files(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def read_text_file(self, path: str) -> str:
        raise NotImplementedError

    def build_repo_context(self, issue: JiraIssueAnalysis) -> dict[str, object]:
        repo_files = self.list_text_files()
        top_level_counts: dict[str, int] = {}
        for item in repo_files:
            top_level = item.split("/", 1)[0]
            top_level_counts[top_level] = top_level_counts.get(top_level, 0) + 1

        repo_summary = ", ".join(f"{name}({count})" for name, count in sorted(top_level_counts.items()))
        keywords = _keyword_tokens(" ".join([issue.summary, issue.description]))
        scored_paths: list[tuple[int, str]] = []
        for relative_path in repo_files:
            normalized = relative_path.lower()
            score = sum(1 for token in keywords if token in normalized)
            if score:
                scored_paths.append((score, relative_path))
        scored_paths.sort(key=lambda item: (-item[0], item[1]))
        candidate_files = [path for _, path in scored_paths[:20]]
        if not candidate_files:
            candidate_files = repo_files[:20]
        return {
            "repo_summary": repo_summary or "Repository structure unavailable.",
            "candidate_files": candidate_files,
        }

    def load_files(self, paths: list[str]) -> dict[str, str]:
        loaded: dict[str, str] = {}
        for path in paths:
            try:
                loaded[path] = self.read_text_file(path)
            except Exception:
                continue
        return loaded


class LocalRepositoryReader(RepositoryReader):
    def __init__(self, root: Path) -> None:
        self._root = root

    def list_text_files(self) -> list[str]:
        repo_files: list[str] = []
        for path in self._root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in EXCLUDED_PATH_PARTS for part in path.parts):
                continue
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            try:
                repo_files.append(str(path.relative_to(self._root)))
            except ValueError:
                continue
        return sorted(repo_files)

    def read_text_file(self, path: str) -> str:
        target = (self._root / path).resolve()
        return target.read_text(encoding="utf-8")


class GitHubRepositoryReader(RepositoryReader):
    def __init__(self, settings: Settings, ref: str | None = None) -> None:
        self._settings = settings
        self._owner, self._repo = _split_repo(settings.github_repo)
        self._api_base = settings.github_api_base_url.rstrip("/")
        self._ref = ref or settings.github_base_branch
        self._cached_files: list[str] | None = None

    def _request(self, method: str, path: str) -> dict[str, Any]:
        request = Request(
            f"{self._api_base}{path}",
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._settings.github_token.strip()}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RepositoryError(f"GitHub repository read HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RepositoryError(f"GitHub repository read network error: {exc}") from exc
        return json.loads(raw) if raw.strip() else {}

    def list_text_files(self) -> list[str]:
        if self._cached_files is not None:
            return self._cached_files
        payload = self._request(
            "GET",
            f"/repos/{self._owner}/{self._repo}/git/trees/{quote(self._ref, safe='')}?recursive=1",
        )
        tree = payload.get("tree") or []
        files: list[str] = []
        for item in tree:
            if not isinstance(item, dict) or item.get("type") != "blob":
                continue
            path = str(item.get("path") or "")
            suffix = Path(path).suffix.lower()
            if not path or suffix not in TEXT_EXTENSIONS:
                continue
            if any(part in EXCLUDED_PATH_PARTS for part in Path(path).parts):
                continue
            files.append(path)
        self._cached_files = sorted(files)
        return self._cached_files

    def read_text_file(self, path: str) -> str:
        payload = self._request(
            "GET",
            f"/repos/{self._owner}/{self._repo}/contents/{quote(path, safe='/')}?ref={quote(self._ref, safe='')}",
        )
        content = str(payload.get("content") or "")
        encoding = str(payload.get("encoding") or "").lower()
        if encoding == "base64":
            return base64.b64decode(content).decode("utf-8")
        return content


def get_repository_reader(settings: Settings | None = None, repo_root: Path | None = None) -> RepositoryReader:
    resolved_settings = settings or get_settings()
    mode = resolved_settings.almas_repository_mode.strip().lower()
    local_root = repo_root or Path(__file__).resolve().parents[4]

    if mode == "local":
        return LocalRepositoryReader(local_root)
    if mode == "github":
        if not resolved_settings.github_integration_enabled:
            raise RepositoryError("GitHub repository mode requires GITHUB_TOKEN and GITHUB_REPO.")
        return GitHubRepositoryReader(resolved_settings)

    if local_root.exists() and (local_root / "backend").exists():
        return LocalRepositoryReader(local_root)
    if resolved_settings.github_integration_enabled:
        return GitHubRepositoryReader(resolved_settings)
    return LocalRepositoryReader(local_root)


def slugify_branch_component(value: str) -> str:
    collapsed = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-")
    return collapsed.lower() or "task"


def _split_repo(value: str) -> tuple[str, str]:
    owner, _, repo = value.strip().partition("/")
    if not owner or not repo:
        raise RepositoryError("GITHUB_REPO must be in the form 'owner/repo'.")
    return owner, repo


def _keyword_tokens(text: str) -> list[str]:
    tokens = [token for token in re.split(r"[^a-zA-Z0-9]+", text.lower()) if len(token) >= 4]
    deduped: list[str] = []
    for token in tokens:
        if token not in deduped:
            deduped.append(token)
    return deduped[:20]
