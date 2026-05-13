from __future__ import annotations

import json
from pathlib import Path

from pydantic_ai import Agent

from agents.prompts import ANALYZER_AGENT_SYSTEM_PROMPT
from agents.tools import build_repo_context
from app.schemas.almas import AnalyzerOutput
from app.services.jira_service import JiraIssueAnalysis


class AnalyzerAgent:
    def __init__(self, model_name: str, repo_root: Path) -> None:
        self._repo_root = repo_root
        self._agent = Agent(
            model_name,
            output_type=AnalyzerOutput,
            system_prompt=ANALYZER_AGENT_SYSTEM_PROMPT,
        )

    def run(self, issue: JiraIssueAnalysis) -> AnalyzerOutput:
        repo_context = build_repo_context(self._repo_root, issue)
        prompt = (
            f"Issue key: {issue.issue_key}\n"
            f"Summary: {issue.summary}\n"
            f"Description:\n{issue.description or '(empty)'}\n"
            f"Labels: {', '.join(issue.labels) if issue.labels else 'none'}\n"
            f"Priority: {issue.priority or 'unspecified'}\n\n"
            "Repository context:\n"
            f"{json.dumps(repo_context, indent=2)}\n\n"
            "Return a single analyzer output that explains the problem and localizes the likely implementation area."
        )
        return self._agent.run_sync(prompt).output
