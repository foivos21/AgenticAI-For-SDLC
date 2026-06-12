"""Inject / restore single-file bugs and create the matching Jira tickets.

Also provides :func:`run_feature_grading` for multi-file feature fixtures
(:class:`~app.eval.bug_catalog.FeatureFixture`) where there is no inject step
and grading is purely test-driven.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings, get_settings
from app.eval.bug_catalog import BugFixture, FeatureFixture
from app.services.jira_service import JiraApiError, JiraPipelineService

# backend/app/eval/harness.py -> parents[3] == repository root
REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"


class HarnessError(RuntimeError):
    pass


def _target_path(fixture: BugFixture) -> Path:
    return REPO_ROOT / fixture.target_file


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )


def git_commit_push(fixture: BugFixture, *, action: str, push: bool = True) -> str:
    """Stage, commit, and (optionally) push the fixture's target file.

    ``action`` is 'inject' or 'restore'. Returns a short human-readable status.
    Pushing the change to ``main`` keeps GitHub in sync with the local working
    tree so ALMAS branches from the same (broken) base it is asked to fix.
    """
    message = f"eval: {action} {fixture.slug} bug"
    add = _git(["add", "--", fixture.target_file])
    if add.returncode != 0:
        raise HarnessError(f"git add failed: {add.stderr.strip()}")
    # If nothing is staged for this file, there is nothing to commit. This is
    # robust across git's varied wording ("nothing to commit", "no changes
    # added to commit", …) and avoids sweeping in other unrelated changes.
    if _git(["diff", "--cached", "--quiet", "--", fixture.target_file]).returncode == 0:
        return "nothing to commit (already in sync)"
    commit = _git(["commit", "-m", message, "--", fixture.target_file])
    if commit.returncode != 0:
        raise HarnessError(f"git commit failed: {(commit.stdout + commit.stderr).strip()}")
    if not push:
        return f"committed locally: {message}"
    pushed = _git(["push"])
    if pushed.returncode != 0:
        raise HarnessError(f"git push failed: {(pushed.stdout + pushed.stderr).strip()}")
    return f"committed and pushed: {message}"


def git_pull() -> str:
    """Fast-forward the local branch to match the remote (after a merge)."""
    pulled = _git(["pull", "--ff-only"])
    if pulled.returncode != 0:
        raise HarnessError(f"git pull failed: {(pulled.stdout + pulled.stderr).strip()}")
    return pulled.stdout.strip().splitlines()[-1] if pulled.stdout.strip() else "already up to date"


def fixture_status(fixture: BugFixture) -> str:
    """Return 'clean', 'broken', or 'unknown' for the fixture's target file."""
    path = _target_path(fixture)
    if not path.exists():
        return "missing"
    text = path.read_text(encoding="utf-8")
    has_correct = fixture.correct in text
    has_broken = fixture.broken in text
    if has_broken and not has_correct:
        return "broken"
    if has_correct and not has_broken:
        return "clean"
    return "unknown"


def inject(fixture: BugFixture) -> bool:
    """Swap the correct snippet for the broken one. Returns True if changed."""
    path = _target_path(fixture)
    if not path.exists():
        raise HarnessError(f"Target file not found: {fixture.target_file}")
    text = path.read_text(encoding="utf-8")
    if fixture.broken in text and fixture.correct not in text:
        return False  # already injected
    if fixture.correct not in text:
        raise HarnessError(
            f"Could not inject '{fixture.slug}': expected snippet not found in "
            f"{fixture.target_file}. The file may already be modified."
        )
    path.write_text(text.replace(fixture.correct, fixture.broken, 1), encoding="utf-8")
    return True


def restore(fixture: BugFixture) -> bool:
    """Swap the broken snippet back to the correct one. Returns True if changed."""
    path = _target_path(fixture)
    if not path.exists():
        raise HarnessError(f"Target file not found: {fixture.target_file}")
    text = path.read_text(encoding="utf-8")
    if fixture.correct in text and fixture.broken not in text:
        return False  # already clean
    if fixture.broken not in text:
        raise HarnessError(
            f"Could not restore '{fixture.slug}': broken snippet not found in "
            f"{fixture.target_file}."
        )
    path.write_text(text.replace(fixture.broken, fixture.correct, 1), encoding="utf-8")
    return True


@dataclass
class TicketResult:
    slug: str
    issue_key: str
    browse_url: str


