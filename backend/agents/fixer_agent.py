from __future__ import annotations

import json

from pydantic_ai import Agent

from agents.prompts import FIXER_AGENT_SYSTEM_PROMPT
from app.config import Settings
from app.schemas.almas import AnalyzerOutput, DeveloperOutput, FileDiffPreview, FixerOutput, PlannerOutput
from app.services.almas.logging import log_stage_payload


class FixerAgent:
    def __init__(self, model_name: str, settings: Settings) -> None:
        self._settings = settings
        self._model_name = model_name
        self._agent = Agent(
            model_name,
            output_type=FixerOutput,
            system_prompt=FIXER_AGENT_SYSTEM_PROMPT,
        )

    def run(
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
        prompt_payload = {
            "analyzer_output": analyzer_output.model_dump(mode="json"),
            "planner_output": planner_output.model_dump(mode="json"),
            "developer_output": developer_output.model_dump(mode="json"),
            "diff_previews": [item.model_dump(mode="json") for item in diff_previews],
        }
        if test_results is not None:
            prompt_payload["automated_test_results"] = test_results
        prompt = (
            "Review this proposed implementation and its file changes.\n"
            f"{json.dumps(prompt_payload, indent=2)}"
        )
        log_stage_payload(
            self._settings,
            run_id=run_id,
            issue_key=issue_key,
            agent="fixer",
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
            issue_key=issue_key,
            agent="fixer",
            stage="output",
            model=self._model_name,
            payload=output,
        )
        return output

    @property
    def last_usage(self) -> dict[str, int]:
        return getattr(self, "_last_usage", {"request_tokens": 0, "response_tokens": 0, "total_tokens": 0})
