from __future__ import annotations

import json

from pydantic_ai import Agent

from agents.prompts import PLANNER_AGENT_SYSTEM_PROMPT
from app.schemas.almas import AnalyzerOutput, PlannerOutput
from app.services.jira_service import JiraIssueAnalysis


class PlannerAgent:
    def __init__(self, model_name: str) -> None:
        self._agent = Agent(
            model_name,
            output_type=PlannerOutput,
            system_prompt=PLANNER_AGENT_SYSTEM_PROMPT,
        )

    def run(
        self,
        issue: JiraIssueAnalysis,
        analyzer_output: AnalyzerOutput,
        revision_requests: list[str] | None = None,
    ) -> PlannerOutput:
        prompt_payload = {
            "issue": issue.__dict__,
            "analyzer_output": analyzer_output.model_dump(mode="json"),
            "revision_requests": revision_requests or [],
        }
        prompt = (
            "Build an implementation plan from this Jira issue context.\n"
            f"{json.dumps(prompt_payload, indent=2)}"
        )
        return self._agent.run_sync(prompt).output
