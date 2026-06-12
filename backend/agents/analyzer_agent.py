from __future__ import annotations

import json

from pydantic_ai import Agent

from agents.prompts import ANALYZER_AGENT_SYSTEM_PROMPT
from app.config import Settings
from app.schemas.almas import AnalyzerOutput
from app.services.almas.logging import log_stage_payload
from app.services.almas.repository import RepositoryReader
from app.services.jira_service import JiraIssueAnalysis


class AnalyzerAgent:
    def __init__(self, model_name: str, repository: RepositoryReader, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings
        self._model_name = model_name
        self._agent = Agent(
            model_name,
            output_type=AnalyzerOutput,
            system_prompt=ANALYZER_AGENT_SYSTEM_PROMPT,
        )

    def run(self, issue: JiraIssueAnalysis, *, run_id: str) -> AnalyzerOutput:
        repo_context = self._repository.build_repo_context(issue)
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
        log_stage_payload(
            self._settings,
            run_id=run_id,
            issue_key=issue.issue_key,
            agent="analyzer",
            stage="input",
            model=self._model_name,
            payload={"prompt": prompt},
        )
        result = self._agent.run_sync(prompt)
        output = result.output
        _u = result.usage()
        self._last_usage = {
            "request_tokens": _u.request_tokens or 0,
            "response_tokens": _u.response_tokens or 0,
            "total_tokens": _u.total_tokens or 0,
        }
        log_stage_payload(
            self._settings,
            run_id=run_id,
            issue_key=issue.issue_key,
            agent="analyzer",
            stage="output",
            model=self._model_name,
            payload=output,
        )
        return output

    @property
    def last_usage(self) -> dict[str, int]:
        return getattr(self, "_last_usage", {"request_tokens": 0, "response_tokens": 0, "total_tokens": 0})
