"""Command-line interface for the ALMAS evaluation harness.

Bug fixture commands (single-file, reversible defects):

    python -m app.eval.cli list
    python -m app.eval.cli inject --all
    python -m app.eval.cli tickets --all
    python -m app.eval.cli run --all          # inject + create tickets
    python -m app.eval.cli verify --all
    python -m app.eval.cli restore --all
    python -m app.eval.cli flow <slug>        # end-to-end: inject → ticket → pipeline → merge

Feature fixture commands (multi-file missing features, no injection step):

    python -m app.eval.cli feature-list
    python -m app.eval.cli feature-verify <slug>
    python -m app.eval.cli feature-flow <slug>  # ticket → pipeline → merge
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import PurePosixPath

from app.eval import (
    ALL_BUG_FIXTURES,
    BUG_FIXTURES,
    MEDIUM_BUG_FIXTURES,
    BugFixture,
    FEATURE_FIXTURES,
    FeatureFixture,
    get_fixture,
    get_feature,
)
from app.eval import harness


_ANSI_RESET = "\033[0m"
# Bright ANSI foreground colour codes used to tell agents apart at a glance.
_COLOR_PALETTE = [31, 32, 33, 34, 35, 36, 91, 92, 93, 94, 95, 96]
_STAGE_COLORS: dict[str, str] = {}
_SHUFFLED_PALETTE: list[int] = []


def _color_for(stage: str) -> str:
    """Assign a stable, randomly-chosen colour to each distinct agent/stage."""
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return ""
    if not _SHUFFLED_PALETTE:
        _SHUFFLED_PALETTE.extend(_COLOR_PALETTE)
        random.shuffle(_SHUFFLED_PALETTE)
    if stage not in _STAGE_COLORS:
        code = _SHUFFLED_PALETTE[len(_STAGE_COLORS) % len(_SHUFFLED_PALETTE)]
        _STAGE_COLORS[stage] = f"\033[{code}m"
    return _STAGE_COLORS[stage]


def _paint(stage: str, text: str) -> str:
    color = _color_for(stage)
    return f"{color}{text}{_ANSI_RESET}" if color else text


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


class _Tee:
    """Mirror writes to a real stream and a log file (ANSI codes stripped).

    Installed over ``sys.stdout``/``sys.stderr`` for the duration of a bench run
    so the terminal still shows live (coloured) output while a clean, plain-text
    copy of *everything* printed is captured to a ``.log`` file.
    """

    def __init__(self, stream, log_handle) -> None:
        self._stream = stream
        self._log = log_handle

    def write(self, data: str) -> int:
        self._stream.write(data)
        self._log.write(_ANSI_RE.sub("", data))
        return len(data)

    def flush(self) -> None:
        self._stream.flush()
        self._log.flush()

    def isatty(self) -> bool:
        # Proxy the real stream so colour detection still works on the terminal.
        return self._stream.isatty()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _numeric_summary(values: list[float] | list[int]) -> dict | None:
    """Return mean/min/median/max/n for a numeric list, or None when empty."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return {
        "mean": round(statistics.mean(vals), 3),
        "min": min(vals),
        "median": round(statistics.median(vals), 3),
        "max": max(vals),
        "n": len(vals),
    }


def _print_timings(manifest) -> None:
    history = list(manifest.timing_history or [])
    if not history:
        return
    print("[flow] step timings:")
    total = 0.0
    for entry in history:
        print(f"   {entry.agent_name:<14}{entry.duration_seconds:>9.3f}s  [{entry.status}]")
        total += entry.duration_seconds
    print(f"   {'PIPELINE TOTAL':<14}{total:>9.3f}s")


def _select(slugs: list[str], use_all: bool, *, easy: bool = False, medium: bool = False) -> list[BugFixture]:
    if easy:
        pool = list(BUG_FIXTURES)
    elif medium:
        pool = list(MEDIUM_BUG_FIXTURES)
    else:
        pool = list(ALL_BUG_FIXTURES)
    if use_all or not slugs:
        return pool
    return [get_fixture(slug) for slug in slugs]


def _cmd_list(_: argparse.Namespace) -> int:
    print(f"{'SLUG':<36} {'LEVEL':<8} {'STATUS':<8} TARGET FILE")
    print("-" * 90)
    for fixture in BUG_FIXTURES:
        status = harness.fixture_status(fixture)
        print(f"{fixture.slug:<36} {'easy':<8} {status:<8} {fixture.target_file}")
    for fixture in MEDIUM_BUG_FIXTURES:
        status = harness.fixture_status(fixture)
        print(f"{fixture.slug:<36} {'medium':<8} {status:<8} {fixture.target_file}")
    return 0


