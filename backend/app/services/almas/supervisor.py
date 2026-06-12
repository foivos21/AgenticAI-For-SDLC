from __future__ import annotations

import difflib
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from agents import ALMASAgentSuite
from app.config import Settings, get_settings
from app.schemas.almas import (
    AgentTimingInfo,
    ALMASRunDetailRead,
    ALMASRunManifest,
    AnalyzerOutput,
    ApprovalDecision,
    DeveloperOutput,
    FileDiffPreview,
    FixerOutput,
    PlannerOutput,
)
from app.services.almas.github_adapter import (
    DisabledGitHubAdapter,
    GitHubAdapter,
    GitHubAdapterError,
    LocalGitHubAdapter,
)
from app.services.almas.logging import log_stage_payload
from app.services.almas.repository import RepositoryError, slugify_branch_component
from app.services.almas.store import ALMASRunStore
from app.services.jira_service import JiraIssueAnalysis, JiraPipelineService


ANALYZER_CONFIDENCE_THRESHOLD = 0.55
MAX_AUTOMATIC_REPAIR_PASSES = 3
logger = logging.getLogger("app.almas")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preview(text: str | None, limit: int = 100) -> str:
    """Collapse text to a single short line for step output."""
    flattened = " ".join((text or "").split())
    if len(flattened) <= limit:
        return flattened or "—"
    return flattened[:limit].rstrip() + "…"


# Paths ALMAS must never modify (e.g. the tests that grade its own fixes).
_PROTECTED_PATH_PARTS = {"eval_grading"}


