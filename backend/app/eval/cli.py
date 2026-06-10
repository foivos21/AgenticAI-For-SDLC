"""Command-line interface for the ALMAS evaluation harness.

Run from the ``backend`` directory:

    python -m app.eval.cli list
    python -m app.eval.cli inject --all
    python -m app.eval.cli tickets --all
    python -m app.eval.cli run --all          # inject + create tickets
    python -m app.eval.cli verify --all
    python -m app.eval.cli restore --all
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import statistics
import sys
import time
from datetime import datetime

from app.eval import BUG_FIXTURES, BugFixture, get_fixture
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


def _select(slugs: list[str], use_all: bool) -> list[BugFixture]:
    if use_all or not slugs:
        return list(BUG_FIXTURES)
    return [get_fixture(slug) for slug in slugs]


def _cmd_list(_: argparse.Namespace) -> int:
    print(f"{'SLUG':<28} {'STATUS':<8} TARGET FILE")
    print("-" * 78)
    for fixture in BUG_FIXTURES:
        status = harness.fixture_status(fixture)
        print(f"{fixture.slug:<28} {status:<8} {fixture.target_file}")
    return 0


def _cmd_inject(args: argparse.Namespace) -> int:
    for fixture in _select(args.slugs, args.all):
        changed = harness.inject(fixture)
        state = "injected" if changed else "already broken"
        print(f"[inject] {fixture.slug}: {state}")
        if not args.no_git:
            print(f"[git]    {harness.git_commit_push(fixture, action='inject')}")
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    for fixture in _select(args.slugs, args.all):
        changed = harness.restore(fixture)
        state = "restored" if changed else "already clean"
        print(f"[restore] {fixture.slug}: {state}")
        if not args.no_git:
            print(f"[git]     {harness.git_commit_push(fixture, action='restore')}")
    return 0


def _cmd_tickets(args: argparse.Namespace) -> int:
    for fixture in _select(args.slugs, args.all):
        result = harness.create_ticket(fixture)
        print(f"[ticket] {fixture.slug}: {result.issue_key} {result.browse_url}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    for fixture in _select(args.slugs, args.all):
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


def _bench_trial(fixture: BugFixture, *, merge: bool) -> dict:
    """Run one break → fix → (merge) → test cycle and return its metrics."""
    from app.services.almas.supervisor import ALMASSupervisor

    started = time.time()
    harness.inject(fixture)
    harness.git_commit_push(fixture, action="inject")
    ticket = harness.create_ticket(fixture)
    print(f"      ticket {ticket.issue_key} created; running pipeline…", flush=True)

    def printer(stage: str, message: str) -> None:
        print(_paint(stage, f"      └─ [{stage}] {message}"), flush=True)

    supervisor = ALMASSupervisor()
    detail = supervisor.start_run(
        ticket.issue_key,
        progress=printer,
        test_runner=lambda dev: harness.run_grading_with_changes(fixture, dev),
    )
    manifest = detail.manifest
    pipeline_seconds = round(sum(t.duration_seconds for t in (manifest.timing_history or [])), 3)

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

    return {
        "slug": fixture.slug,
        "issue_key": ticket.issue_key,
        "status": manifest.status,
        "pipeline_seconds": pipeline_seconds,
        "total_seconds": round(time.time() - started, 3),
        "fixed": fixed,
    }


def _cmd_bench(args: argparse.Namespace) -> int:
    fixtures = _select(args.slugs, args.all)
    rows: list[dict] = []
    trial = 0
    for _ in range(max(1, args.repeat)):
        for fixture in fixtures:
            trial += 1
            print(f"[bench] trial {trial}: {fixture.slug} …", flush=True)
            row = _bench_trial(fixture, merge=not args.no_merge)
            row["trial"] = trial
            rows.append(row)
            mark = "✓" if row["fixed"] else ("✗" if row["fixed"] is False else "—")
            print(
                f"   status={row['status']} pipeline={row['pipeline_seconds']}s "
                f"total={row['total_seconds']}s fixed={mark}"
            )

    print("\n=== RESULTS ===")
    print(f"{'#':>2}  {'SLUG':<30}{'STATUS':<16}{'PIPELINE':>9}{'TOTAL':>9}  FIXED")
    for row in rows:
        mark = "✓" if row["fixed"] else ("✗" if row["fixed"] is False else "—")
        print(
            f"{row['trial']:>2}  {row['slug']:<30}{row['status']:<16}"
            f"{row['pipeline_seconds']:>8.2f}s{row['total_seconds']:>8.2f}s   {mark}"
        )

    graded = [r for r in rows if r["fixed"] is not None]
    fixed_count = sum(1 for r in graded if r["fixed"])
    accuracy = (fixed_count / len(graded) * 100) if graded else 0.0
    totals = [r["total_seconds"] for r in rows]
    pipes = [r["pipeline_seconds"] for r in rows]

    def _stats(values: list[float]) -> str:
        if not values:
            return "n/a"
        return (
            f"avg {statistics.mean(values):.2f}s | min {min(values):.2f} | "
            f"med {statistics.median(values):.2f} | max {max(values):.2f}"
        )

    print("\n=== SUMMARY ===")
    print(f"trials:        {len(rows)}")
    print(f"accuracy:      {fixed_count}/{len(graded)} fixed ({accuracy:.1f}%)")
    print(f"pipeline time: {_stats(pipes)}")
    print(f"total time:    {_stats(totals)}")

    out_dir = harness.BACKEND_DIR / "eval_results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"bench-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    with out_path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["trial", "slug", "issue_key", "status", "pipeline_seconds", "total_seconds", "fixed"],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nsaved: {out_path}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    failures = 0
    for fixture in _select(args.slugs, args.all):
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="almas-eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_selection(p: argparse.ArgumentParser, *, git: bool = False) -> argparse.ArgumentParser:
        p.add_argument("slugs", nargs="*", help="Fixture slugs (default: all)")
        p.add_argument("--all", action="store_true", help="Apply to every fixture")
        if git:
            p.add_argument(
                "--no-git",
                action="store_true",
                help="Do not commit/push the file change to git",
            )
        return p

    sub.add_parser("list", help="List fixtures and their status").set_defaults(func=_cmd_list)
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
    bench.add_argument("slugs", nargs="*", help="Fixture slugs (default: all 10)")
    bench.add_argument("--all", action="store_true", help="Use every fixture")
    bench.add_argument("--repeat", type=int, default=1, help="Repeat the selected set N times")
    bench.add_argument("--no-merge", action="store_true", help="Skip merge/grading (timing only)")
    bench.set_defaults(func=_cmd_bench)
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
