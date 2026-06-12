"""Generate thesis-ready charts from ALMAS bench result CSVs.

Reads one or more ``bench-*.csv`` files produced by ``app.eval.cli bench`` and
writes a set of PNG charts (plus a ``summary.txt``) into an output directory.

Usage:
    python -m app.eval.plot_results eval_results/bench-20260612-143000.csv
    python -m app.eval.plot_results "eval_results/bench-*.csv"
    python -m app.eval.plot_results eval_results/*.csv --output eval_results/plots

Each chart is skipped (with a printed note) when the underlying data is absent,
so the script never crashes on a partial run (e.g. a ``--no-merge`` bench where
``fixed`` is empty for every row).

Requires the optional ``viz`` extras: ``pip install -e ".[viz]"``.
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

try:
    import matplotlib

    matplotlib.use("Agg")  # headless, file-only backend
    import matplotlib.pyplot as plt
    import pandas as pd
    import seaborn as sns
except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
    sys.stderr.write(
        f"error: missing plotting dependency ({exc.name}). "
        'Install with: pip install -e ".[viz]"\n'
    )
    raise SystemExit(2) from exc


# Stable ordering and colours so every chart reads the difficulty axis the same.
LEVEL_ORDER = ["easy", "medium", "hard"]
LEVEL_PALETTE = {"easy": "#4C9F70", "medium": "#E6A817", "hard": "#C8553D"}
STAGES = ["analyzer", "planner", "developer", "fixer"]
STAGE_PALETTE = {
    "analyzer": "#5B8FF9",
    "planner": "#61DDAA",
    "developer": "#F6BD16",
    "fixer": "#E8684A",
}

_TRUTHY = {"true": True, "1": True, "yes": True}
_FALSY = {"false": False, "0": False, "no": False}


def _apply_style() -> None:
    """Publication-friendly defaults: white background, clean serif-ish fonts."""
    sns.set_theme(style="whitegrid", context="talk")
    plt.rcParams.update(
        {
            "figure.dpi": 120,
            "savefig.dpi": 200,
            "savefig.bbox": "tight",
            "axes.titleweight": "bold",
            "axes.titlesize": 16,
            "axes.labelsize": 13,
            "font.size": 12,
            "legend.fontsize": 11,
        }
    )


def _coerce_bool(series: "pd.Series") -> "pd.Series":
    """Map a CSV-read column of True/False/"" into nullable booleans."""

    def _one(value: object) -> object:
        if isinstance(value, bool):
            return value
        if value is None:
            return pd.NA
        text = str(value).strip().lower()
        if text in _TRUTHY:
            return True
        if text in _FALSY:
            return False
        return pd.NA

    return series.map(_one).astype("boolean")


def load_results(paths: list[str]) -> "pd.DataFrame":
    """Read and concatenate every CSV, normalising types and the level column."""
    resolved: list[str] = []
    for pattern in paths:
        matches = glob.glob(pattern)
        if matches:
            resolved.extend(sorted(matches))
        elif Path(pattern).exists():
            resolved.append(pattern)
        else:
            sys.stderr.write(f"warning: no file matched '{pattern}'\n")

    if not resolved:
        raise SystemExit("error: no CSV files found to plot.")

    frames = []
    for path in resolved:
        frame = pd.read_csv(path)
        frame["source_file"] = Path(path).name
        frames.append(frame)
    data = pd.concat(frames, ignore_index=True)

    # Normalise the difficulty level to the known ordered categories.
    if "level" not in data.columns:
        data["level"] = "easy"
    data["level"] = pd.Categorical(
        data["level"].fillna("easy"), categories=LEVEL_ORDER, ordered=True
    )

    for col in ("fixed", "first_attempt_passed"):
        if col in data.columns:
            data[col] = _coerce_bool(data[col])

    # Derived convenience columns.
    if {"prompt_tokens", "completion_tokens"}.issubset(data.columns):
        data["total_tokens"] = (
            data["prompt_tokens"].fillna(0) + data["completion_tokens"].fillna(0)
        )
    if {"lines_added", "lines_removed"}.issubset(data.columns):
        data["lines_changed"] = (
            data["lines_added"].fillna(0) + data["lines_removed"].fillna(0)
        )

    return data


def _levels_present(data: "pd.DataFrame") -> list[str]:
    present = [lvl for lvl in LEVEL_ORDER if (data["level"] == lvl).any()]
    return present or LEVEL_ORDER


def _save(fig, out_dir: Path, name: str) -> Path:
    path = out_dir / name
    fig.savefig(path)
    plt.close(fig)
    print(f"  wrote {path.name}")
    return path


# ---------------------------------------------------------------------------
# Individual charts. Each returns the saved path, or None when skipped.
# ---------------------------------------------------------------------------

def chart_pass_rate_by_level(data: "pd.DataFrame", out_dir: Path) -> Path | None:
    graded = data[data["fixed"].notna()]
    if graded.empty:
        print("  skip pass_rate_by_level (no graded trials — was this a --no-merge run?)")
        return None

    levels = _levels_present(graded)
    rates = [graded[graded["level"] == lvl]["fixed"].mean() * 100 for lvl in levels]
    counts = [int(graded[graded["level"] == lvl]["fixed"].sum()) for lvl in levels]
    totals = [int((graded["level"] == lvl).sum()) for lvl in levels]

    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(levels, rates, color=[LEVEL_PALETTE[lvl] for lvl in levels])
    ax.set_ylim(0, 105)
    ax.set_ylabel("Bugs fixed (%)")
    ax.set_xlabel("Difficulty level")
    ax.set_title("ALMAS pass rate by difficulty")
    for bar, fixed, total in zip(bars, counts, totals):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 2,
            f"{fixed}/{total}",
            ha="center",
            va="bottom",
            fontweight="bold",
        )
    return _save(fig, out_dir, "01_pass_rate_by_level.png")


def chart_pipeline_time_by_level(data: "pd.DataFrame", out_dir: Path) -> Path | None:
    if "pipeline_seconds" not in data.columns or data["pipeline_seconds"].dropna().empty:
        print("  skip pipeline_time_by_level (no pipeline_seconds)")
        return None

    levels = _levels_present(data)
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.boxplot(
        data=data,
        x="level",
        y="pipeline_seconds",
        order=levels,
        hue="level",
        palette=LEVEL_PALETTE,
        legend=False,
        ax=ax,
    )
    sns.stripplot(
        data=data,
        x="level",
        y="pipeline_seconds",
        order=levels,
        color="#2b2b2b",
        size=5,
        alpha=0.5,
        ax=ax,
    )
    ax.set_ylabel("Pipeline time (seconds)")
    ax.set_xlabel("Difficulty level")
    ax.set_title("Pipeline wall-clock time by difficulty")
    return _save(fig, out_dir, "02_pipeline_time_by_level.png")


def chart_stage_timing(data: "pd.DataFrame", out_dir: Path) -> Path | None:
    stage_cols = [f"{s}_seconds" for s in STAGES if f"{s}_seconds" in data.columns]
    if not stage_cols:
        print("  skip stage_timing (no per-stage seconds)")
        return None

    levels = _levels_present(data)
    means = data.groupby("level", observed=True)[stage_cols].mean().reindex(levels)

    fig, ax = plt.subplots(figsize=(9, 6))
    bottom = [0.0] * len(levels)
    for stage in STAGES:
        col = f"{stage}_seconds"
        if col not in means.columns:
            continue
        values = means[col].fillna(0).tolist()
        ax.bar(
            levels,
            values,
            bottom=bottom,
            label=stage.capitalize(),
            color=STAGE_PALETTE[stage],
        )
        bottom = [b + v for b, v in zip(bottom, values)]

    ax.set_ylabel("Mean time per stage (seconds)")
    ax.set_xlabel("Difficulty level")
    ax.set_title("Where pipeline time is spent, by stage")
    ax.legend(title="Stage", bbox_to_anchor=(1.02, 1), loc="upper left")
    return _save(fig, out_dir, "03_stage_timing_breakdown.png")


def chart_first_vs_final(data: "pd.DataFrame", out_dir: Path) -> Path | None:
    if "first_attempt_passed" not in data.columns or "fixed" not in data.columns:
        print("  skip first_vs_final (missing columns)")
        return None
    if data["fixed"].notna().sum() == 0:
        print("  skip first_vs_final (no graded trials)")
        return None

    levels = _levels_present(data)
    first_rates, final_rates = [], []
    for lvl in levels:
        subset = data[data["level"] == lvl]
        first = subset["first_attempt_passed"].dropna()
        final = subset["fixed"].dropna()
        first_rates.append(first.mean() * 100 if not first.empty else 0.0)
        final_rates.append(final.mean() * 100 if not final.empty else 0.0)

    x = range(len(levels))
    width = 0.38
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.bar([i - width / 2 for i in x], first_rates, width, label="First attempt", color="#9DB4C0")
    ax.bar([i + width / 2 for i in x], final_rates, width, label="After revisions", color="#3A6EA5")
    ax.set_xticks(list(x))
    ax.set_xticklabels(levels)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Pass rate (%)")
    ax.set_xlabel("Difficulty level")
    ax.set_title("Value of the revision loop: first attempt vs final")
    ax.legend()
    return _save(fig, out_dir, "04_first_vs_final_pass_rate.png")


def chart_failure_modes(data: "pd.DataFrame", out_dir: Path) -> Path | None:
    if "failure_mode" not in data.columns:
        print("  skip failure_modes (no failure_mode column)")
        return None
    counts = data["failure_mode"].fillna("unknown").value_counts()
    if counts.empty:
        print("  skip failure_modes (no data)")
        return None

    fig, ax = plt.subplots(figsize=(9, max(4, 0.6 * len(counts) + 2)))
    colors = ["#4C9F70" if mode == "none" else "#C8553D" for mode in counts.index]
    ax.barh(counts.index[::-1], counts.values[::-1], color=colors[::-1])
    ax.set_xlabel("Number of trials")
    ax.set_title("Outcome / failure attribution")
    for i, value in enumerate(counts.values[::-1]):
        ax.text(value + 0.05, i, str(int(value)), va="center", fontweight="bold")
    return _save(fig, out_dir, "05_failure_attribution.png")


def chart_token_usage(data: "pd.DataFrame", out_dir: Path) -> Path | None:
    if "total_tokens" not in data.columns or data["total_tokens"].dropna().empty:
        print("  skip token_usage (no token columns)")
        return None

    levels = _levels_present(data)
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.boxplot(
        data=data,
        x="level",
        y="total_tokens",
        order=levels,
        hue="level",
        palette=LEVEL_PALETTE,
        legend=False,
        ax=ax,
    )
    ax.set_ylabel("Total tokens (prompt + completion)")
    ax.set_xlabel("Difficulty level")
    ax.set_title("Token cost by difficulty")
    return _save(fig, out_dir, "06_token_usage_by_level.png")


def chart_lines_changed_vs_outcome(data: "pd.DataFrame", out_dir: Path) -> Path | None:
    if "lines_changed" not in data.columns or "fixed" not in data.columns:
        print("  skip lines_changed_vs_outcome (missing columns)")
        return None
    graded = data[data["fixed"].notna()]
    if graded.empty:
        print("  skip lines_changed_vs_outcome (no graded trials)")
        return None

    levels = _levels_present(graded)
    fixed_means, failed_means = [], []
    for lvl in levels:
        subset = graded[graded["level"] == lvl]
        passed = subset[subset["fixed"]]["lines_changed"]
        failed = subset[~subset["fixed"]]["lines_changed"]
        fixed_means.append(passed.mean() if not passed.empty else 0.0)
        failed_means.append(failed.mean() if not failed.empty else 0.0)

    x = range(len(levels))
    width = 0.38
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.bar([i - width / 2 for i in x], fixed_means, width, label="Fixed", color="#4C9F70")
    ax.bar([i + width / 2 for i in x], failed_means, width, label="Not fixed", color="#C8553D")
    ax.set_xticks(list(x))
    ax.set_xticklabels(levels)
    ax.set_ylabel("Mean lines changed (added + removed)")
    ax.set_xlabel("Difficulty level")
    ax.set_title("Fix size vs outcome")
    ax.legend()
    return _save(fig, out_dir, "07_lines_changed_vs_outcome.png")


def chart_stage_timing_by_model(data: "pd.DataFrame", out_dir: Path) -> Path | None:
    """Optional: only meaningful when more than one model was used for a stage."""
    long_rows = []
    for stage in STAGES:
        sec_col, model_col = f"{stage}_seconds", f"{stage}_model"
        if sec_col not in data.columns or model_col not in data.columns:
            continue
        for _, row in data.iterrows():
            model = row.get(model_col)
            secs = row.get(sec_col)
            if pd.notna(model) and str(model) and pd.notna(secs):
                long_rows.append({"stage": stage.capitalize(), "model": str(model), "seconds": secs})

    if not long_rows:
        print("  skip stage_timing_by_model (no model columns)")
        return None
    long = pd.DataFrame(long_rows)
    if long["model"].nunique() < 2:
        print("  skip stage_timing_by_model (single model — nothing to compare)")
        return None

    fig, ax = plt.subplots(figsize=(11, 6))
    sns.barplot(data=long, x="stage", y="seconds", hue="model", errorbar="sd", ax=ax)
    ax.set_ylabel("Mean time (seconds)")
    ax.set_xlabel("Pipeline stage")
    ax.set_title("Stage time by model")
    ax.legend(title="Model", bbox_to_anchor=(1.02, 1), loc="upper left")
    return _save(fig, out_dir, "08_stage_timing_by_model.png")


def write_summary(data: "pd.DataFrame", out_dir: Path) -> Path:
    """Emit a plain-text headline summary alongside the charts."""
    lines: list[str] = []
    lines.append("ALMAS bench summary")
    lines.append("=" * 50)
    lines.append(f"trials:            {len(data)}")
    lines.append(f"source files:      {', '.join(sorted(data['source_file'].unique()))}")

    graded = data[data["fixed"].notna()] if "fixed" in data.columns else data.iloc[0:0]
    if not graded.empty:
        overall = graded["fixed"].mean() * 100
        lines.append(
            f"overall pass rate: {int(graded['fixed'].sum())}/{len(graded)} ({overall:.1f}%)"
        )
        for lvl in _levels_present(graded):
            subset = graded[graded["level"] == lvl]
            if not subset.empty:
                lines.append(
                    f"  {lvl:<8} {int(subset['fixed'].sum())}/{len(subset)} "
                    f"({subset['fixed'].mean() * 100:.1f}%)"
                )

    if "pipeline_seconds" in data.columns and not data["pipeline_seconds"].dropna().empty:
        lines.append(f"mean pipeline time: {data['pipeline_seconds'].mean():.1f}s")
    if "total_tokens" in data.columns and not data["total_tokens"].dropna().empty:
        lines.append(f"mean total tokens:  {data['total_tokens'].mean():.0f}")

    for stage in STAGES:
        col = f"{stage}_model"
        if col in data.columns:
            models = sorted({str(m) for m in data[col].dropna() if str(m)})
            if models:
                lines.append(f"model[{stage}]: {', '.join(models)}")

    text = "\n".join(lines) + "\n"
    path = out_dir / "summary.txt"
    path.write_text(text, encoding="utf-8")
    print(f"  wrote {path.name}")
    return path


CHARTS = [
    chart_pass_rate_by_level,
    chart_pipeline_time_by_level,
    chart_stage_timing,
    chart_first_vs_final,
    chart_failure_modes,
    chart_token_usage,
    chart_lines_changed_vs_outcome,
    chart_stage_timing_by_model,
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="almas-eval-plot",
        description="Generate charts from ALMAS bench result CSV files.",
    )
    parser.add_argument("csv", nargs="+", help="One or more bench CSV paths or globs")
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output directory for PNGs (default: eval_results/plots)",
    )
    args = parser.parse_args(argv)

    data = load_results(args.csv)

    out_dir = Path(args.output) if args.output else (Path("eval_results") / "plots")
    out_dir.mkdir(parents=True, exist_ok=True)

    _apply_style()
    print(f"plotting {len(data)} trials -> {out_dir}/")
    written = 0
    for chart in CHARTS:
        if chart(data, out_dir) is not None:
            written += 1
    write_summary(data, out_dir)

    print(f"done: {written} chart(s) + summary.txt in {out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
