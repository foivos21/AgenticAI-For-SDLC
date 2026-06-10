from __future__ import annotations

import os
import time
from pathlib import Path

from agents.analyzer_agent import AnalyzerAgent
from agents.developer_agent import DeveloperAgent
from agents.fixer_agent import FixerAgent
from agents.planner_agent import PlannerAgent
from app.config import Settings, get_settings
from app.schemas.almas import AgentTimingInfo, AnalyzerOutput, DeveloperOutput, FileDiffPreview, FixerOutput, PlannerOutput
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
        self._timing_history: list[AgentTimingInfo] = []

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
        start_time = time.time()
        try:
            output = self._analyzer_agent.run(issue, run_id=run_id)
            end_time = time.time()
            self._timing_history.append(AgentTimingInfo(
                agent_name="analyzer",
                start_time=start_time,
                end_time=end_time,
                duration_seconds=end_time - start_time,
                status="success"
            ))
            return output
        except Exception as e:
            end_time = time.time()
            self._timing_history.append(AgentTimingInfo(
                agent_name="analyzer",
                start_time=start_time,
                end_time=end_time,
                duration_seconds=end_time - start_time,
                status="error"
            ))
            raise

    def run_planner(
        self,
        issue: JiraIssueAnalysis,
        analyzer_output: AnalyzerOutput,
        *,
        run_id: str,
        branch_name: str,
        revision_requests: list[str] | None = None,
    ) -> PlannerOutput:
        start_time = time.time()
        try:
            output = self._planner_agent.run(
                issue,
                analyzer_output,
                run_id=run_id,
                branch_name=branch_name,
                revision_requests=revision_requests,
            )
            end_time = time.time()
            self._timing_history.append(AgentTimingInfo(
                agent_name="planner",
                start_time=start_time,
                end_time=end_time,
                duration_seconds=end_time - start_time,
                status="success"
            ))
            return output
        except Exception as e:
            end_time = time.time()
            self._timing_history.append(AgentTimingInfo(
                agent_name="planner",
                start_time=start_time,
                end_time=end_time,
                duration_seconds=end_time - start_time,
                status="error"
            ))
            raise

    def run_developer(
        self,
        issue: JiraIssueAnalysis,
        analyzer_output: AnalyzerOutput,
        planner_output: PlannerOutput,
        *,
        run_id: str,
    ) -> DeveloperOutput:
        start_time = time.time()
        try:
            output = self._developer_agent.run(
                issue,
                analyzer_output,
                planner_output,
                run_id=run_id,
            )
            end_time = time.time()
            self._timing_history.append(AgentTimingInfo(
                agent_name="developer",
                start_time=start_time,
                end_time=end_time,
                duration_seconds=end_time - start_time,
                status="success"
            ))
            return output
        except Exception as e:
            end_time = time.time()
            self._timing_history.append(AgentTimingInfo(
                agent_name="developer",
                start_time=start_time,
                end_time=end_time,
                duration_seconds=end_time - start_time,
                status="error"
            ))
            raise

    def run_fixer(
        self,
        analyzer_output: AnalyzerOutput,
        planner_output: PlannerOutput,
        developer_output: DeveloperOutput,
        diff_previews: list[FileDiffPreview],
        *,
        run_id: str,
        issue_key: str,
        test_results: dict | None = None,
    ) -> FixerOutput:
        start_time = time.time()
        try:
            output = self._fixer_agent.run(
                analyzer_output,
                planner_output,
                developer_output,
                diff_previews,
                run_id=run_id,
                issue_key=issue_key,
                test_results=test_results,
            )
            end_time = time.time()
            self._timing_history.append(AgentTimingInfo(
                agent_name="fixer",
                start_time=start_time,
                end_time=end_time,
                duration_seconds=end_time - start_time,
                status="success"
            ))
            return output
        except Exception as e:
            end_time = time.time()
            self._timing_history.append(AgentTimingInfo(
                agent_name="fixer",
                start_time=start_time,
                end_time=end_time,
                duration_seconds=end_time - start_time,
                status="error"
            ))
            raise

    @property
    def timing_history(self) -> list[AgentTimingInfo]:
        return self._timing_history

    def get_timing_summary(self) -> dict[str, float]:
        """Get a summary of timing by agent."""
        summary = {}
        for timing in self._timing_history:
            if timing.agent_name not in summary:
                summary[timing.agent_name] = 0.0
            summary[timing.agent_name] += timing.duration_seconds
        return summary
