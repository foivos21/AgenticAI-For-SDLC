from __future__ import annotations

import re
from pathlib import Path

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
}


def build_repo_context(repo_root: Path, issue: JiraIssueAnalysis) -> dict[str, object]:
    repo_files = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_PATH_PARTS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        try:
            relative_path = str(path.relative_to(repo_root))
        except ValueError:
            continue
        repo_files.append(relative_path)

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


def _keyword_tokens(text: str) -> list[str]:
    tokens = [token for token in re.split(r"[^a-zA-Z0-9]+", text.lower()) if len(token) >= 4]
    deduped: list[str] = []
    for token in tokens:
        if token not in deduped:
            deduped.append(token)
    return deduped[:20]
