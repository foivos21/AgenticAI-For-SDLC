from __future__ import annotations

import json

from pydantic_ai import Agent

from agents.prompts import PLANNER_AGENT_SYSTEM_PROMPT
from app.config import Settings
from app.schemas.almas import AnalyzerOutput, PlannerOutput
from app.services.almas.logging import log_stage_payload
from app.services.jira_service import JiraIssueAnalysis


class PlannerAgent:
    def __init__(self, model_name: str, settings: Settings) -> None:
        self._settings = settings
        self._model_name = model_name
        self._agent = Agent(
            model_name,
            output_type=PlannerOutput,
            system_prompt=PLANNER_AGENT_SYSTEM_PROMPT,
        )

    def run(
        self,
        issue: JiraIssueAnalysis,
        analyzer_output: AnalyzerOutput,
        *,
        run_id: str,
        branch_name: str,
        revision_requests: list[str] | None = None,
    ) -> PlannerOutput:
        prompt_payload = {
            "issue": issue.__dict__,
            "analyzer_output": analyzer_output.model_dump(mode="json"),
            "revision_requests": revision_requests or [],
            "required_branch_name": branch_name,
        }
        prompt = (
            "Build an implementation plan from this Jira issue context.\n"
            "Use the required_branch_name exactly for the branch_name field.\n"
            f"{json.dumps(prompt_payload, indent=2)}"
        )
        log_stage_payload(
            self._settings,
            run_id=run_id,
            issue_key=issue.issue_key,
            agent="planner",
            stage="input",
            model=self._model_name,
            payload={"prompt": prompt},
        )
        result = self._agent.run_sync(prompt)
        output = result.output
        output.branch_name = branch_name
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
            agent="planner",
            stage="output",
            model=self._model_name,
            payload=output,
        )
        return output

    @property
    def last_usage(self) -> dict[str, int]:
        return getattr(self, "_last_usage", {"request_tokens": 0, "response_tokens": 0, "total_tokens": 0})
