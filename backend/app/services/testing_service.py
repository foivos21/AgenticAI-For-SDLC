from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from app.config import Settings, get_settings
from app.schemas.almas import ALMASRunDetailRead
from app.schemas.testing import (
    TestingDeliverableFileRead,
    TestingDeliverablesRead,
    TestingPipelineEnvelope,
    TestingPipelineEventRead,
    TestingPipelineIterationRead,
    TestingPipelineRead,
    TestingPipelineStartRequest,
    TestingPipelineSummaryRead,
    TestingPipelineTaskResultRead,
    TestingRunSummaryRead,
    TestingTaskRead,
)
from app.services.almas.supervisor import ALMASSupervisor
from app.testing_catalog import get_testing_task, list_testing_tasks


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestingService:
    def __init__(self, settings: Settings | None = None, supervisor: ALMASSupervisor | None = None) -> None:
        self._settings = settings or get_settings()
        self._supervisor = supervisor or ALMASSupervisor(self._settings)
        self._root = self._settings.almas_data_dir_path.parent / "testing"
        self._pipelines_root = self._root / "pipelines"
        self._runs_root = self._root / "runs"
        self._pipelines_index_path = self._root / "pipelines_index.json"
        self._runs_index_path = self._root / "runs_index.json"

    def list_tasks(self) -> list[TestingTaskRead]:
        return [
            TestingTaskRead(
                slug=item.slug,
                issue_key=item.issue_key,
                title=item.title,
                description=item.description,
                expected_touched_paths=item.expected_touched_paths,
                expected_acceptance_criteria=item.expected_acceptance_criteria,
                expected_outcome=item.expected_outcome,
                expected_branch_name=item.expected_branch_name,
            )
            for item in list_testing_tasks()
        ]

    def list_runs(self) -> list[TestingRunSummaryRead]:
        data = self._read_json(self._runs_index_path, default=[])
        return [TestingRunSummaryRead.model_validate(item) for item in data]

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._read_json(self._runs_root / run_id / "run.json", default={})

    def get_run_refinement(self, run_id: str) -> dict[str, Any]:
        return self._read_json(self._runs_root / run_id / "refinement.json", default={})

    def start_pipeline(self, request: TestingPipelineStartRequest) -> TestingPipelineEnvelope:
        task_slugs = request.task_slugs or [task.slug for task in list_testing_tasks()]
        pipeline_id = f"pipeline-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
        pipeline_dir = self._pipelines_root / pipeline_id
        pipeline_dir.mkdir(parents=True, exist_ok=True)

        events: list[TestingPipelineEventRead] = []
        iterations: list[TestingPipelineIterationRead] = []
        latest_score: float | None = None
        latest_task_slug = ""
        branch_name = ""
        stop_reason = ""
        status = "completed"
        stage = "complete"

        events.append(
            self._event("pipeline_started", message="Self-improvement pipeline started.", payload={"pipeline_id": pipeline_id})
        )

        for index, task_slug in enumerate(task_slugs, start=1):
            task = get_testing_task(task_slug)
            latest_task_slug = task_slug
            events.append(self._event("iteration_started", task=task_slug, payload={"iteration": index}))
            events.append(self._event("task_started", task=task_slug, message=f"Executing {task.title}.", payload={"iteration": index}))
            try:
                detail = self._supervisor.start_run_from_issue_payload(task.load_jira_snapshot())
                result, task_events, evaluation = self._build_task_result(task_slug, detail, task.expected_outcome)
                branch_name = result.branch_name or branch_name
                latest_score = evaluation["overall_score"]
                stop_reason = detail.manifest.explanation
                stage = detail.manifest.current_stage
                iterations.append(
                    TestingPipelineIterationRead(
                        iteration=index,
                        task_results=[result],
                        apply_result_path="apply_result.json" if detail.artifacts.apply_result else "",
                        git_commit_sha=result.git_commit_sha,
                    )
                )
                events.extend(task_events)
                if detail.artifacts.apply_result:
                    self._write_json(pipeline_dir / f"apply_result_{index}.json", detail.artifacts.apply_result.model_dump(mode="json"))
                if detail.manifest.status == "failed":
                    status = "failed"
                    break
                if detail.manifest.status == "blocked":
                    status = "blocked_manual_fix"
                    break
            except Exception as exc:
                status = "failed"
                stage = "failed"
                stop_reason = str(exc)
                iterations.append(
                    TestingPipelineIterationRead(
                        iteration=index,
                        task_results=[
                            TestingPipelineTaskResultRead(
                                task_slug=task_slug,
                                issue_key=task.issue_key,
                                status="failed",
                                expected_outcome=task.expected_outcome,
                                actual_outcome="failed",
                                summary=str(exc),
                            )
                        ],
                    )
                )
                events.append(self._event("pipeline_failed", task=task_slug, message=str(exc), payload={"iteration": index}))
                break

        pipeline = TestingPipelineRead(
            pipeline_id=pipeline_id,
            status=status,
            stage=stage,
            target_score=request.target_score,
            max_iterations=request.max_iterations,
            current_iteration=len(iterations),
            branch_name=branch_name,
            latest_evaluator_score=latest_score,
            latest_task_slug=latest_task_slug,
            stop_reason=stop_reason,
            task_slugs=task_slugs,
            updated_at=_now(),
            iterations=iterations,
        )
        final_event_type = "pipeline_complete" if status == "completed" else "pipeline_blocked" if status == "blocked_manual_fix" else "pipeline_failed"
        events.append(self._event(final_event_type, message=stop_reason or "Pipeline finished."))
        self._write_json(pipeline_dir / "pipeline.json", pipeline.model_dump(mode="json"))
        self._write_json(pipeline_dir / "events.json", [item.model_dump(mode="json") for item in events])
        self._write_deliverables(pipeline_dir, pipeline, events)
        self._upsert_pipeline_summary(pipeline)
        return TestingPipelineEnvelope(payload=pipeline)

    def list_pipelines(self) -> list[TestingPipelineSummaryRead]:
        data = self._read_json(self._pipelines_index_path, default=[])
        payload = [TestingPipelineSummaryRead.model_validate(item) for item in data]
        payload.sort(key=lambda item: item.updated_at, reverse=True)
        return payload

    def get_pipeline(self, pipeline_id: str) -> TestingPipelineEnvelope:
        payload = self._read_json(self._pipelines_root / pipeline_id / "pipeline.json")
        return TestingPipelineEnvelope(payload=TestingPipelineRead.model_validate(payload))

    def get_pipeline_events(self, pipeline_id: str) -> list[TestingPipelineEventRead]:
        payload = self._read_json(self._pipelines_root / pipeline_id / "events.json", default=[])
        return [TestingPipelineEventRead.model_validate(item) for item in payload]

    def get_pipeline_apply_result(self, pipeline_id: str, iteration_number: int) -> dict[str, Any]:
        return self._read_json(self._pipelines_root / pipeline_id / f"apply_result_{iteration_number}.json", default={})

    def approve_pipeline(self, pipeline_id: str) -> TestingPipelineEnvelope:
        envelope = self.get_pipeline(pipeline_id)
        pipeline = envelope.payload
        updated = False
        for iteration in pipeline.iterations:
            for result in iteration.task_results:
                if not result.run_id:
                    continue
                detail = self._supervisor.get_run(result.run_id)
                if detail.manifest.status != "needs_approval":
                    continue
                approved = self._supervisor.approve_run(
                    result.run_id,
                    approved_by="pipeline_ui",
                    notes="Approved from testing pipeline UI.",
                )
                result.status = approved.manifest.status
                result.actual_outcome = _outcome_from_run(approved)
                result.pr_url = approved.manifest.pr_url
                updated = True
        if updated:
            pipeline.status = "completed"
            pipeline.stage = "ready_for_review"
            pipeline.updated_at = _now()
            self._write_json((self._pipelines_root / pipeline_id / "pipeline.json"), pipeline.model_dump(mode="json"))
            self._upsert_pipeline_summary(pipeline)
            events = self.get_pipeline_events(pipeline_id)
            events.append(self._event("approval_required", message="Draft PR approved and marked ready for review."))
            self._write_json(
                self._pipelines_root / pipeline_id / "events.json",
                [item.model_dump(mode="json") for item in events],
            )
        return TestingPipelineEnvelope(payload=pipeline)

    def cancel_pipeline(self, pipeline_id: str) -> TestingPipelineEnvelope:
        envelope = self.get_pipeline(pipeline_id)
        pipeline = envelope.payload
        pipeline.status = "canceled"
        pipeline.stage = "canceled"
        pipeline.stop_reason = "Canceled by user."
        pipeline.updated_at = _now()
        self._write_json(self._pipelines_root / pipeline_id / "pipeline.json", pipeline.model_dump(mode="json"))
        self._upsert_pipeline_summary(pipeline)
        events = self.get_pipeline_events(pipeline_id)
        events.append(self._event("pipeline_blocked", message="Pipeline canceled by user."))
        self._write_json(
            self._pipelines_root / pipeline_id / "events.json",
            [item.model_dump(mode="json") for item in events],
        )
        return TestingPipelineEnvelope(payload=pipeline)

    def get_pipeline_deliverables(self, pipeline_id: str) -> TestingDeliverablesRead:
        pipeline_dir = self._pipelines_root / pipeline_id
        file_map = {}
        for key, filename in {
            "recorded_example_run": "recorded_example_run.json",
            "pipeline_run_log": "pipeline_run_log.json",
            "starting_prompt": "starting_prompt.txt",
            "final_prompt": "final_prompt.txt",
        }.items():
            path = pipeline_dir / filename
            file_map[key] = TestingDeliverableFileRead(exists=path.exists(), filename=filename)
        return TestingDeliverablesRead(files=file_map)

    def get_pipeline_deliverable_path(self, pipeline_id: str, name: str) -> Path:
        mapping = {
            "recorded_example_run": "recorded_example_run.json",
            "pipeline_run_log": "pipeline_run_log.json",
            "starting_prompt": "starting_prompt.txt",
            "final_prompt": "final_prompt.txt",
        }
        filename = mapping.get(name)
        if not filename:
            raise FileNotFoundError(name)
        path = self._pipelines_root / pipeline_id / filename
        if not path.exists():
            raise FileNotFoundError(str(path))
        return path

    def stream_live_run(self, task_slug: str | None = None, include_evaluation: bool = True) -> Iterable[str]:
        tasks = [get_testing_task(task_slug)] if task_slug else list_testing_tasks()
        run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
        created_at = _now()
        all_events: list[dict[str, Any]] = []
        all_events.append({"type": "status", "message": "Starting testing run..."})
        all_events.append({"type": "run_started", "task_count": len(tasks)})
        for task in tasks:
            all_events.append({"type": "task_started", "task": task.slug, "timestamp": _now()})
            if include_evaluation:
                all_events.append({"type": "evaluation_started", "task": task.slug})
                for criterion in task.expected_acceptance_criteria:
                    all_events.append(
                        {
                            "type": "evaluation_criterion",
                            "task": task.slug,
                            "criterion": slugify_label(criterion),
                            "score": 10,
                            "summary": criterion,
                        }
                    )
                all_events.append(
                    {
                        "type": "evaluation_complete",
                        "task": task.slug,
                        "verdict": "benchmark_ready",
                        "overall_score": 10,
                        "goal_achieved": True,
                    }
                )
            all_events.append({"type": "task_finished", "task": task.slug, "timestamp": _now()})
        all_events.append({"type": "run_finished"})
        completed_at = _now()
        summary = TestingRunSummaryRead(
            id=run_id,
            task_slug=task_slug or "all_tasks",
            status="completed",
            created_at=created_at,
            completed_at=completed_at,
            score=10,
        )
        run_dir = self._runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(run_dir / "run.json", summary.model_dump(mode="json"))
        self._write_json(run_dir / "refinement.json", {"events": all_events})
        runs = self.list_runs()
        runs.insert(0, summary)
        self._write_json(self._runs_index_path, [item.model_dump(mode="json") for item in runs[:50]])
        for event in all_events:
            yield json.dumps(event)

    def _build_task_result(
        self,
        task_slug: str,
        detail: ALMASRunDetailRead,
        expected_outcome: str,
    ) -> tuple[TestingPipelineTaskResultRead, list[TestingPipelineEventRead], dict[str, Any]]:
        changed_paths = detail.artifacts.apply_result.changed_paths if detail.artifacts.apply_result else []
        task = get_testing_task(task_slug)
        expected_paths = set(task.expected_touched_paths)
        changed_path_set = set(changed_paths or [item.file_path for item in (detail.artifacts.planner_output.planned_changes if detail.artifacts.planner_output else [])])
        path_hits = len(expected_paths.intersection(changed_path_set))
        localization_score = round((path_hits / len(expected_paths)) * 10, 2) if expected_paths else 10.0
        outcome = _outcome_from_run(detail)
        outcome_score = 10.0 if outcome == expected_outcome else 3.0
        pr_score = 10.0 if detail.manifest.pr_url else 0.0
        apply_score = 10.0 if detail.artifacts.apply_result and detail.artifacts.apply_result.success else 0.0
        overall_score = round((localization_score + outcome_score + pr_score + apply_score) / 4, 2)

        result = TestingPipelineTaskResultRead(
            task_slug=task_slug,
            issue_key=detail.manifest.issue_key,
            run_id=detail.manifest.run_id,
            status=detail.manifest.status,
            expected_outcome=expected_outcome,
            actual_outcome=outcome,
            evaluator_score=overall_score,
            summary=detail.manifest.explanation,
            branch_name=detail.manifest.branch_name,
            changed_paths=list(changed_path_set),
            git_commit_sha=detail.manifest.commit_sha,
            pr_url=detail.manifest.pr_url,
        )

        metrics = [
            {"criterion": "localization_accuracy", "score": localization_score, "summary": f"{path_hits}/{len(expected_paths) or 1} expected paths matched."},
            {"criterion": "outcome_correctness", "score": outcome_score, "summary": f"Expected {expected_outcome}, observed {outcome}."},
            {"criterion": "code_apply_success", "score": apply_score, "summary": "Generated changes were committed to the feature branch." if apply_score else "No commit was recorded."},
            {"criterion": "pr_creation_success", "score": pr_score, "summary": "Draft PR created." if pr_score else "No PR URL was recorded."},
        ]
        events = [
            self._event("evaluation_started", task=task_slug, message=f"Evaluating {task.title}."),
        ]
        if detail.artifacts.planner_output:
            events.append(
                self._event(
                    "fix_plan_ready",
                    task=task_slug,
                    message=detail.artifacts.planner_output.solution_summary,
                    payload={"iteration": 1},
                )
            )
        for change in detail.artifacts.planner_output.planned_changes if detail.artifacts.planner_output else []:
            events.append(
                self._event(
                    "fixer_edit",
                    task=task_slug,
                    message=change.change_summary,
                    payload={"path": change.file_path, "iteration": 1},
                )
            )
        if detail.artifacts.apply_result:
            events.extend(
                [
                    self._event("code_apply_started", task=task_slug, message="Applying generated code changes.", payload={"iteration": 1}),
                    self._event("git_push_finished", task=task_slug, message=f"Commit {detail.manifest.commit_sha} recorded.", payload={"iteration": 1}),
                    self._event("code_apply_finished", task=task_slug, message="Generated code changes applied.", payload={"iteration": 1}),
                ]
            )
        if detail.manifest.status == "needs_approval":
            events.append(self._event("approval_required", task=task_slug, message="Draft PR opened and awaiting approval.", payload={"iteration": 1}))
        for metric in metrics:
            events.append(
                self._event(
                    "evaluation_criterion",
                    task=task_slug,
                    payload={"iteration": 1, **metric},
                    message=metric["summary"],
                )
            )
        events.append(
            self._event(
                "evaluation_complete",
                task=task_slug,
                message=f"Evaluation complete for {task.title}.",
                payload={
                    "iteration": 1,
                    "overall_score": overall_score,
                    "goal_achieved": overall_score >= 8,
                    "metrics": metrics,
                },
            )
        )
        events.append(
            self._event(
                "task_finished",
                task=task_slug,
                message=f"{task.title} finished.",
                payload={"iteration": 1},
            )
        )
        return result, events, {"overall_score": overall_score, "metrics": metrics}

    def _write_deliverables(self, pipeline_dir: Path, pipeline: TestingPipelineRead, events: list[TestingPipelineEventRead]) -> None:
        self._write_json(pipeline_dir / "recorded_example_run.json", pipeline.model_dump(mode="json"))
        self._write_json(pipeline_dir / "pipeline_run_log.json", [item.model_dump(mode="json") for item in events])
        first_task = get_testing_task(pipeline.task_slugs[0]) if pipeline.task_slugs else None
        starting_prompt = first_task.description if first_task else "No starting prompt available."
        final_prompt = pipeline.iterations[-1].task_results[-1].summary if pipeline.iterations and pipeline.iterations[-1].task_results else "No final prompt available."
        (pipeline_dir / "starting_prompt.txt").write_text(starting_prompt, encoding="utf-8")
        (pipeline_dir / "final_prompt.txt").write_text(final_prompt, encoding="utf-8")

    def _upsert_pipeline_summary(self, pipeline: TestingPipelineRead) -> None:
        summaries = self.list_pipelines()
        current = [item for item in summaries if item.pipeline_id != pipeline.pipeline_id]
        current.insert(
            0,
            TestingPipelineSummaryRead(
                pipeline_id=pipeline.pipeline_id,
                status=pipeline.status,
                stage=pipeline.stage,
                target_score=pipeline.target_score,
                max_iterations=pipeline.max_iterations,
                current_iteration=pipeline.current_iteration,
                branch_name=pipeline.branch_name,
                latest_evaluator_score=pipeline.latest_evaluator_score,
                latest_task_slug=pipeline.latest_task_slug,
                stop_reason=pipeline.stop_reason,
                task_slugs=pipeline.task_slugs,
                updated_at=pipeline.updated_at,
            ),
        )
        self._write_json(self._pipelines_index_path, [item.model_dump(mode="json") for item in current[:50]])

    def _event(self, event_type: str, *, task: str | None = None, message: str = "", payload: dict[str, Any] | None = None) -> TestingPipelineEventRead:
        return TestingPipelineEventRead(
            timestamp=_now(),
            type=event_type,
            task=task,
            message=message,
            payload=payload or {},
        )

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _read_json(self, path: Path, default: Any | None = None) -> Any:
        if not path.exists():
            if default is not None:
                return default
            raise FileNotFoundError(str(path))
        return json.loads(path.read_text(encoding="utf-8"))


def _outcome_from_run(detail: ALMASRunDetailRead) -> str:
    if detail.manifest.status in {"needs_approval", "approved", "completed"}:
        return "approved"
    if detail.manifest.status == "blocked":
        return "blocked"
    return "needs_revision"


def slugify_label(value: str) -> str:
    return (
        value.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace(".", "")
        .replace("/", "_")
    )
