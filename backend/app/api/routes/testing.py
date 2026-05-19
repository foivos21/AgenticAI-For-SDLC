from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.schemas.testing import (
    TestingDeliverablesRead,
    TestingPipelineEnvelope,
    TestingPipelineEventRead,
    TestingPipelineSummaryRead,
    TestingPipelineStartRequest,
    TestingRunSummaryRead,
    TestingTaskRead,
)
from app.services.testing_service import TestingService


router = APIRouter(prefix="/testing", tags=["testing"])
service = TestingService()


class TestingLiveRunRequest(BaseModel):
    task: str | None = None
    include_evaluation: bool = True


@router.get("/tasks", response_model=list[TestingTaskRead])
def list_testing_tasks() -> list[TestingTaskRead]:
    return service.list_tasks()


@router.get("/runs", response_model=list[TestingRunSummaryRead])
def list_testing_runs() -> list[TestingRunSummaryRead]:
    return service.list_runs()


@router.get("/runs/{run_id}")
def get_testing_run(run_id: str) -> dict:
    try:
        return service.get_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Testing run '{run_id}' was not found.") from exc


@router.get("/runs/{run_id}/refinement")
def get_testing_run_refinement(run_id: str) -> dict:
    try:
        return service.get_run_refinement(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Testing refinement for '{run_id}' was not found.") from exc


@router.post("/run/live")
def run_testing_task_live(request: TestingLiveRunRequest) -> StreamingResponse:
    return StreamingResponse(
        service.stream_live_run(task_slug=request.task, include_evaluation=request.include_evaluation),
        media_type="application/json",
    )


@router.post("/pipelines", response_model=TestingPipelineEnvelope)
def start_testing_pipeline(request: TestingPipelineStartRequest) -> TestingPipelineEnvelope:
    return service.start_pipeline(request)


@router.get("/pipelines", response_model=list[TestingPipelineSummaryRead])
def list_testing_pipelines() -> list[TestingPipelineSummaryRead]:
    return service.list_pipelines()


@router.get("/pipelines/{pipeline_id}", response_model=TestingPipelineEnvelope)
def get_testing_pipeline(pipeline_id: str) -> TestingPipelineEnvelope:
    try:
        return service.get_pipeline(pipeline_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' was not found.") from exc


@router.get("/pipelines/{pipeline_id}/events", response_model=list[TestingPipelineEventRead])
def get_testing_pipeline_events(pipeline_id: str) -> list[TestingPipelineEventRead]:
    try:
        return service.get_pipeline_events(pipeline_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' events were not found.") from exc


@router.get("/pipelines/{pipeline_id}/deliverables", response_model=TestingDeliverablesRead)
def get_testing_pipeline_deliverables(pipeline_id: str) -> TestingDeliverablesRead:
    return service.get_pipeline_deliverables(pipeline_id)


@router.get("/pipelines/{pipeline_id}/deliverables/{name}")
def download_testing_pipeline_deliverable(pipeline_id: str, name: str) -> FileResponse:
    try:
        path = service.get_pipeline_deliverable_path(pipeline_id, name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Deliverable '{name}' was not found for pipeline '{pipeline_id}'.") from exc
    return FileResponse(path, filename=path.name)


@router.get("/pipelines/{pipeline_id}/iterations/{iteration_number}/apply-result")
def get_testing_pipeline_apply_result(pipeline_id: str, iteration_number: int) -> dict:
    return service.get_pipeline_apply_result(pipeline_id, iteration_number)


@router.post("/pipelines/{pipeline_id}/approve", response_model=TestingPipelineEnvelope)
def approve_testing_pipeline(pipeline_id: str) -> TestingPipelineEnvelope:
    try:
        return service.approve_pipeline(pipeline_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' was not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/pipelines/{pipeline_id}/cancel", response_model=TestingPipelineEnvelope)
def cancel_testing_pipeline(pipeline_id: str) -> TestingPipelineEnvelope:
    try:
        return service.cancel_pipeline(pipeline_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' was not found.") from exc