def _is_protected_path(path: str) -> bool:
    parts = {part for part in path.replace("\\", "/").split("/") if part}
    return bool(parts & _PROTECTED_PATH_PARTS)


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
        if github_adapter is not None:
            self._github_adapter = github_adapter
        elif self._settings.github_integration_enabled:
            self._github_adapter = LocalGitHubAdapter(self._settings)
        else:
            self._github_adapter = DisabledGitHubAdapter(self._settings)
        self._progress: Callable[[str, str], None] | None = None
        self._test_runner: Callable[[DeveloperOutput], dict] | None = None

    def _emit(self, stage: str, message: str) -> None:
        # Always log the step so the backend log clearly shows where we are…
        logger.info("[ALMAS][STEP][%s] %s", stage.upper(), message)
        # …and additionally forward to any live progress sink (e.g. the CLI).
        callback = self._progress
        if callback is not None:
            try:
                callback(stage, message)
            except Exception:  # never let a progress sink break a run
                pass

    def _record_timing(
        self,
        manifest: ALMASRunManifest,
        agent_name: str,
        start_time: float,
        *,
        status: str = "success",
    ) -> float:
        end_time = time.time()
        duration = round(end_time - start_time, 3)
        manifest.timing_history.append(
            AgentTimingInfo(
                agent_name=agent_name,
                start_time=start_time,
                end_time=end_time,
                duration_seconds=duration,
                status=status,
            )
        )
        return duration

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

    def reset_issue(self, issue_key: str) -> list[str]:
        try:
            detail = self._store.latest_run_for_issue(issue_key)
            if detail and detail.manifest and detail.manifest.branch_name:
                try:
                    self._github_adapter.delete_branch(branch_name=detail.manifest.branch_name)
                except Exception:
                    pass
        except Exception:
            pass
        return self._store.delete_runs_for_issue(issue_key)

    def start_run(
        self,
        issue_key: str,
        *,
        progress: Callable[[str, str], None] | None = None,
        test_runner: Callable[[DeveloperOutput], dict] | None = None,
    ) -> ALMASRunDetailRead:
        issue_payload = self._jira_service.create_client().get_issue(issue_key)
        return self.start_run_from_issue_payload(
            issue_payload, progress=progress, test_runner=test_runner
        )

    def start_run_from_issue_payload(
        self,
        issue_payload: dict,
        *,
        progress: Callable[[str, str], None] | None = None,
        test_runner: Callable[[DeveloperOutput], dict] | None = None,
    ) -> ALMASRunDetailRead:
        self._progress = progress
        self._test_runner = test_runner
        if hasattr(self._agents, "reset_token_usage"):
            self._agents.reset_token_usage()
        try:
            analysis = self._jira_service.analyze_issue(issue_payload)
            run_id = self._new_run_id(analysis.issue_key)
            manifest = self._store.create_run(run_id, analysis.issue_key, self._agents.model_names)
            branch_name = self._build_branch_name(analysis)
            manifest.branch_name = branch_name
            self._write_artifact(manifest, "jira_snapshot", issue_payload)
            self._emit("branch", f"Creating branch {branch_name} from {self._settings.github_base_branch}")
            _branch_started = time.time()
            branch_result = self._github_adapter.create_branch(
                issue_key=analysis.issue_key,
                run_id=run_id,
                branch_name=branch_name,
            )
            self._record_timing(manifest, "branch", _branch_started)
            manifest.status = "branch_created"
            manifest.current_stage = "branch_created"
            manifest.explanation = f"Created branch {branch_name}."
            self._write_artifact(manifest, "github_branch", branch_result)
            self._store.save_manifest(manifest)
            return self._run_pipeline(manifest, analysis, branch_name=branch_name)
        finally:
            self._progress = None
            self._test_runner = None

    def retry_run(self, run_id: str, refresh_from_jira: bool = True) -> ALMASRunDetailRead:
        detail = self._store.load_run(run_id)
        manifest = detail.manifest
        issue_payload = detail.artifacts.jira_snapshot or {}
        if refresh_from_jira:
            issue_payload = self._jira_service.create_client().get_issue(manifest.issue_key)
            self._write_artifact(manifest, "jira_snapshot", issue_payload)
        analysis = self._jira_service.analyze_issue(issue_payload)

        revision_requests = None
        if detail.artifacts.fixer_output and manifest.status == "needs_review_revision":
            revision_requests = detail.artifacts.fixer_output.revision_requests
        manifest.status = "running"
        manifest.current_stage = "retry"
        manifest.explanation = "Retrying run."
        self._store.save_manifest(manifest)
        return self._run_pipeline(
            manifest,
            analysis,
            branch_name=manifest.branch_name or self._build_branch_name(analysis),
            revision_requests=revision_requests,
        )

    def approve_run(self, run_id: str, approved_by: str = "human", notes: str = "") -> ALMASRunDetailRead:
        detail = self._store.load_run(run_id)
        manifest = detail.manifest
        if manifest.status != "needs_approval":
            raise ValueError(f"Run {run_id} is not waiting for approval.")
        if not detail.artifacts.github_pull_request:
            raise ValueError(f"Run {run_id} does not have a draft pull request to approve.")

        approval = ApprovalDecision(
            approved=True,
            approved_by=approved_by,
            notes=notes,
            approved_at=_now(),
        )
        self._write_artifact(manifest, "approval_decision", approval)
        updated_pr = self._github_adapter.mark_pr_ready_for_review(
            issue_key=manifest.issue_key,
            run_id=manifest.run_id,
            pull_request=detail.artifacts.github_pull_request,
        )
        self._write_artifact(manifest, "github_pull_request", updated_pr)
        manifest.status = "completed"
        manifest.current_stage = "ready_for_review"
        manifest.pr_number = updated_pr.number
        manifest.pr_url = updated_pr.html_url or updated_pr.url
        manifest.explanation = f"Approved by {approved_by}. Pull request is ready for review."
        self._store.save_manifest(manifest)
        return self._store.load_run(run_id)

    def merge_run(
        self,
        run_id: str,
        *,
        merge_method: str = "squash",
        delete_branch: bool = False,
    ) -> dict:
        """Merge the pull request produced by a run into the base branch."""
        detail = self._store.load_run(run_id)
        manifest = detail.manifest
        pull_request = detail.artifacts.github_pull_request
        if not pull_request or pull_request.number is None:
            raise ValueError(f"Run {run_id} has no pull request to merge.")

        self._emit("merge", f"Merging PR #{pull_request.number}")
        result = self._github_adapter.merge_pull_request(
            number=pull_request.number,
            merge_method=merge_method,
            commit_title=f"{manifest.issue_key}: merge ALMAS fix (#{pull_request.number})",
        )
        merged = bool(result.get("merged"))
        if merged:
            manifest.status = "merged"
            manifest.current_stage = "merged"
            manifest.explanation = (
                f"Pull request #{pull_request.number} merged into {self._settings.github_base_branch}."
            )
            self._store.save_manifest(manifest)
            if delete_branch and manifest.branch_name:
                try:
                    self._github_adapter.delete_branch(branch_name=manifest.branch_name)
                except Exception:
                    pass
        self._emit("merge", "Merged" if merged else f"Merge not completed: {result.get('message')}")
        return {
            "merged": merged,
            "pr_number": pull_request.number,
            "sha": result.get("sha"),
            "message": result.get("message"),
            "branch_name": manifest.branch_name,
            "base_branch": self._settings.github_base_branch,
        }

    def preview_implementation(self, issue_key: str) -> PlannerOutput:
        logger.info("ALMAS preview started | issue_key=%s mode=fresh_jira", issue_key)
        issue_payload = self._jira_service.create_client().get_issue(issue_key)
        analysis = self._jira_service.analyze_issue(issue_payload)
        return self.preview_implementation_for_analysis(analysis)

    def preview_implementation_for_analysis(self, analysis: JiraIssueAnalysis) -> PlannerOutput:
        logger.info("ALMAS analyzer agent started | issue_key=%s", analysis.issue_key)
        analyzer = self._agents.run_analyzer(analysis, run_id=f"preview-{analysis.issue_key.lower()}")
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
        branch_name = self._build_branch_name(analysis)
        implementation = self._agents.run_planner(
            analysis,
            analyzer,
            run_id=f"preview-{analysis.issue_key.lower()}",
            branch_name=branch_name,
        )
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
        *,
        branch_name: str,
        revision_requests: list[str] | None = None,
    ) -> ALMASRunDetailRead:
        try:
            analyzer_artifact = self._run_analyzer(manifest, analysis)
            if analyzer_artifact.clarification_needed or analyzer_artifact.confidence < ANALYZER_CONFIDENCE_THRESHOLD:
                return self._finish(
                    manifest,
                    "needs_clarification",
                    "analyzer",
                    "Analyzer requires clarification before safe planning.",
                )
            if analyzer_artifact.blocked_reason:
                return self._finish(manifest, "blocked", "analyzer", analyzer_artifact.blocked_reason)
            next_revision_requests = revision_requests
            seen_revision_signatures: set[str] = set()
            seen_developer_signatures: set[str] = set()

            while True:
                self._emit("planner", "Planning the fix (steps and files to change)")
                _started = time.time()
                planner_output = self._agents.run_planner(
                    analysis,
                    analyzer_artifact,
                    run_id=manifest.run_id,
                    branch_name=branch_name,
                    revision_requests=next_revision_requests,
                )
                duration = self._record_timing(manifest, "planner", _started)
                self._write_artifact(manifest, "planner_output", planner_output)
                manifest.status = "running"
                manifest.current_stage = "planner"
                manifest.explanation = "Planner output generated."
                self._store.save_manifest(manifest)
                self._emit(
                    "planner",
                    f"Planner done in {duration}s — {len(planner_output.planned_changes)} change(s); "
                    f"summary: {_preview(planner_output.solution_summary)}",
                )

                developer_output, diff_previews, fixer_output = self._run_developer_and_fixer(
                    manifest,
                    analysis,
                    analyzer_artifact,
                    planner_output,
                )
                if fixer_output.decision == "approved":
                    return self._publish_approved_run(
                        manifest,
                        planner_output,
                        developer_output,
                        diff_previews,
                    )
                if fixer_output.decision == "blocked":
                    reason = "; ".join(fixer_output.rejection_reasons or ["Fixer blocked the implementation."])
                    return self._finish(manifest, "blocked", "fixer", reason)

                stop_reason = self._next_revision_stop_reason(
                    manifest,
                    developer_output,
                    fixer_output,
                    seen_revision_signatures=seen_revision_signatures,
                    seen_developer_signatures=seen_developer_signatures,
                )
                if stop_reason:
                    return self._finish(manifest, "needs_review_revision", "fixer", stop_reason)

                manifest.revision_count += 1
                manifest.status = "running"
                manifest.current_stage = "planner"
                manifest.explanation = f"Fixer requested revisions. Starting repair pass {manifest.revision_count + 1}."
                self._store.save_manifest(manifest)
                self._emit(
                    "revision",
                    f"↻ Fixer requested changes — repair pass "
                    f"{manifest.revision_count + 1} (limit {MAX_AUTOMATIC_REPAIR_PASSES + 1}); "
                    "looping back to Planner",
                )
                next_revision_requests = fixer_output.revision_requests
        except Exception as exc:
            return self._finish(manifest, "failed", manifest.current_stage or "pipeline", str(exc))

    def _run_analyzer(self, manifest: ALMASRunManifest, analysis: JiraIssueAnalysis) -> AnalyzerOutput:
        logger.info("ALMAS analyzer agent started | issue_key=%s run_id=%s", analysis.issue_key, manifest.run_id)
        self._emit("analyzer", "Analyzing the issue and locating the relevant code")
        _started = time.time()
        analyzer_artifact = self._agents.run_analyzer(analysis, run_id=manifest.run_id)
        duration = self._record_timing(manifest, "analyzer", _started)
        self._write_artifact(manifest, "analyzer_output", analyzer_artifact)
        manifest.status = "running"
        manifest.current_stage = "analyzer"
        manifest.explanation = "Analyzer output generated."
        self._store.save_manifest(manifest)
        self._emit(
            "analyzer",
            f"Analyzer done in {duration}s — confidence {analyzer_artifact.confidence:.2f}; "
            f"goal: {_preview(analyzer_artifact.goal)}; "
            f"files: {', '.join(analyzer_artifact.candidate_files[:3]) or 'n/a'}",
        )
        return analyzer_artifact

    def _run_developer_and_fixer(
        self,
        manifest: ALMASRunManifest,
        analysis: JiraIssueAnalysis,
        analyzer_artifact: AnalyzerOutput,
        planner_output: PlannerOutput,
    ) -> tuple[DeveloperOutput, list[FileDiffPreview], FixerOutput]:
        self._emit("developer", "Developer writing the code changes")
        _started = time.time()
        developer_output = self._agents.run_developer(
            analysis,
            analyzer_artifact,
            planner_output,
            run_id=manifest.run_id,
        )
        duration = self._record_timing(manifest, "developer", _started)
        _dropped = [c.path for c in developer_output.changes if _is_protected_path(c.path)]
        if _dropped:
            developer_output.changes = [
                c for c in developer_output.changes if not _is_protected_path(c.path)
            ]
            self._emit("developer", f"Ignored protected paths (not applied): {', '.join(_dropped)}")
        self._write_artifact(manifest, "developer_output", developer_output)
        manifest.status = "code_generated"
        manifest.current_stage = "developer"
        manifest.explanation = "Developer generated file changes."
        self._store.save_manifest(manifest)
        self._emit(
            "developer",
            f"Developer done in {duration}s — changed: "
            f"{', '.join(change.path for change in developer_output.changes) or 'none'}",
        )

        diff_previews = self._build_diff_previews(manifest, developer_output)

        test_results: dict | None = None
        if self._test_runner is not None:
            self._emit("test", "Running grading tests against the proposed fix")
            try:
                test_results = self._test_runner(developer_output)
            except Exception as exc:  # never let test execution break the run
                test_results = {"ran": False, "reason": str(exc)}
            if test_results.get("ran"):
                verdict = "PASSED" if test_results.get("passed") else "FAILED"
                self._emit("test", f"Grading tests {verdict}")
            else:
                self._emit("test", f"Grading tests not run ({test_results.get('reason')})")

        self._emit("fixer", "Fixer reviewing the generated changes")
        _started = time.time()
        fixer_output = self._agents.run_fixer(
            analyzer_artifact,
            planner_output,
            developer_output,
            diff_previews,
            run_id=manifest.run_id,
            issue_key=analysis.issue_key,
            test_results=test_results,
        )
        duration = self._record_timing(manifest, "fixer", _started)
        self._write_artifact(manifest, "fixer_output", fixer_output)
        manifest.latest_fixer_decision = fixer_output.decision
        manifest.current_stage = "fixer"
        manifest.explanation = "Fixer reviewed the generated changes."
        self._store.save_manifest(manifest)
        _fixer_reasons = (
            fixer_output.approval_reasons
            if fixer_output.decision == "approved"
            else (fixer_output.rejection_reasons or fixer_output.revision_requests)
        )
        self._emit(
            "fixer",
            f"Fixer decision: {fixer_output.decision} in {duration}s"
            + (f" — {_preview(_fixer_reasons[0])}" if _fixer_reasons else ""),
        )
        return developer_output, diff_previews, fixer_output

    def _publish_approved_run(
        self,
        manifest: ALMASRunManifest,
        planner_output: PlannerOutput,
        developer_output: DeveloperOutput,
        diff_previews: list[FileDiffPreview],
    ) -> ALMASRunDetailRead:
        self._emit("apply", "Committing the changes to the feature branch")
        _started = time.time()
        apply_result = self._github_adapter.apply_changes(
            issue_key=manifest.issue_key,
            run_id=manifest.run_id,
            branch_name=manifest.branch_name or planner_output.branch_name,
            developer_output=developer_output,
            diff_previews=diff_previews,
        )
        self._record_timing(manifest, "apply", _started)
        self._write_artifact(manifest, "apply_result", apply_result)
        manifest.status = "code_applied"
        manifest.current_stage = "code_applied"
        manifest.commit_sha = apply_result.commit_sha
        manifest.explanation = "Generated changes committed to the feature branch."
        self._store.save_manifest(manifest)
        self._emit("apply", f"Committed {apply_result.commit_sha[:8]}")

        self._emit("pull_request", "Opening the draft pull request")
        _started = time.time()
        pull_request = self._github_adapter.open_draft_pr(
            issue_key=manifest.issue_key,
            run_id=manifest.run_id,
            implementation=planner_output,
            apply_result=apply_result,
        )
        self._record_timing(manifest, "pull_request", _started)
        self._write_artifact(manifest, "github_pull_request", pull_request)
        handoff = self._github_adapter.prepare_handoff(planner_output, apply_result, pull_request)
        self._write_artifact(manifest, "github_handoff_package", handoff)
        manifest.status = "needs_approval"
        manifest.current_stage = "draft_pr_opened"
        manifest.pr_number = pull_request.number
        manifest.pr_url = pull_request.html_url or pull_request.url
        manifest.explanation = "Draft pull request opened. Waiting for human approval to mark it ready for review."
        self._flush_token_usage(manifest)
        self._store.save_manifest(manifest)
        self._emit(
            "pull_request",
            f"Draft PR #{pull_request.number} opened: {pull_request.html_url or pull_request.url}",
        )
        return self._store.load_run(manifest.run_id)

    def _build_diff_previews(self, manifest: ALMASRunManifest, developer_output: DeveloperOutput) -> list[FileDiffPreview]:
        previews: list[FileDiffPreview] = []
        repository = self._agents.repository
        for change in developer_output.changes:
            before_content = ""
            try:
                before_content = repository.read_text_file(change.path)
            except (FileNotFoundError, RepositoryError):
                before_content = ""
            after_content = "" if change.operation == "delete" else change.content
            diff = "\n".join(
                difflib.unified_diff(
                    before_content.splitlines(),
                    after_content.splitlines(),
                    fromfile=f"a/{change.path}",
                    tofile=f"b/{change.path}",
                    lineterm="",
                )
            )
            previews.append(
                FileDiffPreview(
                    path=change.path,
                    operation=change.operation,
                    before_content=before_content,
                    after_content=after_content,
                    diff=diff,
                )
            )
        log_stage_payload(
            self._settings,
            run_id=manifest.run_id,
            issue_key=manifest.issue_key,
            agent="apply",
            stage="input",
            model="internal",
            payload={"diff_previews": [item.model_dump(mode="json") for item in previews]},
        )
        return previews

    def _build_branch_name(self, analysis: JiraIssueAnalysis) -> str:
        summary_slug = slugify_branch_component(analysis.summary or analysis.issue_key)
        return f"feature/{analysis.issue_key.upper()}-{summary_slug}"

    def _next_revision_stop_reason(
        self,
        manifest: ALMASRunManifest,
        developer_output: DeveloperOutput,
        fixer_output: FixerOutput,
        *,
        seen_revision_signatures: set[str],
        seen_developer_signatures: set[str],
    ) -> str | None:
        if not fixer_output.revision_requests:
            return "Fixer requested revisions but did not provide actionable revision requests."
        if manifest.revision_count >= MAX_AUTOMATIC_REPAIR_PASSES:
            return (
                "Fixer requested more revisions, but the automatic repair limit was reached "
                f"after {MAX_AUTOMATIC_REPAIR_PASSES} revision pass"
                f"{'' if MAX_AUTOMATIC_REPAIR_PASSES == 1 else 'es'}."
            )

        revision_signature = json.dumps(sorted(fixer_output.revision_requests))
        if revision_signature in seen_revision_signatures:
            return "Fixer repeated the same revision requests, so the run stopped to avoid looping indefinitely."
        seen_revision_signatures.add(revision_signature)

        developer_signature = json.dumps(developer_output.model_dump(mode="json"), sort_keys=True)
        if developer_signature in seen_developer_signatures:
            return "Developer produced the same file changes again after review feedback, so the run stopped."
        seen_developer_signatures.add(developer_signature)
        return None

    def _flush_token_usage(self, manifest: ALMASRunManifest) -> None:
        """Write accumulated token totals from the agent suite into the manifest."""
        if hasattr(self._agents, "token_usage"):
            usage = self._agents.token_usage
            manifest.total_prompt_tokens = usage.get("request_tokens", 0)
            manifest.total_completion_tokens = usage.get("response_tokens", 0)

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
        self._flush_token_usage(manifest)
        self._store.save_manifest(manifest)
        self._emit(status, explanation)
        return self._store.load_run(manifest.run_id)

    def _write_artifact(self, manifest: ALMASRunManifest, artifact_name: str, payload) -> None:
        filename = self._store.write_artifact(manifest.run_id, artifact_name, payload)
        manifest.artifact_files[artifact_name] = filename
        self._store.save_manifest(manifest)

    def _new_run_id(self, issue_key: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{issue_key.lower()}-{timestamp}-{uuid4().hex[:8]}"
