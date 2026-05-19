from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from pydantic import BaseModel

from app.config import Settings, get_settings
from app.schemas.almas import (
    ALMASRunArtifacts,
    ALMASRunDetailRead,
    ALMASRunManifest,
    ALMASRunSummaryRead,
    AnalyzerOutput,
    ApprovalDecision,
    DeveloperOutput,
    FixerOutput,
    GitHubApplyResult,
    GitHubBranchResult,
    GitHubHandoffPackage,
    GitHubPullRequestResult,
    PlannerOutput,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ALMASRunStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._root = self._settings.almas_data_dir_path
        self._index_path = self._root / "runs_index.json"
        self._lock = Lock()

    @property
    def root(self) -> Path:
        return self._root

    def create_run(self, run_id: str, issue_key: str, model_names: dict[str, str]) -> ALMASRunManifest:
        manifest = ALMASRunManifest(
            run_id=run_id,
            issue_key=issue_key,
            status="created",
            current_stage="created",
            created_at=_now(),
            updated_at=_now(),
            explanation="Run created.",
            model_names=model_names,
        )
        self.save_manifest(manifest)
        return manifest

    def save_manifest(self, manifest: ALMASRunManifest) -> ALMASRunManifest:
        manifest.updated_at = _now()
        with self._lock:
            run_dir = self._run_dir(manifest.run_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "manifest.json").write_text(
                json.dumps(manifest.model_dump(mode="json"), indent=2),
                encoding="utf-8",
            )
            index = self._read_index()
            index[manifest.run_id] = ALMASRunSummaryRead(
                run_id=manifest.run_id,
                issue_key=manifest.issue_key,
                status=manifest.status,
                current_stage=manifest.current_stage,
                revision_count=manifest.revision_count,
                updated_at=manifest.updated_at,
                explanation=manifest.explanation,
                branch_name=manifest.branch_name,
                commit_sha=manifest.commit_sha,
                pr_number=manifest.pr_number,
                pr_url=manifest.pr_url,
            ).model_dump(mode="json")
            self._write_index(index)
        return manifest

    def write_artifact(self, run_id: str, artifact_name: str, payload: BaseModel | dict[str, Any]) -> str:
        filename = f"{artifact_name}.json"
        artifact_path = self._run_dir(run_id) / filename
        if isinstance(payload, BaseModel):
            data = payload.model_dump(mode="json")
        else:
            data = payload
        with self._lock:
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return filename

    def load_manifest(self, run_id: str) -> ALMASRunManifest:
        path = self._run_dir(run_id) / "manifest.json"
        return ALMASRunManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def load_run(self, run_id: str) -> ALMASRunDetailRead:
        manifest = self.load_manifest(run_id)
        artifacts = ALMASRunArtifacts()
        for artifact_name, filename in manifest.artifact_files.items():
            path = self._run_dir(run_id) / filename
            if not path.exists():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            if artifact_name == "jira_snapshot":
                artifacts.jira_snapshot = raw
            elif artifact_name == "analyzer_output":
                artifacts.analyzer_output = AnalyzerOutput.model_validate(raw)
            elif artifact_name == "planner_output":
                artifacts.planner_output = PlannerOutput.model_validate(raw)
            elif artifact_name == "developer_output":
                artifacts.developer_output = DeveloperOutput.model_validate(raw)
            elif artifact_name == "fixer_output":
                artifacts.fixer_output = FixerOutput.model_validate(raw)
            elif artifact_name == "approval_decision":
                artifacts.approval_decision = ApprovalDecision.model_validate(raw)
            elif artifact_name == "github_branch":
                artifacts.github_branch = GitHubBranchResult.model_validate(raw)
            elif artifact_name == "apply_result":
                artifacts.apply_result = GitHubApplyResult.model_validate(raw)
            elif artifact_name == "github_pull_request":
                artifacts.github_pull_request = GitHubPullRequestResult.model_validate(raw)
            elif artifact_name == "github_handoff_package":
                artifacts.github_handoff_package = GitHubHandoffPackage.model_validate(raw)
            elif artifact_name == "sprint_work_package":
                artifacts.analyzer_output = AnalyzerOutput.model_validate(raw)
            elif artifact_name == "context_bundle":
                analyzer = artifacts.analyzer_output.model_dump(mode="json") if artifacts.analyzer_output else {}
                analyzer.update(raw)
                artifacts.analyzer_output = AnalyzerOutput.model_validate(analyzer)
            elif artifact_name == "implementation_package":
                artifacts.planner_output = PlannerOutput.model_validate(raw)
            elif artifact_name == "review_report":
                artifacts.fixer_output = FixerOutput.model_validate(raw)
        return ALMASRunDetailRead.model_validate(
            {
                "manifest": manifest.model_dump(mode="json"),
                "artifacts": artifacts.model_dump(mode="json"),
            }
        )

    def list_runs(self) -> list[ALMASRunSummaryRead]:
        index = self._read_index()
        items = [ALMASRunSummaryRead.model_validate(item) for item in index.values()]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items

    def latest_run_for_issue(self, issue_key: str) -> ALMASRunDetailRead | None:
        matches = [item for item in self.list_runs() if item.issue_key.upper() == issue_key.upper()]
        if not matches:
            return None
        return self.load_run(matches[0].run_id)

    def delete_run(self, run_id: str) -> None:
        with self._lock:
            run_dir = self._run_dir(run_id)
            if run_dir.exists():
                shutil.rmtree(run_dir)
            index = self._read_index()
            if run_id in index:
                del index[run_id]
                self._write_index(index)

    def delete_runs_for_issue(self, issue_key: str) -> list[str]:
        normalized = issue_key.upper()
        with self._lock:
            index = self._read_index()
            run_ids = [
                run_id
                for run_id, item in index.items()
                if str((item or {}).get("issue_key") or "").upper() == normalized
            ]
            for run_id in run_ids:
                run_dir = self._run_dir(run_id)
                if run_dir.exists():
                    shutil.rmtree(run_dir)
                index.pop(run_id, None)
            self._write_index(index)
        return run_ids

    def _run_dir(self, run_id: str) -> Path:
        return self._root / run_id

    def _read_index(self) -> dict[str, Any]:
        if not self._index_path.exists():
            return {}
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_index(self, payload: dict[str, Any]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