def _cmd_inject(args: argparse.Namespace) -> int:
    for fixture in _select(args.slugs, args.all, easy=getattr(args, "easy", False), medium=getattr(args, "medium", False)):
        changed = harness.inject(fixture)
        state = "injected" if changed else "already broken"
        print(f"[inject] {fixture.slug}: {state}")
        if not args.no_git:
            print(f"[git]    {harness.git_commit_push(fixture, action='inject')}")
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    for fixture in _select(args.slugs, args.all, easy=getattr(args, "easy", False), medium=getattr(args, "medium", False)):
        changed = harness.restore(fixture)
        state = "restored" if changed else "already clean"
        print(f"[restore] {fixture.slug}: {state}")
        if not args.no_git:
            print(f"[git]     {harness.git_commit_push(fixture, action='restore')}")
    return 0


def _cmd_tickets(args: argparse.Namespace) -> int:
    for fixture in _select(args.slugs, args.all, easy=getattr(args, "easy", False), medium=getattr(args, "medium", False)):
        result = harness.create_ticket(fixture)
        print(f"[ticket] {fixture.slug}: {result.issue_key} {result.browse_url}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    for fixture in _select(args.slugs, args.all, easy=getattr(args, "easy", False), medium=getattr(args, "medium", False)):
        changed = harness.inject(fixture)
        state = "injected" if changed else "already broken"
        print(f"[run] {fixture.slug}: {state}")
        if not args.no_git:
            print(f"[git] {harness.git_commit_push(fixture, action='inject')}")
        result = harness.create_ticket(fixture)
        print(f"[run] {fixture.slug}: ticket -> {result.issue_key} {result.browse_url}")
    return 0


def _cmd_flow(args: argparse.Namespace) -> int:
    from app.services.almas.supervisor import ALMASSupervisor

    fixture = get_fixture(args.slug)

    # 1. Break the file and push it so GitHub main matches what ALMAS will read.
    changed = harness.inject(fixture)
    print(f"[flow] {fixture.slug}: {'injected' if changed else 'already broken'}")
    if not args.no_git:
        print(f"[flow] git: {harness.git_commit_push(fixture, action='inject')}")

    # 2. Resolve the Jira ticket.
    if args.issue:
        issue_key = args.issue.upper()
        print(f"[flow] using existing ticket {issue_key}")
    else:
        ticket = harness.create_ticket(fixture)
        issue_key = ticket.issue_key
        print(f"[flow] created ticket {issue_key} {ticket.browse_url}")

    # 3. Run the ALMAS pipeline with live step printing.
    supervisor = ALMASSupervisor()

    def printer(stage: str, message: str) -> None:
        print(_paint(stage, f"   └─ [{stage}] {message}"), flush=True)

    print(f"[flow] starting ALMAS pipeline for {issue_key} …")
    flow_started = time.time()
    detail = supervisor.start_run(
        issue_key,
        progress=printer,
        test_runner=lambda dev: harness.run_grading_with_changes(fixture, dev),
    )
    manifest = detail.manifest
    print(f"[flow] pipeline finished: status={manifest.status}")
    _print_timings(manifest)

    pull_request = detail.artifacts.github_pull_request
    if manifest.status != "needs_approval" or not pull_request:
        print(f"[flow] no pull request to merge — {manifest.explanation}")
        print(f"[flow] total time so far: {time.time() - flow_started:.3f}s")
        return 0
    print(f"[flow] PR #{pull_request.number}: {pull_request.html_url or pull_request.url}")

    # 4. Ask whether to merge.
    if args.no_merge:
        print("[flow] --no-merge set; leaving the PR open.")
        print(f"[flow] total time (start → PR): {time.time() - flow_started:.3f}s")
        return 0
    if not args.yes:
        answer = input("Merge this PR? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("[flow] merge skipped; PR left open.")
            print(f"[flow] total time (start → PR): {time.time() - flow_started:.3f}s")
            return 0

    result = supervisor.merge_run(manifest.run_id, delete_branch=args.delete_branch)
    if not result.get("merged"):
        print(f"[flow] merge not completed: {result.get('message')}")
        return 1
    print(f"[flow] merged PR #{result['pr_number']} into {result['base_branch']}.")

    # 5. Pull main so the local tree is fixed and clean.
    if not args.no_git:
        try:
            print(f"[flow] git pull: {harness.git_pull()}")
        except harness.HarnessError as exc:
            print(f"[flow] warning: {exc}")
    print(f"[flow] file status now: {harness.fixture_status(fixture)}")
    print(f"[flow] TOTAL TIME (start of flow → issue resolved): {time.time() - flow_started:.3f}s")
    return 0


_PIPELINE_STAGES = ("analyzer", "planner", "developer", "fixer")


def _classify_failure(manifest, fixed: bool | None) -> str:
    """Return a stage-level label describing why (or whether) the pipeline failed.

    Values:
      none             — pipeline produced a PR and the grading test passed
      wrong_fix        — PR was created but the grading test failed
      no_merge         — bench ran with --no-merge; outcome unknown
      fixer_blocked    — the Fixer agent explicitly decided to block the run
      analyzer_failed  — pipeline errored/aborted while in the Analyzer stage
      planner_failed   — pipeline errored/aborted while in the Planner stage
      developer_failed — pipeline errored/aborted while in the Developer stage
      fixer_failed     — pipeline errored/aborted during a Fixer revision loop
      pipeline_failed  — pipeline failed at an unattributed stage
      no_pr            — pipeline finished in an unexpected state with no PR
    """
    status = manifest.status
    stage = (manifest.current_stage or "").lower()

    if fixed is True:
        return "none"
    if status == "needs_approval" and fixed is False:
        return "wrong_fix"
    if status == "needs_approval" and fixed is None:
        return "no_merge"
    if status == "blocked":
        return "fixer_blocked"
    if status in ("failed", "needs_review_revision"):
        for keyword in _PIPELINE_STAGES:
            if keyword in stage:
                return f"{keyword}_failed"
        return "pipeline_failed"
    return "no_pr"


def _stage_times_from_history(timing_history) -> dict[str, float]:
    """Aggregate per-stage wall-clock seconds from manifest timing history."""
    totals: dict[str, float] = {}
    for entry in timing_history or []:
        name = entry.agent_name.lower()
        totals[name] = round(totals.get(name, 0.0) + entry.duration_seconds, 3)
    return totals


def _bench_trial(fixture: BugFixture, *, merge: bool) -> dict:
    """Run one break → fix → (merge) → test cycle and return its metrics."""
    from app.services.almas.supervisor import ALMASSupervisor

    # Determine fixture level for per-level pass-rate breakdown.
    level = "medium" if fixture in MEDIUM_BUG_FIXTURES else "easy"

    started = time.time()
    harness.inject(fixture)
    harness.git_commit_push(fixture, action="inject")
    ticket = harness.create_ticket(fixture)
    print(f"      ticket {ticket.issue_key} created; running pipeline…", flush=True)

    def printer(stage: str, message: str) -> None:
        print(_paint(stage, f"      └─ [{stage}] {message}"), flush=True)

    # Track whether the Developer's very first output passes the grading test.
    _first_attempt_result: list[bool | None] = []

    def _test_runner_with_tracking(dev):
        result = harness.run_grading_with_changes(fixture, dev)
        if not _first_attempt_result:
            _first_attempt_result.append(bool(result.get("passed")) if result.get("ran") else None)
        return result

    supervisor = ALMASSupervisor()
    detail = supervisor.start_run(
        ticket.issue_key,
        progress=printer,
        test_runner=_test_runner_with_tracking,
    )
    manifest = detail.manifest
    stage_times = _stage_times_from_history(manifest.timing_history)
    pipeline_seconds = round(sum(stage_times.values()), 3)

    # Files changed + LOC from the apply result diffs.
    dev_output = detail.artifacts.developer_output
    files_touched = len(dev_output.changes) if dev_output else 0

    lines_added = 0
    lines_removed = 0
    changed_paths: list[str] = []
    apply_result = detail.artifacts.apply_result
    if apply_result:
        for change in apply_result.applied_changes:
            for line in (change.diff or "").splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    lines_added += 1
                elif line.startswith("-") and not line.startswith("---"):
                    lines_removed += 1
        # Prefer the explicit changed_paths list; fall back to applied_changes.
        changed_paths = list(apply_result.changed_paths) or [
            change.path for change in apply_result.applied_changes
        ]

    # Distinct parent folders touched by the fix.
    folders_changed = len({str(PurePosixPath(p).parent) for p in changed_paths})

    # Which model ran each stage (from the run manifest).
    model_names = manifest.model_names or {}

    fixed: bool | None = None
    pull_request = detail.artifacts.github_pull_request
    if merge and manifest.status == "needs_approval" and pull_request:
        supervisor.merge_run(manifest.run_id)
        try:
            harness.git_pull()
        except harness.HarnessError:
            pass
        passed, _ = harness.verify(fixture)
        fixed = bool(passed)

    failure_mode = _classify_failure(manifest, fixed)
    first_attempt_passed = _first_attempt_result[0] if _first_attempt_result else None

    return {
        "slug": fixture.slug,
        "level": level,
        "issue_key": ticket.issue_key,
        "status": manifest.status,
        "revision_count": manifest.revision_count,
        "files_changed": files_touched,
        "folders_changed": folders_changed,
        "changed_paths": ";".join(changed_paths),
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "first_attempt_passed": first_attempt_passed,
        "failure_mode": failure_mode,
        "prompt_tokens": manifest.total_prompt_tokens,
        "completion_tokens": manifest.total_completion_tokens,
        # Which model ran each stage.
        "analyzer_model": model_names.get("analyzer", ""),
        "planner_model": model_names.get("planner", ""),
        "developer_model": model_names.get("developer", ""),
        "fixer_model": model_names.get("fixer", ""),
        # Per-stage seconds (0.0 when a stage did not run).
        "analyzer_seconds": stage_times.get("analyzer", 0.0),
        "planner_seconds": stage_times.get("planner", 0.0),
        "developer_seconds": stage_times.get("developer", 0.0),
        "fixer_seconds": stage_times.get("fixer", 0.0),
        "pipeline_seconds": pipeline_seconds,
        "total_seconds": round(time.time() - started, 3),
        "fixed": fixed,
    }


def _cmd_bench(args: argparse.Namespace) -> int:
    """Wrap the bench run so all terminal output is also captured to a .log file."""
    run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = harness.BACKEND_DIR / "eval_results"
    out_dir.mkdir(exist_ok=True)
    log_path = out_dir / f"bench-{run_stamp}.log"

    real_stdout, real_stderr = sys.stdout, sys.stderr
    log_handle = log_path.open("w", encoding="utf-8")
    sys.stdout = _Tee(real_stdout, log_handle)
    sys.stderr = _Tee(real_stderr, log_handle)
    try:
        return _run_bench(args, run_stamp, out_dir, log_path)
    finally:
        sys.stdout, sys.stderr = real_stdout, real_stderr
        log_handle.close()


def _preflight_check(fixtures: list[BugFixture]) -> bool:
    """Fast, local checks that a bench run can complete. No API calls or PRs.

    Verifies the things that have historically aborted a run *after* tickets and
    PRs were already created: missing credentials, a fixture whose snippet no
    longer matches the file (so inject would raise), or a missing grading test.
    Returns True when it is safe to proceed.
    """
    from app.config import get_settings

    print("=== PRE-FLIGHT HEALTH CHECK ===")
    settings = get_settings()
    critical = 0
    warnings = 0

    def _line(ok: bool, label: str, detail: str = "") -> None:
        mark = "OK  " if ok else "FAIL"
        print(f"  [{mark}] {label}{(' — ' + detail) if detail else ''}")

    # 1. Credentials / integrations the pipeline needs end-to-end.
    openai_ok = bool(settings.openai_api_key.strip())
    _line(openai_ok, "OpenAI API key", "" if openai_ok else "OPENAI_API_KEY not set")
    critical += 0 if openai_ok else 1

    jira_ok = settings.jira_integration_enabled
    _line(jira_ok, "Jira integration",
          "" if jira_ok else f"missing: {', '.join(settings.jira_missing_required)}")
    critical += 0 if jira_ok else 1

    gh_ok = settings.github_integration_enabled
    _line(gh_ok, "GitHub integration",
          "" if gh_ok else "GITHUB_TOKEN / GITHUB_REPO not set")
    critical += 0 if gh_ok else 1

    git_ok = harness._git(["rev-parse", "--is-inside-work-tree"]).returncode == 0
    _line(git_ok, "Git working tree", "" if git_ok else "not inside a git repository")
    critical += 0 if git_ok else 1

    # 2. Every selected fixture can actually be injected and graded.
    not_injectable: list[tuple[str, str]] = []
    already_broken: list[str] = []
    missing_tests: list[str] = []
    for fx in fixtures:
        status = harness.fixture_status(fx)
        if status in ("unknown", "missing"):
            not_injectable.append((fx.slug, status))
        elif status == "broken":
            already_broken.append(fx.slug)
        if fx.test_file and not (harness.BACKEND_DIR / fx.test_file).exists():
            missing_tests.append(fx.slug)

    inj_ok = not not_injectable
    _line(inj_ok, f"Fixtures injectable ({len(fixtures)} selected)",
          "" if inj_ok else f"{len(not_injectable)} cannot be injected")
    for slug, st in not_injectable:
        print(f"         - {slug}: status={st} (correct snippet not found in target file)")
    critical += 0 if inj_ok else 1

    tests_ok = not missing_tests
    _line(tests_ok, "Grading test files present",
          "" if tests_ok else f"{len(missing_tests)} missing")
    for slug in missing_tests:
        print(f"         - {slug}: grading test file not found")
    critical += 0 if tests_ok else 1

    # 3. Non-blocking warnings.
    if already_broken:
        warnings += 1
        print(f"  [WARN] {len(already_broken)} fixture(s) already injected: {', '.join(already_broken)}")
        print("         they will run on the already-broken file; "
              "restore them first for a clean baseline")

    verdict = "PASSED" if critical == 0 else "FAILED"
    print(f"--- {verdict}: {critical} critical issue(s), {warnings} warning(s) ---\n")
    return critical == 0


def _run_bench(args: argparse.Namespace, run_stamp: str, out_dir, log_path) -> int:
    fixtures = _select(args.slugs, args.all, easy=getattr(args, "easy", False), medium=getattr(args, "medium", False))

    if not getattr(args, "skip_health_check", False):
        if not _preflight_check(fixtures):
            print(
                "Aborting before any tickets or PRs are created. Fix the issues above, "
                "or re-run with --skip-health-check to bypass."
            )
            return 2

    rows: list[dict] = []
    errors: list[dict] = []
    trial = 0
    for _ in range(max(1, args.repeat)):
        for fixture in fixtures:
            trial += 1
            print(f"[bench] trial {trial}: {fixture.slug} …", flush=True)
            row = None
            try:
                row = _bench_trial(fixture, merge=not args.no_merge)
            except Exception as exc:  # noqa: BLE001 - one bad trial must not abort the run
                print(f"   !! trial {trial} ERRORED: {exc}", flush=True)
                errors.append({"trial": trial, "slug": fixture.slug, "error": str(exc)})
            finally:
                # Guarantee no bug is left injected on main, whatever the outcome:
                # an exception, a graceful pipeline failure, or a --no-merge run.
                try:
                    if harness.fixture_status(fixture) == "broken":
                        harness.restore(fixture)
                        harness.git_commit_push(fixture, action="restore")
                        print(f"   restored {fixture.slug} (was left injected)", flush=True)
                except Exception as cleanup_exc:  # noqa: BLE001
                    print(f"   (cleanup failed for {fixture.slug}: {cleanup_exc})", flush=True)
            if row is None:
                continue
            row["trial"] = trial
            rows.append(row)
            mark = "✓" if row["fixed"] else ("✗" if row["fixed"] is False else "—")
            print(
                f"   status={row['status']} pipeline={row['pipeline_seconds']}s "
                f"total={row['total_seconds']}s fixed={mark}"
            )

    if not rows:
        print("\n=== RESULTS ===")
        print("no trials completed successfully.")
        if errors:
            print("\n--- errored trials ---")
            for e in errors:
                print(f"  trial {e['trial']:>2}  {e['slug']}: {e['error']}")
        print(f"\nsaved log:  {log_path}")
        return 1

    print("\n=== RESULTS ===")
    print(
        f"{'#':>2}  {'SLUG':<36}{'STATUS':<20}{'REV':>4}{'FILES':>6}"
        f"{'ADD':>5}{'DEL':>5}{'1ST':>5}{'PIPELINE':>10}{'TOTAL':>9}  {'TOKENS':>8}  FIXED"
    )
    for row in rows:
        mark = "✓" if row["fixed"] else ("✗" if row["fixed"] is False else "—")
        first = "✓" if row["first_attempt_passed"] else ("✗" if row["first_attempt_passed"] is False else "—")
        tok = row["prompt_tokens"] + row["completion_tokens"]
        print(
            f"{row['trial']:>2}  {row['slug']:<36}{row['status']:<20}"
            f"{row['revision_count']:>4}{row['files_changed']:>6}"
            f"{row['lines_added']:>5}{row['lines_removed']:>5}"
            f"{first:>5}{row['pipeline_seconds']:>9.2f}s{row['total_seconds']:>8.2f}s"
            f"  {tok:>8}   {mark}"
        )

    from collections import Counter, defaultdict

    graded = [r for r in rows if r["fixed"] is not None]
    fixed_count = sum(1 for r in graded if r["fixed"])
    accuracy = (fixed_count / len(graded) * 100) if graded else 0.0

    first_graded = [r for r in rows if r["first_attempt_passed"] is not None]
    first_pass_count = sum(1 for r in first_graded if r["first_attempt_passed"])
    first_pass_rate = (first_pass_count / len(first_graded) * 100) if first_graded else 0.0

    # Per-level pass rates.
    def _level_rate(level: str) -> str:
        lvl_graded = [r for r in graded if r.get("level") == level]
        if not lvl_graded:
            return "n/a"
        n_fixed = sum(1 for r in lvl_graded if r["fixed"])
        return f"{n_fixed}/{len(lvl_graded)} ({n_fixed / len(lvl_graded) * 100:.1f}%)"

    totals = [r["total_seconds"] for r in rows]
    pipes = [r["pipeline_seconds"] for r in rows]
    prompt_toks = [r["prompt_tokens"] for r in rows]
    completion_toks = [r["completion_tokens"] for r in rows]
    total_toks = [p + c for p, c in zip(prompt_toks, completion_toks)]
    revisions = [r["revision_count"] for r in rows]
    files_changed_list = [r["files_changed"] for r in rows]
    folders_changed_list = [r["folders_changed"] for r in rows]
    lines_added_list = [r["lines_added"] for r in rows]
    lines_removed_list = [r["lines_removed"] for r in rows]

    # Per-stage timing aggregation.
    stage_time_map: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for stage in _PIPELINE_STAGES:
            secs = row.get(f"{stage}_seconds", 0.0)
            if secs > 0:
                stage_time_map[stage].append(secs)

    def _stats(values: list[float], unit: str = "s") -> str:
        if not values:
            return "n/a"
        return (
            f"avg {statistics.mean(values):.2f}{unit} | min {min(values):.2f} | "
            f"med {statistics.median(values):.2f} | max {max(values):.2f}"
        )

    def _istats(values: list[int], unit: str = "") -> str:
        if not values:
            return "n/a"
        return (
            f"avg {statistics.mean(values):.0f}{unit} | min {min(values)} | "
            f"med {statistics.median(values):.0f} | max {max(values)}"
        )

    print("\n=== SUMMARY ===")
    print(f"trials:              {len(rows)}")
    print(f"avg revisions:       {_istats(revisions)}")
    print(f"files changed:       {_istats(files_changed_list)}")
    print(f"folders changed:     {_istats(folders_changed_list)}")
    print(f"lines added:         {_istats(lines_added_list)}")
    print(f"lines removed:       {_istats(lines_removed_list)}")
    print(f"pipeline time:       {_stats(pipes)}")
    print(f"total time:          {_stats(totals)}")
    print(f"prompt tokens:       {_istats(prompt_toks)}")
    print(f"completion tokens:   {_istats(completion_toks)}")
    print(f"total tokens:        {_istats(total_toks)}")

    # Per-stage timing breakdown.
    print("\n--- stage timing ---")
    for stage in _PIPELINE_STAGES:
        vals = stage_time_map.get(stage, [])
        label = f"{stage}:"
        print(f"  {label:<14}{_stats(vals)}")

    # Models used per stage (distinct values observed across all trials).
    print("\n--- models used ---")
    for stage in _PIPELINE_STAGES:
        observed = sorted({r.get(f"{stage}_model", "") for r in rows if r.get(f"{stage}_model")})
        label = f"{stage}:"
        print(f"  {label:<14}{', '.join(observed) if observed else 'n/a'}")

    # Failure mode attribution — which pipeline stage caused failures.
    modes = Counter(r["failure_mode"] for r in rows)
    print("\n--- failure attribution ---")
    for mode, count in sorted(modes.items(), key=lambda x: -x[1]):
        print(f"  {mode:<28} {count:>3}")

    # Trials that raised before producing any metrics (e.g. inject/network errors).
    if errors:
        print("\n--- errored trials (excluded from stats) ---")
        for e in errors:
            print(f"  trial {e['trial']:>2}  {e['slug']}: {e['error']}")

    # Pass-rate headline — most quotable number for the thesis.
    print("\n" + "=" * 50)
    print("  PASS RATE")
    print("=" * 50)
    print(f"  overall:       {fixed_count}/{len(graded)} fixed ({accuracy:.1f}%)")
    print(f"  easy:          {_level_rate('easy')}")
    print(f"  medium:        {_level_rate('medium')}")
    print(f"  first-attempt: {first_pass_count}/{len(first_graded)} ({first_pass_rate:.1f}%)")
    print("=" * 50)

    # --- CSV (one row per trial) ---
    out_path = out_dir / f"bench-{run_stamp}.csv"
    with out_path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "trial", "slug", "level", "issue_key", "status",
                "revision_count", "files_changed", "folders_changed", "changed_paths",
                "lines_added", "lines_removed",
                "first_attempt_passed", "failure_mode",
                "prompt_tokens", "completion_tokens",
                "analyzer_model", "planner_model", "developer_model", "fixer_model",
                "analyzer_seconds", "planner_seconds", "developer_seconds", "fixer_seconds",
                "pipeline_seconds", "total_seconds", "fixed",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    # --- JSON (structured rows + computed summary, for downstream analysis) ---
    by_level: dict[str, dict] = {}
    for lvl in ("easy", "medium", "hard"):
        lvl_graded = [r for r in graded if r.get("level") == lvl]
        if lvl_graded:
            n_fixed = sum(1 for r in lvl_graded if r["fixed"])
            by_level[lvl] = {
                "fixed": n_fixed,
                "graded": len(lvl_graded),
                "rate_pct": round(n_fixed / len(lvl_graded) * 100, 1),
            }

    summary = {
        "accuracy": {
            "fixed": fixed_count,
            "graded": len(graded),
            "rate_pct": round(accuracy, 1),
        },
        "by_level": by_level,
        "first_attempt": {
            "passed": first_pass_count,
            "graded": len(first_graded),
            "rate_pct": round(first_pass_rate, 1),
        },
        "revisions": _numeric_summary(revisions),
        "files_changed": _numeric_summary(files_changed_list),
        "folders_changed": _numeric_summary(folders_changed_list),
        "lines_added": _numeric_summary(lines_added_list),
        "lines_removed": _numeric_summary(lines_removed_list),
        "pipeline_seconds": _numeric_summary(pipes),
        "total_seconds": _numeric_summary(totals),
        "stage_seconds": {
            stage: _numeric_summary(stage_time_map.get(stage, [])) for stage in _PIPELINE_STAGES
        },
        "tokens": {
            "prompt": _numeric_summary(prompt_toks),
            "completion": _numeric_summary(completion_toks),
            "total": _numeric_summary(total_toks),
        },
        "failure_modes": dict(modes),
        "models": {
            stage: sorted({r.get(f"{stage}_model", "") for r in rows if r.get(f"{stage}_model")})
            for stage in _PIPELINE_STAGES
        },
    }
    json_path = out_dir / f"bench-{run_stamp}.json"
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "trials": len(rows),
        "errored_trials": len(errors),
        "repeat": args.repeat,
        "rows": rows,
        "errors": errors,
        "summary": summary,
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print(f"\nsaved CSV:  {out_path}")
    print(f"saved JSON: {json_path}")
    print(f"saved log:  {log_path}")
    if errors:
        print(f"note: {len(errors)} trial(s) errored and were excluded — see 'errors' in the JSON.")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    failures = 0
    for fixture in _select(args.slugs, args.all, easy=getattr(args, "easy", False), medium=getattr(args, "medium", False)):
        passed, tail = harness.verify(fixture)
        if passed is None:
            print(f"[verify] {fixture.slug}: MANUAL ({tail})")
            continue
        label = "PASS" if passed else "FAIL"
        print(f"[verify] {fixture.slug}: {label}")
        if not passed:
            failures += 1
            print(tail)
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# Feature fixture commands
# ---------------------------------------------------------------------------

def _cmd_feature_list(_: argparse.Namespace) -> int:
    print(f"{'SLUG':<36} {'STATUS':<8} TEST FILE")
    print("-" * 80)
    for fixture in FEATURE_FIXTURES:
        status = harness.feature_status(fixture)
        print(f"{fixture.slug:<36} {status:<8} {fixture.test_file}")
    return 0


def _cmd_feature_verify(args: argparse.Namespace) -> int:
    fixture = get_feature(args.slug)
    passed, tail = harness.verify_feature(fixture)
    label = "PASS" if passed else "FAIL"
    print(f"[feature-verify] {fixture.slug}: {label}")
    if not passed:
        print(tail)
    return 0 if passed else 1


def _cmd_feature_flow(args: argparse.Namespace) -> int:
    from app.services.almas.supervisor import ALMASSupervisor

    fixture = get_feature(args.slug)

    # No inject step — the current repo is the pre-state (feature absent).
    print(f"[feature-flow] {fixture.slug}: pre-state is current repo (no injection)")

    if args.issue:
        issue_key = args.issue.upper()
        print(f"[feature-flow] using existing ticket {issue_key}")
    else:
        ticket = harness.create_ticket(fixture)
        issue_key = ticket.issue_key
        print(f"[feature-flow] created ticket {issue_key} {ticket.browse_url}")

    supervisor = ALMASSupervisor()

    def printer(stage: str, message: str) -> None:
        print(_paint(stage, f"   └─ [{stage}] {message}"), flush=True)

    print(f"[feature-flow] starting ALMAS pipeline for {issue_key} …")
    flow_started = time.time()
    detail = supervisor.start_run(
        issue_key,
        progress=printer,
        test_runner=lambda dev: harness.run_feature_grading(fixture, dev),
    )
    manifest = detail.manifest
    print(f"[feature-flow] pipeline finished: status={manifest.status}")
    _print_timings(manifest)

    pull_request = detail.artifacts.github_pull_request
    if manifest.status != "needs_approval" or not pull_request:
        print(f"[feature-flow] no pull request to merge — {manifest.explanation}")
        print(f"[feature-flow] total time: {time.time() - flow_started:.3f}s")
        return 0

    print(f"[feature-flow] PR #{pull_request.number}: {pull_request.html_url or pull_request.url}")

    if args.no_merge:
        print("[feature-flow] --no-merge set; leaving the PR open.")
        print(f"[feature-flow] total time (start → PR): {time.time() - flow_started:.3f}s")
        return 0

    if not args.yes:
        answer = input("Merge this PR? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("[feature-flow] merge skipped; PR left open.")
            print(f"[feature-flow] total time (start → PR): {time.time() - flow_started:.3f}s")
            return 0

    result = supervisor.merge_run(manifest.run_id, delete_branch=args.delete_branch)
    if not result.get("merged"):
        print(f"[feature-flow] merge not completed: {result.get('message')}")
        return 1
    print(f"[feature-flow] merged PR #{result['pr_number']} into {result['base_branch']}.")

    if not args.no_git:
        try:
            print(f"[feature-flow] git pull: {harness.git_pull()}")
        except harness.HarnessError as exc:
            print(f"[feature-flow] warning: {exc}")

    print(f"[feature-flow] grading suite status: {harness.feature_status(fixture)}")
    print(f"[feature-flow] TOTAL TIME: {time.time() - flow_started:.3f}s")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="almas-eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_selection(p: argparse.ArgumentParser, *, git: bool = False) -> argparse.ArgumentParser:
        p.add_argument("slugs", nargs="*", help="Fixture slugs (default: all)")
        p.add_argument("--all", action="store_true", help="Apply to every fixture (easy + medium)")
        p.add_argument("--easy", action="store_true", help="Apply to easy fixtures only")
        p.add_argument("--medium", action="store_true", help="Apply to medium fixtures only")
        if git:
            p.add_argument(
                "--no-git",
                action="store_true",
                help="Do not commit/push the file change to git",
            )
        return p

    # Bug fixture commands
    sub.add_parser("list", help="List bug fixtures and their status").set_defaults(func=_cmd_list)
    add_selection(sub.add_parser("inject", help="Inject bug(s)"), git=True).set_defaults(func=_cmd_inject)
    add_selection(sub.add_parser("restore", help="Restore file(s)"), git=True).set_defaults(func=_cmd_restore)
    add_selection(sub.add_parser("tickets", help="Create Jira ticket(s)")).set_defaults(func=_cmd_tickets)
    add_selection(sub.add_parser("run", help="Inject + git push + create ticket(s)"), git=True).set_defaults(func=_cmd_run)
    add_selection(sub.add_parser("verify", help="Run grading tests")).set_defaults(func=_cmd_verify)

    flow = sub.add_parser(
        "flow",
        help="End-to-end: inject + ticket + run pipeline + optional merge",
    )
    flow.add_argument("slug", help="Fixture slug")
    flow.add_argument("--issue", help="Use an existing Jira issue key instead of creating one")
    flow.add_argument("--yes", action="store_true", help="Merge without prompting")
    flow.add_argument("--no-merge", action="store_true", help="Stop after the PR is created")
    flow.add_argument("--delete-branch", action="store_true", help="Delete the fix branch after merge")
    flow.add_argument("--no-git", action="store_true", help="Do not commit/push/pull git changes")
    flow.set_defaults(func=_cmd_flow)

    bench = sub.add_parser(
        "bench",
        help="Run break→fix→test trials, measuring time + accuracy, and save a CSV",
    )
    bench.add_argument("slugs", nargs="*", help="Fixture slugs (default: all)")
    bench.add_argument("--all", action="store_true", help="Use every fixture (easy + medium)")
    bench.add_argument("--easy", action="store_true", help="Use easy fixtures only")
    bench.add_argument("--medium", action="store_true", help="Use medium fixtures only")
    bench.add_argument("--repeat", type=int, default=1, help="Repeat the selected set N times")
    bench.add_argument("--no-merge", action="store_true", help="Skip merge/grading (timing only)")
    bench.add_argument(
        "--skip-health-check",
        action="store_true",
        help="Skip the pre-flight health check (not recommended)",
    )
    bench.set_defaults(func=_cmd_bench)

    # Feature fixture commands
    sub.add_parser(
        "feature-list",
        help="List feature fixtures and their grading status",
    ).set_defaults(func=_cmd_feature_list)

    feature_verify = sub.add_parser(
        "feature-verify",
        help="Run grading tests for a feature fixture",
    )
    feature_verify.add_argument("slug", help="Feature fixture slug")
    feature_verify.set_defaults(func=_cmd_feature_verify)

    feature_flow = sub.add_parser(
        "feature-flow",
        help="End-to-end: create ticket + run pipeline + optional merge (no injection)",
    )
    feature_flow.add_argument("slug", help="Feature fixture slug")
    feature_flow.add_argument("--issue", help="Use an existing Jira issue key instead of creating one")
    feature_flow.add_argument("--yes", action="store_true", help="Merge without prompting")
    feature_flow.add_argument("--no-merge", action="store_true", help="Stop after the PR is created")
    feature_flow.add_argument("--delete-branch", action="store_true", help="Delete the fix branch after merge")
    feature_flow.add_argument("--no-git", action="store_true", help="Do not pull after merge")
    feature_flow.set_defaults(func=_cmd_feature_flow)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (harness.HarnessError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
