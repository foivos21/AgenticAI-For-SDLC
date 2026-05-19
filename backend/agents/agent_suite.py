from __future__ import annotations

import os
from pathlib import Path

from agents.analyzer_agent import AnalyzerAgent
from agents.developer_agent import DeveloperAgent
from agents.fixer_agent import FixerAgent
from agents.planner_agent import PlannerAgent
from app.config import Settings, get_settings
from app.schemas.almas import AnalyzerOutput, DeveloperOutput, FileDiffPreview, FixerOutput, PlannerOutput
from app.services.almas.repository import RepositoryReader, get_repository_reader
from app.services.jira_service import JiraIssueAnalysis


class ALMASAgentSuite:
    def __init__(
        self,
        settings: Settings | None = None,
        repo_root: Path | None = None,
        repository: RepositoryReader | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        if self._settings.openai_api_key.strip():
            os.environ.setdefault("OPENAI_API_KEY", self._settings.openai_api_key.strip())
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for ALMAS agent execution.")

        self._repo_root = repo_root or Path(__file__).resolve().parents[2]
        self._repository = repository or get_repository_reader(self._settings, self._repo_root)
        self._analyzer_agent = AnalyzerAgent(self._settings.almas_analyzer_model, self._repository, self._settings)
        self._planner_agent = PlannerAgent(self._settings.almas_planner_model, self._settings)
        self._developer_agent = DeveloperAgent(self._settings.almas_developer_model, self._repository, self._settings)
        self._fixer_agent = FixerAgent(self._settings.almas_fixer_model, self._settings)

    @property
    def model_names(self) -> dict[str, str]:
        return {
            "analyzer": self._settings.almas_analyzer_model,
            "planner": self._settings.almas_planner_model,
            "developer": self._settings.almas_developer_model,
            "fixer": self._settings.almas_fixer_model,
        }

    @property
    def repository(self) -> RepositoryReader:
        return self._repository

    def run_analyzer(self, issue: JiraIssueAnalysis, *, run_id: str) -> AnalyzerOutput:
        return self._analyzer_agent.run(issue, run_id=run_id)

    def run_planner(
        self,
        issue: JiraIssueAnalysis,
        analyzer_output: AnalyzerOutput,
        *,
        run_id: str,
        branch_name: str,
        revision_requests: list[str] | None = None,
    ) -> PlannerOutput:
        return self._planner_agent.run(
            issue,
            analyzer_output,
            run_id=run_id,
            branch_name=branch_name,
            revision_requests=revision_requests,
        )

    def run_developer(
        self,
        issue: JiraIssueAnalysis,
        analyzer_output: AnalyzerOutput,
        planner_output: PlannerOutput,
        *,
        run_id: str,
    ) -> DeveloperOutput:
        return self._developer_agent.run(
            issue,
            analyzer_output,
            planner_output,
            run_id=run_id,
        )

    def run_fixer(
        self,
        analyzer_output: AnalyzerOutput,
        planner_output: PlannerOutput,
        developer_output: DeveloperOutput,
        diff_previews: list[FileDiffPreview],
        *,
        run_id: str,
        issue_key: str,
    ) -> FixerOutput:
        return self._fixer_agent.run(
            analyzer_output,
            planner_output,
            developer_output,
            diff_previews,
            run_id=run_id,
            issue_key=issue_key,
        )
