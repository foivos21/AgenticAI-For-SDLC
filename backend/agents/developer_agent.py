from __future__ import annotations

import json

from pydantic_ai import Agent

from agents.prompts import DEVELOPER_AGENT_SYSTEM_PROMPT
from app.config import Settings
from app.schemas.almas import AnalyzerOutput, DeveloperOutput, PlannerOutput
from app.services.almas.logging import log_stage_payload
from app.services.almas.repository import RepositoryReader
from app.services.jira_service import JiraIssueAnalysis


class DeveloperAgent:
    def __init__(self, model_name: str, repository: RepositoryReader, settings: Settings) -> None:
        self._settings = settings
        self._repository = repository
        self._model_name = model_name
        self._agent = Agent(
            model_name,
            output_type=DeveloperOutput,
            system_prompt=DEVELOPER_AGENT_SYSTEM_PROMPT,
        )

    def run(
        self,
        issue: JiraIssueAnalysis,
        analyzer_output: AnalyzerOutput,
        planner_output: PlannerOutput,
        *,
        run_id: str,
    ) -> DeveloperOutput:
        target_paths = [change.file_path for change in planner_output.planned_changes if change.file_path]
        file_payload = self._repository.load_files(target_paths[:20])
        prompt_payload = {
            "issue": issue.__dict__,
            "analyzer_output": analyzer_output.model_dump(mode="json"),
            "planner_output": planner_output.model_dump(mode="json"),
            "repository_files": file_payload,
            "required_branch_name": planner_output.branch_name,
        }
        prompt = (
            "Generate the concrete file changes needed to implement the planned work.\n"
            "Return only structured file operations with complete file contents.\n"
            "Use the required_branch_name exactly for the branch_name field.\n"
            f"{json.dumps(prompt_payload, indent=2)}"
        )
        log_stage_payload(
            self._settings,
            run_id=run_id,
            issue_key=issue.issue_key,
            agent="developer",
            stage="input",
            model=self._model_name,
            payload={"prompt": prompt},
        )
        result = self._agent.run_sync(prompt)
        output = result.output
        output.branch_name = planner_output.branch_name
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
            agent="developer",
            stage="output",
            model=self._model_name,
            payload=output,
        )
        return output

    @property
    def last_usage(self) -> dict[str, int]:
        return getattr(self, "_last_usage", {"request_tokens": 0, "response_tokens": 0, "total_tokens": 0})
