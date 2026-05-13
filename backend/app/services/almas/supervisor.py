from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from agents import ALMASAgentSuite
from app.config import Settings, get_settings
from app.schemas.almas import (
    ALMASRunDetailRead,
    ALMASRunManifest,
    AnalyzerOutput,
    ApprovalDecision,
    FixerOutput,
    PlannerOutput,
)
from app.services.almas.github_adapter import GitHubAdapter, LocalGitHubAdapter
from app.services.almas.store import ALMASRunStore
from app.services.jira_service import JiraIssueAnalysis, JiraPipelineService


ANALYZER_CONFIDENCE_THRESHOLD = 0.55
logger = logging.getLogger("app.almas")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ALMASSupervisor:
    def __init__(
        self,
        settings: Settings | None = None,
        jira_service: JiraPipelineService | None = None,
        agent_suite: ALMASAgentSuite | None = None,
        store: ALMASRunStore | None = None,
        github_adapter: GitHubAdapter | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._jira_service = jira_service or JiraPipelineService(self._settings)
        self._agent_suite = agent_suite
        self._store = store or ALMASRunStore(self._settings)
        self._github_adapter = github_adapter or LocalGitHubAdapter(self._settings)

    @property
    def _agents(self) -> ALMASAgentSuite:
        if self._agent_suite is None:
            self._agent_suite = ALMASAgentSuite(self._settings)
        return self._agent_suite

    def list_runs(self):
        return self._store.list_runs()

    def get_run(self, run_id: str) -> ALMASRunDetailRead:
        return self._store.load_run(run_id)

    def latest_run_for_issue(self, issue_key: str) -> ALMASRunDetailRead | None:
        return self._store.latest_run_for_issue(issue_key)

    def start_run(self, issue_key: str) -> ALMASRunDetailRead:
        issue_payload = self._jira_service.create_client().get_issue(issue_key)
        analysis = self._jira_service.analyze_issue(issue_payload)
        run_id = self._new_run_id(analysis.issue_key)
        manifest = self._store.create_run(run_id, analysis.issue_key, self._agents.model_names)
        self._write_artifact(manifest, "jira_snapshot", issue_payload)
        manifest.status = "running"
        manifest.current_stage = "jira_snapshot"
        manifest.explanation = f"Fetched Jira issue {analysis.issue_key}."
        self._store.save_manifest(manifest)
        return self._run_pipeline(manifest, analysis)

    def retry_run(self, run_id: str, refresh_from_jira: bool = True) -> ALMASRunDetailRead:
        detail = self._store.load_run(run_id)
        manifest = detail.manifest
        issue_payload = detail.artifacts.jira_snapshot or {}
        if refresh_from_jira:
            issue_payload = self._jira_service.create_client().get_issue(manifest.issue_key)
            self._write_artifact(manifest, "jira_snapshot", issue_payload)
        analysis = self._jira_service.analyze_issue(issue_payload)

        revision_requests = None
        start_stage = "analyzer"
        if manifest.status == "needs_review_revision" and detail.artifacts.fixer_output:
            revision_requests = detail.artifacts.fixer_output.revision_requests
            start_stage = "planner"
        manifest.status = "running"
        manifest.current_stage = start_stage
        manifest.explanation = f"Retrying run from {start_stage}."
        self._store.save_manifest(manifest)
        return self._run_pipeline(manifest, analysis, start_stage=start_stage, revision_requests=revision_requests)

    def approve_run(self, run_id: str, approved_by: str = "human", notes: str = "") -> ALMASRunDetailRead:
        detail = self._store.load_run(run_id)
        manifest = detail.manifest
        if manifest.status != "needs_approval":
            raise ValueError(f"Run {run_id} is not waiting for approval.")
        if not detail.artifacts.planner_output or not detail.artifacts.fixer_output:
            raise ValueError(f"Run {run_id} is missing required artifacts for approval.")

        manifest.status = "approved"
        manifest.current_stage = "approval"
        manifest.explanation = f"Approved by {approved_by}."
        self._store.save_manifest(manifest)
        approval = ApprovalDecision(
            approved=True,
            approved_by=approved_by,
            notes=notes,
            approved_at=_now(),
        )
        self._write_artifact(manifest, "approval_decision", approval)

        handoff = self._github_adapter.prepare_handoff(
            detail.artifacts.planner_output,
            detail.artifacts.fixer_output,
        )
        self._write_artifact(manifest, "github_handoff_package", handoff)
        manifest.status = "completed"
        manifest.current_stage = "github_handoff"
        manifest.explanation = "GitHub handoff package generated."
        self._store.save_manifest(manifest)
        return self._store.load_run(run_id)

    def preview_implementation(self, issue_key: str) -> PlannerOutput:
        logger.info("ALMAS preview started | issue_key=%s mode=fresh_jira", issue_key)
        issue_payload = self._jira_service.create_client().get_issue(issue_key)
        analysis = self._jira_service.analyze_issue(issue_payload)
        return self.preview_implementation_for_analysis(analysis)

    def preview_implementation_for_analysis(self, analysis: JiraIssueAnalysis) -> PlannerOutput:
        logger.info("ALMAS analyzer agent started | issue_key=%s", analysis.issue_key)
        analyzer = self._agents.run_analyzer(analysis)
        logger.info(
            "ALMAS analyzer agent completed | issue_key=%s confidence=%.2f clarification_needed=%s blocked=%s",
            analysis.issue_key,
            analyzer.confidence,
            analyzer.clarification_needed,
            bool(analyzer.blocked_reason),
        )
        if analyzer.clarification_needed or analyzer.confidence < ANALYZER_CONFIDENCE_THRESHOLD:
            raise ValueError("Analyzer requires clarification before a safe plan can be generated.")
        if analyzer.blocked_reason:
            raise ValueError(analyzer.blocked_reason)
        logger.info("ALMAS planner agent started | issue_key=%s", analysis.issue_key)
        implementation = self._agents.run_planner(analysis, analyzer)
        logger.info(
            "ALMAS planner agent completed | issue_key=%s steps=%s planned_changes=%s",
            analysis.issue_key,
            len(implementation.implementation_steps),
            len(implementation.planned_changes),
        )
        return implementation

    def _run_pipeline(
        self,
        manifest: ALMASRunManifest,
        analysis: JiraIssueAnalysis,
        start_stage: str = "analyzer",
        revision_requests: list[str] | None = None,
    ) -> ALMASRunDetailRead:
        try:
            analyzer_artifact: AnalyzerOutput | None = None
            if start_stage == "analyzer":
                logger.info("ALMAS analyzer agent started | issue_key=%s run_id=%s", analysis.issue_key, manifest.run_id)
                analyzer_artifact = self._agents.run_analyzer(analysis)
                self._write_artifact(manifest, "analyzer_output", analyzer_artifact)
                if analyzer_artifact.clarification_needed or analyzer_artifact.confidence < ANALYZER_CONFIDENCE_THRESHOLD:
                    return self._finish(
                        manifest,
                        "needs_clarification",
                        "analyzer",
                        "Analyzer requires clarification before safe planning.",
                    )
                if analyzer_artifact.blocked_reason:
                    reason = analyzer_artifact.blocked_reason
                    return self._finish(manifest, "blocked", "analyzer", reason)
            else:
                detail = self._store.load_run(manifest.run_id)
                analyzer_artifact = detail.artifacts.analyzer_output
                if not analyzer_artifact:
                    return self._finish(
                        manifest,
                        "failed",
                        start_stage,
                        "Retry requested without the required prior artifacts.",
                    )

            logger.info("ALMAS planner agent started | issue_key=%s run_id=%s", analysis.issue_key, manifest.run_id)
            planner_output = self._agents.run_planner(
                analysis,
                analyzer_artifact,
                revision_requests=revision_requests,
            )
            self._write_artifact(manifest, "planner_output", planner_output)
            logger.info("ALMAS fixer agent started | issue_key=%s run_id=%s", analysis.issue_key, manifest.run_id)
            fixer_output = self._agents.run_fixer(
                analyzer_artifact,
                planner_output,
            )
            self._write_artifact(manifest, "fixer_output", fixer_output)
            manifest.latest_fixer_decision = fixer_output.decision
            self._store.save_manifest(manifest)

            if fixer_output.decision == "approved":
                return self._finish(
                    manifest,
                    "needs_approval",
                    "fixer",
                    "Fixer approved the plan. Waiting for human approval before GitHub handoff.",
                )

            if fixer_output.decision == "blocked":
                reason = "; ".join(fixer_output.rejection_reasons or ["Fixer blocked the plan."])
                return self._finish(manifest, "blocked", "fixer", reason)

            if manifest.revision_count < self._settings.almas_max_review_revisions:
                manifest.revision_count += 1
                self._store.save_manifest(manifest)
                revised_planner_output = self._agents.run_planner(
                    analysis,
                    analyzer_artifact,
                    revision_requests=fixer_output.revision_requests,
                )
                self._write_artifact(manifest, "planner_output", revised_planner_output)
                revised_fixer_output = self._agents.run_fixer(
                    analyzer_artifact,
                    revised_planner_output,
                )
                self._write_artifact(manifest, "fixer_output", revised_fixer_output)
                manifest.latest_fixer_decision = revised_fixer_output.decision
                self._store.save_manifest(manifest)
                if revised_fixer_output.decision == "approved":
                    return self._finish(
                        manifest,
                        "needs_approval",
                        "fixer",
                        "Fixer approved the plan after one revision. Waiting for human approval.",
                    )
                if revised_fixer_output.decision == "blocked":
                    reason = "; ".join(revised_fixer_output.rejection_reasons or ["Fixer blocked the revised plan."])
                    return self._finish(manifest, "blocked", "fixer", reason)

            return self._finish(
                manifest,
                "needs_review_revision",
                "fixer",
                "Fixer still requires revisions after the allowed retry loop.",
            )
        except Exception as exc:
            return self._finish(manifest, "failed", manifest.current_stage or start_stage, str(exc))

    def _finish(
        self,
        manifest: ALMASRunManifest,
        status: str,
        stage: str,
        explanation: str,
    ) -> ALMASRunDetailRead:
        manifest.status = status
        manifest.current_stage = stage
        manifest.explanation = explanation
        self._store.save_manifest(manifest)
        return self._store.load_run(manifest.run_id)

    def _write_artifact(self, manifest: ALMASRunManifest, artifact_name: str, payload) -> None:
        filename = self._store.write_artifact(manifest.run_id, artifact_name, payload)
        manifest.artifact_files[artifact_name] = filename
        self._store.save_manifest(manifest)

    def _new_run_id(self, issue_key: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{issue_key.lower()}-{timestamp}-{uuid4().hex[:8]}"
