from __future__ import annotations

import json

from pydantic_ai import Agent

from agents.prompts import FIXER_AGENT_SYSTEM_PROMPT
from app.schemas.almas import AnalyzerOutput, FixerOutput, PlannerOutput


class FixerAgent:
    def __init__(self, model_name: str) -> None:
        self._agent = Agent(
            model_name,
            output_type=FixerOutput,
            system_prompt=FIXER_AGENT_SYSTEM_PROMPT,
        )

    def run(
        self,
        analyzer_output: AnalyzerOutput,
        planner_output: PlannerOutput,
    ) -> FixerOutput:
        prompt_payload = {
            "analyzer_output": analyzer_output.model_dump(mode="json"),
            "planner_output": planner_output.model_dump(mode="json"),
        }
        prompt = (
            "Review this proposed implementation plan and act as the final fixer/checkpoint.\n"
            f"{json.dumps(prompt_payload, indent=2)}"
        )
        return self._agent.run_sync(prompt).output
