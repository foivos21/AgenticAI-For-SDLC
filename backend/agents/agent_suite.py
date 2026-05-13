from __future__ import annotations

import os
from pathlib import Path

from agents.analyzer_agent import AnalyzerAgent
from agents.fixer_agent import FixerAgent
from agents.planner_agent import PlannerAgent
from app.config import Settings, get_settings
from app.schemas.almas import AnalyzerOutput, FixerOutput, PlannerOutput
from app.services.jira_service import JiraIssueAnalysis


class ALMASAgentSuite:
    def __init__(self, settings: Settings | None = None, repo_root: Path | None = None) -> None:
        self._settings = settings or get_settings()
        if self._settings.openai_api_key.strip():
            os.environ.setdefault("OPENAI_API_KEY", self._settings.openai_api_key.strip())
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for ALMAS agent execution.")

        self._repo_root = repo_root or Path(__file__).resolve().parents[1]
        self._analyzer_agent = AnalyzerAgent(self._settings.almas_analyzer_model, self._repo_root)
        self._planner_agent = PlannerAgent(self._settings.almas_planner_model)
        self._fixer_agent = FixerAgent(self._settings.almas_fixer_model)

    @property
    def model_names(self) -> dict[str, str]:
        return {
            "analyzer": self._settings.almas_analyzer_model,
            "planner": self._settings.almas_planner_model,
            "fixer": self._settings.almas_fixer_model,
        }

    def run_analyzer(self, issue: JiraIssueAnalysis) -> AnalyzerOutput:
        return self._analyzer_agent.run(issue)

    def run_planner(
        self,
        issue: JiraIssueAnalysis,
        analyzer_output: AnalyzerOutput,
        revision_requests: list[str] | None = None,
    ) -> PlannerOutput:
        return self._planner_agent.run(
            issue,
            analyzer_output,
            revision_requests=revision_requests,
        )

    def run_fixer(self, analyzer_output: AnalyzerOutput, planner_output: PlannerOutput) -> FixerOutput:
        return self._fixer_agent.run(analyzer_output, planner_output)