def create_ticket(
    fixture: BugFixture | FeatureFixture,
    *,
    service: JiraPipelineService | None = None,
    settings: Settings | None = None,
) -> TicketResult:
    resolved_settings = settings or get_settings()
    if not resolved_settings.jira_integration_enabled:
        missing = ", ".join(resolved_settings.jira_missing_required)
        raise HarnessError(f"Jira integration disabled. Missing: {missing}")
    pipeline = service or JiraPipelineService(resolved_settings)
    try:
        created = pipeline.create_issue(
            summary=fixture.summary,
            description=fixture.description,
            issue_type=fixture.issue_type,
            labels=fixture.labels,
            priority=fixture.priority,
        )
    except JiraApiError as exc:
        raise HarnessError(f"Failed to create ticket for '{fixture.slug}': {exc}") from exc
    return TicketResult(
        slug=fixture.slug,
        issue_key=created.get("issue_key", ""),
        browse_url=created.get("browse_url", ""),
    )


def verify(fixture: BugFixture) -> tuple[bool | None, str]:
    """Grade a fixture.

    Returns ``(passed, message)``. ``passed`` is ``None`` when the fixture has no
    automated test (verify the fix manually via the app/PR); otherwise it is the
    pytest result. The current status ('clean'/'broken') is always reported.
    """
    status = fixture_status(fixture)
    if not fixture.test_file:
        return None, f"no automated test — current file status: {status}"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", fixture.test_file, "-q"],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
    )
    output = (completed.stdout + completed.stderr).strip()
    tail = "\n".join(output.splitlines()[-8:])
    return completed.returncode == 0, tail


def run_grading_with_changes(fixture: BugFixture, developer_output) -> dict:
    """Apply the developer's proposed changes, run the grading test, then revert.

    Returns a dict the Fixer can read: ``{ran, passed, output}``. The working
    tree is always restored to its prior state, even if the test errors.
    """
    if not fixture.test_file:
        return {"ran": False, "reason": "no grading test for this fixture"}

    backups: dict[str, tuple[bool, str | None]] = {}
    try:
        for change in developer_output.changes:
            path = REPO_ROOT / change.path
            existed = path.exists()
            backups[change.path] = (existed, path.read_text(encoding="utf-8") if existed else None)
            if change.operation == "delete":
                if existed:
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(change.content, encoding="utf-8")

        passed, output = verify(fixture)
        return {"ran": True, "passed": bool(passed), "output": output}
    finally:
        for rel_path, (existed, content) in backups.items():
            path = REPO_ROOT / rel_path
            if existed:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content or "", encoding="utf-8")
            elif path.exists():
                path.unlink()


# ---------------------------------------------------------------------------
# Feature fixture helpers (no inject/restore — grading is purely test-driven)
# ---------------------------------------------------------------------------

def feature_status(fixture: FeatureFixture) -> str:
    """Run the grading suite and return 'passing', 'failing', or 'error'."""
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", fixture.test_file, "-q"],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
    )
    combined = (completed.stdout + completed.stderr).lower()
    if completed.returncode == 0:
        return "passing"
    if "error" in combined and "failed" not in combined:
        return "error"
    return "failing"


def verify_feature(fixture: FeatureFixture) -> tuple[bool, str]:
    """Run the grading test suite for a feature fixture.

    Returns ``(passed, tail_output)`` — always runs (there is always a test file).
    """
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", fixture.test_file, "-q"],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
    )
    output = (completed.stdout + completed.stderr).strip()
    tail = "\n".join(output.splitlines()[-12:])
    return completed.returncode == 0, tail


def run_feature_grading(fixture: FeatureFixture, developer_output) -> dict:
    """Apply the developer's proposed multi-file changes, run grading tests, then revert.

    The working tree is always fully restored after the run — every file that
    existed before is put back; every file created by the changes that did not
    exist before is removed.

    Returns ``{"ran": True, "passed": bool, "output": str}``.
    """
    backups: dict[str, tuple[bool, str | None]] = {}
    try:
        for change in developer_output.changes:
            path = REPO_ROOT / change.path
            existed = path.exists()
            backups[change.path] = (existed, path.read_text(encoding="utf-8") if existed else None)
            if change.operation == "delete":
                if existed:
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(change.content, encoding="utf-8")

        passed, output = verify_feature(fixture)
        return {"ran": True, "passed": passed, "output": output}
    finally:
        for rel_path, (existed, content) in backups.items():
            path = REPO_ROOT / rel_path
            if existed:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content or "", encoding="utf-8")
            elif path.exists():
                path.unlink()
